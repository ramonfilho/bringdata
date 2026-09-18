"""vigia_pos_deploy.py: a hora depois dos 100%, com rollback automático.

Os dois sinais (feature-report da revisão, 5xx dos logs dela) e o rollback são injetados,
então o que se prova aqui é a decisão e o laço, sem Cloud Run.
"""
import re
import sys
from pathlib import Path
from types import SimpleNamespace

_V2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2 / "scripts"))

import vigia_pos_deploy as vg  # noqa: E402

REV, PREV = "smart-ads-api-01160-abc", "smart-ads-api-01152-wov"
_FEAT_OK = {'ok': True, 'status': 'OK', 'total_batches': 2}
_SEM_5XX = {'rate': 0.0, 'n_5xx': 0, 'total': 120}


def test_julgar_error_no_feature_report_e_rollback():
    v, m = vg.julgar(dict(_FEAT_OK, status='ERROR'), _SEM_5XX)
    assert v == 'ROLLBACK' and 'ERROR' in m[0]


def test_julgar_5xx_com_amostra_e_rollback():
    v, m = vg.julgar(_FEAT_OK, {'rate': 0.04, 'n_5xx': 4, 'total': 100})
    assert v == 'ROLLBACK' and '[5xx] 4 de 100' in m[0]


def test_julgar_5xx_sem_amostra_e_ok():
    v, _ = vg.julgar(_FEAT_OK, {'rate': 0.2, 'n_5xx': 2, 'total': 10})
    assert v == 'OK'


def test_julgar_sem_lote_e_sem_requisicao_e_sem_dados():
    v, _ = vg.julgar({'ok': True, 'status': None, 'total_batches': 0}, {'rate': None, 'n_5xx': 0, 'total': 0})
    assert v == 'SEM_DADOS'


class _Relogio:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _laco(sinais, rodar_rc=0, minutos=60, intervalo=5):
    """Roda vigiar() com relógio falso: cada dormir() avança `intervalo` minutos."""
    rel = _Relogio()
    chamadas = []
    fila = list(sinais)

    def colher():
        return fila.pop(0) if len(fila) > 1 else fila[0]

    def rodar(cmd):
        chamadas.append(cmd)
        return SimpleNamespace(returncode=rodar_rc)

    saida = []
    rc = vg.vigiar(REV, PREV, minutos, intervalo, colher, rodar=rodar, relogio=rel,
                   dormir=lambda s: setattr(rel, 't', rel.t + s), resumo=saida.append)
    return rc, chamadas, saida


def test_hora_inteira_sem_motivo_termina_com_zero_e_sem_rollback():
    rc, chamadas, saida = _laco([(_FEAT_OK, _SEM_5XX)])
    assert rc == 0 and chamadas == []
    assert any("60 min sem motivo" in l for l in saida)
    assert sum("min:" in l for l in saida) == 13  # 0, 5, ..., 60


def test_error_na_terceira_rodada_faz_rollback_e_para():
    sinais = [(_FEAT_OK, _SEM_5XX), (_FEAT_OK, _SEM_5XX), (dict(_FEAT_OK, status='ERROR'), _SEM_5XX)]
    rc, chamadas, saida = _laco(sinais)
    assert rc == 1
    assert len(chamadas) == 1
    assert chamadas[0][1:] == [str(_V2 / "api" / "deploy-gate.sh"), "promote", "--revision", PREV, "--to", "100", "--rollback", "--yes"]
    assert any("ROLLBACK AUTOMÁTICO" in l for l in saida) and any("rollback feito" in l for l in saida)


def test_rollback_que_falha_imprime_o_comando():
    rc, chamadas, saida = _laco([(dict(_FEAT_OK, status='ERROR'), _SEM_5XX)], rodar_rc=1)
    assert rc == 1 and len(chamadas) == 1
    assert any("ROLLBACK FALHOU" in l and f"--revision {PREV} --to 100 --rollback --yes" in l for l in saida)


def test_erro_de_infra_ao_colher_nao_faz_rollback():
    def colher():
        raise RuntimeError("gcloud fora do ar")
    rel = _Relogio()
    chamadas = []
    rc = vg.vigiar(REV, PREV, 10, 5, colher, rodar=lambda c: chamadas.append(c), relogio=rel,
                   dormir=lambda s: setattr(rel, 't', rel.t + s), resumo=lambda *_: None)
    assert rc == 0 and chamadas == []


def test_deploy_yml_tem_o_job_vigia_depois_do_production_e_ignora_o_que_nao_vai_na_imagem():
    wf = (_V2.parent / ".github" / "workflows" / "deploy.yml").read_text()
    m = re.search(r"\n  vigia:\n(.*?)(?=\n  [a-z0-9-]+:\n|\Z)", wf, re.S)
    assert m, "job vigia ausente"
    bloco = m.group(1)
    assert "needs: [canary, retomar, production]" in bloco   # retomar desde 17/09/2026 (janela de deploy)
    assert "scripts/vigia_pos_deploy.py" in bloco and "--rollback" in bloco
    assert "timeout-minutes: 75" in bloco
    ignore = wf.split("paths-ignore:", 1)[1].split("workflow_dispatch:", 1)[0]
    for p in ("'**.md'", "'V2/docs/**'", "'V2/tests/**'", "'.github/**'", "'infra/**'"):
        assert p in ignore, p
    assert "'V2/src/**'" not in ignore and "'V2/api/**'" not in ignore

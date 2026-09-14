"""promover_com_rollback.sh: o degrau de promoção do deploy.yml, com rollback automático.

O script chama três comandos (progression_gate, deploy-gate promote, smoke) que aqui viram
dublês: cada um grava a chamada num arquivo e devolve o exit que o teste manda. O que se
prova é a DECISÃO do script em cada saída do gate, sem tocar em Cloud Run.
"""
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

_V2 = Path(__file__).resolve().parents[1]
_SCRIPT = _V2 / "scripts" / "promover_com_rollback.sh"
REV, PREV = "smart-ads-api-01144-xon", "smart-ads-api-01141-hex"


def _duble(tmp_path, nome, exit_code):
    p = tmp_path / nome
    p.write_text(f'#!/usr/bin/env bash\necho "{nome} $*" >> "{tmp_path}/chamadas"\nexit {exit_code}\n')
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def _roda(tmp_path, gate, promote=0, smoke=0, de="10", para="50"):
    env = dict(os.environ,
               GATE_CMD=_duble(tmp_path, "gate", gate),
               PROMOTE_CMD=_duble(tmp_path, "promote", promote),
               SMOKE_CMD=_duble(tmp_path, "smoke", smoke),
               GITHUB_STEP_SUMMARY=str(tmp_path / "resumo"))
    r = subprocess.run(["bash", str(_SCRIPT), REV, PREV, de, para], env=env,
                       capture_output=True, text=True)
    chamadas = (tmp_path / "chamadas").read_text().splitlines() if (tmp_path / "chamadas").exists() else []
    return r.returncode, chamadas, r.stdout


def test_promote_quando_o_gate_aprova_e_o_smoke_passa(tmp_path):
    rc, chamadas, _ = _roda(tmp_path, gate=0)
    assert rc == 0
    assert chamadas == [
        f"gate --revision {REV} --from 10 --to 50 --rollback {PREV}",
        f"promote --revision {REV} --to 50 --yes",
        f"smoke {REV}",
    ]


def test_primeiros_10_por_cento_passam_pelo_smoke_e_nao_pelo_gate(tmp_path):
    """A 0% o gate devolve HOLD para sempre (sem lote na janela): run 34873411719, 14/09/2026."""
    rc, chamadas, _ = _roda(tmp_path, gate=1, de="0", para="10")
    assert rc == 0
    assert chamadas == [f"smoke {REV}", f"promote --revision {REV} --to 10 --yes", f"smoke {REV}"]


def test_primeiros_10_por_cento_nao_saem_com_smoke_ruim(tmp_path):
    rc, chamadas, out = _roda(tmp_path, gate=0, smoke=1, de="0", para="10")
    assert rc == 1
    assert chamadas == [f"smoke {REV}"]
    assert "Tráfego não mudou" in out


def test_hold_nao_toca_em_trafego(tmp_path):
    rc, chamadas, out = _roda(tmp_path, gate=1)
    assert rc == 1
    assert [c.split()[0] for c in chamadas] == ["gate"], chamadas
    assert "HOLD" in out and "Tráfego não mudou" in out


def test_rollback_do_gate_devolve_100_para_a_anterior(tmp_path):
    rc, chamadas, out = _roda(tmp_path, gate=2, de="10", para="50")
    assert rc == 1
    assert chamadas == [
        f"gate --revision {REV} --from 10 --to 50 --rollback {PREV}",
        f"promote --revision {PREV} --to 100 --rollback --yes",
    ]
    assert "ROLLBACK AUTOMÁTICO" in out


def test_smoke_ruim_depois_do_promote_faz_rollback(tmp_path):
    rc, chamadas, _ = _roda(tmp_path, gate=0, smoke=1, de="50", para="100")
    assert rc == 1
    assert chamadas == [
        f"gate --revision {REV} --from 50 --to 100 --rollback {PREV}",
        f"promote --revision {REV} --to 100 --yes",
        f"smoke {REV}",
        f"promote --revision {PREV} --to 100 --rollback --yes",
    ]


def test_erro_de_infra_nao_toca_em_trafego(tmp_path):
    rc, chamadas, out = _roda(tmp_path, gate=3)
    assert rc == 1
    assert [c.split()[0] for c in chamadas] == ["gate"]
    assert "infra" in out


def test_rollback_que_falha_imprime_o_comando_manual(tmp_path):
    rc, chamadas, out = _roda(tmp_path, gate=2, promote=1, de="50", para="100")
    assert rc == 1
    assert "ROLLBACK FALHOU" in out and f"--revision {PREV} --to 100 --rollback --yes" in out


@pytest.mark.parametrize("estagio", ["canary-10", "canary-50", "production"])
def test_deploy_yml_usa_o_script_em_cada_degrau(estagio):
    wf = (_V2.parent / ".github" / "workflows" / "deploy.yml").read_text()
    m = re.search(rf"\n  {re.escape(estagio)}:\n(.*?)(?=\n  [a-z0-9-]+:\n|\Z)", wf, re.S)
    assert m, f"job {estagio} não está no deploy.yml"
    bloco = m.group(1)
    assert "scripts/promover_com_rollback.sh" in bloco, f"{estagio} não usa promover_com_rollback.sh"
    assert "deploy-gate.sh promote" not in bloco, f"{estagio} ainda promove sem rollback automático"

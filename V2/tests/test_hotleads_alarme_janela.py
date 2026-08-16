"""O alarme vermelho do HotLeads não pode ficar vermelho PARA SEMPRE.

Contexto (auditoria 16/08/2026): 4 leads foram submetidos durante a pane do
callback (06-14/08) e a resposta da Hotmart bateu no endpoint morto. Eles
ficaram em 'submitted' e envelheceram para FORA da janela de re-submissão de
7 dias — o retorno deles não vem nunca mais. O alarme de idade do PR #195 lia
o mais antigo 'submitted' SEM filtro de janela, então o primeiro DM pós-
conserto acordou "🔴 Retorno da Hotmart parado há 70h" com o retorno
comprovadamente saudável (950 selos nas mesmas 24h). Vermelho permanente
treina o operador a ignorar o bloco — e mascara a parada real futura.

Desenho novo: o alarme de idade só olha lead que o re-submit de 6h ainda PODE
pegar (dentro da janela); os envelhecidos viram `presos_fora_da_janela`, uma
linha própria de pendência manual (🧟), visível mas nunca vermelha.

Rodável sem pytest: python tests/test_hotleads_alarme_janela.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.monitoring.hotleads_summary import compute_hotleads_summary
from src.monitoring.digest import _slack_hotleads_24h, _IDADE_RETORNO_ALARME_H


class ConexaoComRespostas:
    """Fake da casa: registra o SQL e devolve linhas prontas, sem banco."""

    def __init__(self, linha_resumo, fila=0):
        self.chamadas = []
        self._linha = linha_resumo
        self._fila = fila

    def run(self, sql, **params):
        self.chamadas.append((sql, params))
        if 'hotleads_scored_at' in sql:
            return [self._linha]
        return [[self._fila]]


def _resumo(linha, fila=0, wd=7):
    conn = ConexaoComRespostas(linha, fila)
    out = compute_hotleads_summary(conn=conn, submit_window_days=wd)
    return out, conn


# ────────────────── o SQL respeita a janela de re-submissão ──────────────────

def test_idade_e_aguardando_so_olham_dentro_da_janela():
    """A idade e o "aguardando" têm que carregar o filtro de created_at na
    janela — sem ele, o zumbi de incidente vira vermelho permanente."""
    _out, conn = _resumo([950, 67, 67, 0, 0, 0.0, 4])
    sql = conn.chamadas[0][0]
    assert sql.count("created_at >= NOW() - (:wd * INTERVAL '1 day')") >= 2, \
        "idade E aguardando precisam do filtro de janela"
    assert "created_at < NOW() - (:wd * INTERVAL '1 day')" in sql, \
        "os presos (fora da janela) precisam ser contados à parte"
    assert conn.chamadas[0][1]['wd'] == 7


def test_janela_vem_da_config_nao_de_numero_cravado():
    _out, conn = _resumo([0, 0, 0, 0, 0, 0.0, 0], wd=14)
    assert conn.chamadas[0][1]['wd'] == 14


def test_presos_entram_no_resumo():
    out, _ = _resumo([950, 67, 67, 0, 0, 0.0, 4])
    assert out['presos_fora_da_janela'] == 4
    assert out['aguardando_selo'] == 0
    assert out['idade_max_aguardando_h'] == 0.0
    assert out['disponivel'] is True


def test_esqueleto_tem_a_chave_nova_em_falha_de_leitura():
    """Fail-soft: mesmo sem conseguir ler, a chave existe (o payload_schema
    falha alto em chave produzida sem declarar — e em chave sumida o digest
    leria None; contrato estável evita os dois)."""
    class ConexaoQueQuebra:
        def run(self, *a, **k):
            raise RuntimeError('sem banco')
    out = compute_hotleads_summary(conn=ConexaoQueQuebra())
    assert out['presos_fora_da_janela'] == 0
    assert out['disponivel'] is False


# ─────────────── o digest: zumbi nunca é vermelho, mas é visível ───────────────

def _render(h):
    blocos = []
    _slack_hotleads_24h({'hotleads_24h': h}, blocos)
    return ' '.join(str(b) for b in blocos)


def _h(**kw):
    base = {'disponivel': True, 'selados': 950, 'quentes': 67, 'pct_quentes': 7.1,
            'eventos_enviados': 67, 'erros': 0, 'aguardando_selo': 0,
            'idade_max_aguardando_h': 0.0, 'presos_fora_da_janela': 0,
            'sem_selo_na_janela': 8, 'window_hours': 24}
    base.update(kw)
    return base


def test_o_cenario_do_dm_de_1608_nao_e_mais_vermelho():
    """O caso real: fluxo saudável (950 selos) + 4 presos de incidente.
    Antes: '🔴 Retorno da Hotmart parado há 70h'. Agora: linha 🧟 de pendência."""
    texto = _render(_h(presos_fora_da_janela=4))
    assert '🔴' not in texto
    assert '🧟' in texto and '4 lead(s) preso(s)' in texto
    assert 'não voltam' in texto


def test_parada_real_continua_vermelha():
    """Não-enfraquecimento: lead DENTRO da janela esperando além do limiar
    continua disparando o alarme vermelho."""
    texto = _render(_h(aguardando_selo=12,
                       idade_max_aguardando_h=_IDADE_RETORNO_ALARME_H + 1))
    assert '🔴' in texto and 'Retorno da Hotmart parado' in texto


def test_estado_limpo_sem_linhas_de_diagnostico_alarmantes():
    texto = _render(_h())
    assert '🔴' not in texto and '🧟' not in texto


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))

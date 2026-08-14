"""
Trava as duas metades do conserto do HotLeads de 14/08/2026.

METADE 1 — o selo do ciclo diário não chegava no público.
Havia dois escritores da mesma tabela, com chaves e políticas de conflito
diferentes e nenhum dono: o lote histórico escrevia em `analytics.hotleads_seal`
por email, o ciclo diário escrevia em `registros_ml` por event_id, e ninguém
sincronizava. Medido: a tabela do público congelada em 31/07 com 323.134 linhas
enquanto 19.872 emails já selados pelo ciclo diário nunca chegaram lá.

METADE 2 — o alerta media o lado errado.
De 06 a 14/08 o retorno da Hotmart ficou 8 dias morto e o bloco do relatório não
gritou nenhuma vez. O alarme exigia `selados == 0 AND fila > 0`, e a fila nunca
subia porque o cron continuava drenando: a IDA estava saudável, quem morreu foi a
VOLTA. Os presos apareciam na linha calma "aguardando retorno da Hotmart".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / 'src'))

from src.data import hotleads_seal_writer as escritor  # noqa: E402


class ConexaoFalsa:
    """Registra o SQL sem tocar em banco."""

    def __init__(self):
        self.chamadas = []

    def run(self, sql, **params):
        self.chamadas.append((sql, params))
        return []


# ── Metade 1: o dono único da tabela ─────────────────────────────────────────

def test_politica_de_conflito_e_uma_so():
    """Os dois modos de alimentação compartilham a MESMA cláusula.

    Era a divergência que criou o problema: o escritor antigo sobrescrevia sem
    condição, e uma segunda cópia da cláusula teria nascido com outra regra.
    """
    conn = ConexaoFalsa()
    escritor.upsert_seals(conn, [{'email': 'a@b.com', 'hot': True}])
    escritor.upsert_seals_from_ledger(conn, ['evt-1'])
    assert len(conn.chamadas) == 2
    for sql, _ in conn.chamadas:
        assert escritor._ON_CONFLICT.strip() in sql.strip(), (
            "um dos caminhos deixou de usar a cláusula compartilhada — é assim "
            "que as duas políticas voltam a divergir"
        )


def test_selo_mais_velho_nao_apaga_o_mais_novo():
    """A guarda de recência tem que estar na cláusula, não na intenção.

    O caminho do ledger carrega a data REAL do selo, que pode ser anterior à que
    já está na tabela. Sem esta guarda, um espelhamento tardio apagaria um selo
    mais recente.
    """
    assert 'WHERE EXCLUDED.sealed_at > analytics.hotleads_seal.sealed_at' in \
        escritor._ON_CONFLICT.replace('\n', ' ').replace('  ', ' ')


def test_lista_vazia_nao_toca_o_banco():
    conn = ConexaoFalsa()
    assert escritor.upsert_seals_from_ledger(conn, []) == 0
    assert escritor.upsert_seals_from_ledger(conn, None) == 0
    assert conn.chamadas == []


def test_teto_por_chamada_protege_a_tabela():
    """Sem teto, um dia alguém pede tudo e trava a tabela que o treino lê."""
    conn = ConexaoFalsa()
    n = escritor.upsert_seals_from_ledger(conn, [f'e{i}' for i in range(escritor.MAX_POR_CHAMADA + 500)])
    assert n == escritor.MAX_POR_CHAMADA


def test_o_ciclo_diario_espelha_no_publico():
    """O gancho existe no caminho do webhook — é o que faltava.

    Sem ele o selo vira evento e nunca vira público, que é como o
    "COMPRADORES HOTMART" ficou duas semanas sem receber ninguém.
    """
    fonte = (RAIZ / 'api' / 'hotleads_integration.py').read_text(encoding='utf-8')
    assert 'upsert_seals_from_ledger' in fonte, (
        "o ciclo diário voltou a não espelhar o selo na tabela do público"
    )
    # E o lote histórico não pode ter cópia própria da cláusula.
    assert 'ON CONFLICT (email) DO UPDATE' not in fonte, (
        "store_bulk_seals voltou a ter SQL próprio — a tabela ficou com 2 donos"
    )


# ── Metade 2: o alerta que mede a VOLTA ──────────────────────────────────────

def test_resumo_declara_a_idade_do_mais_antigo():
    from src.monitoring.hotleads_summary import _empty_summary
    assert 'idade_max_aguardando_h' in _empty_summary()


def test_chave_nova_esta_declarada_no_schema_do_payload():
    """Chave no payload sem declaração derruba o daily-check com 500."""
    schema = (RAIZ / 'src' / 'monitoring' / 'payload_schema.py').read_text(encoding='utf-8')
    assert 'hotleads_24h_summary.idade_max_aguardando_h' in schema


def test_alarme_dispara_por_idade_e_nao_por_fila():
    """O cenário exato dos 8 dias mudos: fila zerada, volta morta.

    O cron drenava (fila=0) e havia 2.215 presos. O alarme antigo, que exigia
    fila > 0, ficava calado. O novo tem que gritar.
    """
    from src.monitoring.digest import _slack_hotleads_24h, _IDADE_RETORNO_ALARME_H

    blocos = []
    _slack_hotleads_24h({'hotleads_24h': {
        'disponivel': True, 'selados': 0, 'quentes': 0, 'pct_quentes': 0.0,
        'eventos_enviados': 0, 'erros': 0,
        'sem_selo_na_janela': 0,          # o cron drenou — fila vazia
        'aguardando_selo': 2215,          # presos esperando a volta
        'idade_max_aguardando_h': 192.0,  # 8 dias
    }}, blocos)

    texto = ' '.join(str(b) for b in blocos)
    assert 'Retorno da Hotmart parado' in texto
    assert 'aguardando retorno da Hotmart, o mais antigo' not in texto, (
        "a linha tranquilizadora não pode aparecer quando o retorno está morto"
    )
    assert _IDADE_RETORNO_ALARME_H < 6, (
        "o teto tem que ser menor que o re-submit de 6h, senão o alarme só toca "
        "depois de o próprio sistema já ter tentado se recuperar"
    )


def test_espera_normal_nao_vira_alarme():
    """Guard contra falso positivo: a volta leva ~17s, minutos são normais."""
    from src.monitoring.digest import _slack_hotleads_24h

    blocos = []
    _slack_hotleads_24h({'hotleads_24h': {
        'disponivel': True, 'selados': 900, 'quentes': 70, 'pct_quentes': 7.8,
        'eventos_enviados': 70, 'erros': 0,
        'sem_selo_na_janela': 0, 'aguardando_selo': 12,
        'idade_max_aguardando_h': 0.2,
    }}, blocos)

    texto = ' '.join(str(b) for b in blocos)
    assert 'Retorno da Hotmart parado' not in texto

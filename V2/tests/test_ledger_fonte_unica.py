"""Guarda-corpo: leitura do `registros_ml` por um lugar só.

Trava as duas regressões que derrubaram o relatório de criativo em 28-29/06/2026:

1. O default da fonte de leitura do ledger precisa ser 'cloudsql'. A migração do
   ledger acabou (a tabela `registros_ml` foi dropada do Railway em 24/06), então
   um default 'railway' é mina: qualquer caminho sem a env `LEDGER_READ_SOURCE`
   setada leria uma tabela que não existe mais.

2. O refresh online da `scores_historicos` (api/scores_refresh.py) NÃO pode abrir
   conexão Railway crua. Ele deve ler o `registros_ml` pelo ponto único
   `open_ledger_read_connection`. Foi exatamente isso que quebrou: ele apontava
   `RAILWAY_DB_*` na mão e não seguiu a virada de fonte.

3. O carregador dos backfills locais (scripts/gerar_scores_2026.py,
   `load_ledger_window`) tinha o MESMO bug — lia o `registros_ml` do Railway cru.
   Ele também deve ler pela porta única. (Outros scripts que leem Railway de
   propósito — migração/backup pré-drop — ficam de fora; a checagem é só do corpo
   de `load_ledger_window`, o carregador que alimenta os re-scores dos backfills.)

Contexto arquitetural: `src/data/ledger_connection.py` é o ÚNICO ponto de entrada
de leitura do `registros_ml`. Nenhum outro módulo deve construir conexão crua pra
essa tabela.
"""
import os
import re
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[1]


def test_default_de_leitura_do_ledger_e_cloudsql(monkeypatch):
    """Sem a env setada, a fonte resolve pra 'cloudsql' (migração encerrada)."""
    from src.data.ledger_connection import ledger_read_source

    monkeypatch.delenv("LEDGER_READ_SOURCE", raising=False)
    assert ledger_read_source() == "cloudsql"

    # valor inválido também cai no default seguro
    monkeypatch.setenv("LEDGER_READ_SOURCE", "banana")
    assert ledger_read_source() == "cloudsql"


def test_scores_refresh_nao_abre_conexao_railway_crua():
    """O refresh lê o ledger pelo ponto único — sem literal de conexão Railway."""
    src = (V2_ROOT / "api" / "scores_refresh.py").read_text()
    assert "RAILWAY_DB" not in src, (
        "scores_refresh.py voltou a abrir conexão Railway crua; o registros_ml "
        "não existe mais no Railway. Use open_ledger_read_connection()."
    )
    assert "open_ledger_read_connection" in src, (
        "scores_refresh.py deve ler o registros_ml pelo ponto único "
        "open_ledger_read_connection (segue LEDGER_READ_SOURCE)."
    )


def test_caminho_da_scores_historicos_delega_o_literal_de_conexao():
    """O caminho do `registros_ml`/`scores_historicos` não carrega literal de
    conexão Cloud SQL próprio — delega pro conector único `open_cloudsql_ledger_connection`.

    Escopo proposital: só os arquivos desta frente (leitura do registros_ml +
    tabela scores_historicos). `analytics_connection.py` é conector-irmão de OUTRA
    frente (schema `analytics`, com search_path próprio, write-capable) e não lê
    `registros_ml` — fica de fora de propósito.
    """
    pat_host = re.compile(r"LEDGER_DB_HOST")
    pat_conn = re.compile(r"pg8000\.native\.Connection")
    no_literal = ["src/data/scores_historicos.py", "api/scores_refresh.py"]
    offenders = []
    for rel in no_literal:
        txt = (V2_ROOT / rel).read_text()
        if pat_host.search(txt) and pat_conn.search(txt):
            offenders.append(rel)
    assert not offenders, (
        f"{offenders} voltou a abrir conexão Cloud SQL crua; delegue pra "
        "open_cloudsql_ledger_connection (ponto único do literal)."
    )


def test_backfill_loader_le_registros_ml_pela_porta_unica():
    """O carregador dos backfills locais (gerar_scores_2026.load_ledger_window),
    que faz `FROM registros_ml`, lê pela porta única — não pelo `_railway_conn`
    cru. Checa só o corpo dessa função: `_railway_conn` segue legítimo em
    `load_lf55_hybrid` (lê `lead_surveys`, tabela só-Railway)."""
    src = (V2_ROOT / "scripts" / "gerar_scores_2026.py").read_text()
    m = re.search(r"def load_ledger_window\(.*?(?=\ndef )", src, re.DOTALL)
    assert m, "load_ledger_window não encontrada em gerar_scores_2026.py"
    body = m.group(0)
    assert "FROM registros_ml" in body, "sanity: load_ledger_window deveria ler registros_ml"
    # Checa a CHAMADA (com paren), não o nome solto — o docstring cita _railway_conn.
    assert "_railway_conn(" not in body, (
        "load_ledger_window voltou a ler o registros_ml do Railway cru; use "
        "open_ledger_read_connection() (registros_ml só existe no Cloud SQL)."
    )
    assert "open_ledger_read_connection(" in body, (
        "load_ledger_window deve ler pela porta única open_ledger_read_connection."
    )

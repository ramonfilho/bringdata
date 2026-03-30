#!/usr/bin/env python3
"""
Exporta leads D9/D10 (ou qualquer faixa de decis) de um período para Excel.

Uso:
    python scripts/export_leads_top_decis.py
    python scripts/export_leads_top_decis.py --start 2026-03-01 --end 2026-03-31
    python scripts/export_leads_top_decis.py --start 2026-03-01 --end 2026-03-31 --decis 8,9,10
    python scripts/export_leads_top_decis.py --start 2026-04-01 --end 2026-04-30 --output "Lead Score Abril 2026 D9-D10"

Saída: files/analises/{nome}.xlsx
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import psycopg2


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

RAILWAY_CONN = {
    "host":     os.getenv("RAILWAY_DB_HOST",     "shortline.proxy.rlwy.net"),
    "port":     int(os.getenv("RAILWAY_DB_PORT", "11594")),
    "dbname":   os.getenv("RAILWAY_DB_NAME",     "railway"),
    "user":     os.getenv("RAILWAY_DB_USER",     "postgres"),
    "password": os.getenv("RAILWAY_DB_PASSWORD", "THxguXxQPZaSWIzquYRiLlVhJBnPoRGu"),
}

OUTPUT_DIR = Path(__file__).parent.parent / "files" / "analises"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_pesquisa(p):
    if p is None:
        return {}
    if isinstance(p, dict):
        return p
    try:
        return json.loads(p)
    except Exception:
        return {}


def faixa_label(decil: int) -> str:
    if decil in (9, 10):
        return "A"
    if decil in (7, 8):
        return "B"
    if decil in (5, 6):
        return "C"
    return "D"


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------

def export_leads(start_date: str, end_date: str, decis: list[int], output_name: str) -> Path:
    """
    Consulta Railway e gera Excel com leads dos decis especificados no período.

    Args:
        start_date:  Data início inclusive (YYYY-MM-DD)
        end_date:    Data fim inclusive (YYYY-MM-DD)
        decis:       Lista de decis inteiros, ex: [9, 10]
        output_name: Nome do arquivo (sem extensão)

    Returns:
        Path do arquivo gerado.
    """
    end_exclusive = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"Conectando ao Railway...")
    conn = psycopg2.connect(**RAILWAY_CONN)
    cur = conn.cursor()

    placeholders = ", ".join(str(d) for d in decis)
    cur.execute(f"""
        SELECT
            "createdAt", "nomeCompleto", email, telefone,
            "leadScore", decil,
            source, campaign, medium, content, term,
            pesquisa, fbc, fbp, "pageUrl"
        FROM "Lead"
        WHERE decil IN ({placeholders})
          AND "createdAt" >= %s
          AND "createdAt" <  %s
        ORDER BY decil DESC, "createdAt"
    """, (start_date, end_exclusive))

    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()

    if not rows:
        print("Nenhum lead encontrado para o período e decis informados.")
        sys.exit(0)

    df_raw = pd.DataFrame(rows, columns=cols)
    pesquisa_df = df_raw["pesquisa"].apply(parse_pesquisa).apply(pd.Series)

    # --- Monta no formato Lead Score ---
    df_out = pd.DataFrame()
    df_out["Data"]          = df_raw["createdAt"].dt.strftime("%Y-%m-%d %H:%M:%S")
    df_out["Nome Completo"] = df_raw["nomeCompleto"]
    df_out["E-mail"]        = df_raw["email"]
    df_out["Telefone"]      = df_raw["telefone"]

    df_out["O seu gênero:"]                                                                      = pesquisa_df.get("genero")
    df_out["Qual a sua idade?"]                                                                  = pesquisa_df.get("idade")
    df_out["O que você faz atualmente?"]                                                         = pesquisa_df.get("ocupacao")
    df_out["Atualmente, qual a sua faixa salarial?"]                                             = pesquisa_df.get("faixaSalarial")
    df_out["Você possui cartão de crédito?"]                                                     = pesquisa_df.get("cartaoCredito")
    df_out["Já estudou programação?"]                                                            = pesquisa_df.get("estudouProgramacao")
    df_out["Você já fez/faz/pretende fazer faculdade?"]                                          = pesquisa_df.get("faculdade")
    df_out["Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro?"] = pesquisa_df.get("investiuCurso")
    df_out["O que mais te chama atenção na profissão de Programador?"]                           = pesquisa_df.get("atracaoProfissao")
    df_out["O que mais você quer ver no evento?"]                                                = pesquisa_df.get("interesseEvento")
    df_out["Tem computador/notebook?"]                                                           = pesquisa_df.get("computador")

    df_out["Source"]   = df_raw["source"]
    df_out["Campaign"] = df_raw["campaign"]
    df_out["Medium"]   = df_raw["medium"]
    df_out["Content"]  = df_raw["content"]
    df_out["Term"]     = df_raw["term"]

    df_out["fbc"]      = df_raw["fbc"]
    df_out["fbp"]      = df_raw["fbp"]
    df_out["Page URL"] = df_raw["pageUrl"]

    df_out["Score"] = df_raw["leadScore"].round(4)
    df_out["Decil"] = df_raw["decil"].apply(lambda d: f"D{int(d):02d}" if pd.notna(d) else "")
    df_out["Faixa"] = df_raw["decil"].apply(lambda d: faixa_label(int(d)) if pd.notna(d) else "")

    for faixa in ("A", "B", "C", "D"):
        df_out[f"Faixa {faixa}"] = df_out["Faixa"].apply(lambda f: "X" if f == faixa else "")

    # --- Salva ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{output_name}.xlsx"

    sheet_name = f"D{min(decis)}-D{max(decis)} {start_date[:7]}"[:31]
    df_out.to_excel(output_path, index=False, sheet_name=sheet_name)

    print(f"\nArquivo: {output_path}")
    print(f"Total:   {len(df_out):,} leads")
    for d in sorted(decis, reverse=True):
        count = (df_raw["decil"] == d).sum()
        print(f"  D{d:02d}: {count:,}")
    print(f"Período: {df_out['Data'].min()} → {df_out['Data'].max()}")

    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    # Defaults: mês corrente
    hoje = datetime.today()
    default_start = hoje.replace(day=1).strftime("%Y-%m-%d")
    default_end   = hoje.strftime("%Y-%m-%d")
    default_label = hoje.strftime("%B %Y").capitalize()

    parser = argparse.ArgumentParser(description="Exporta leads top decis do Railway para Excel.")
    parser.add_argument("--start",  default=default_start,  help="Data início YYYY-MM-DD (padrão: 1º do mês corrente)")
    parser.add_argument("--end",    default=default_end,    help="Data fim   YYYY-MM-DD (padrão: hoje)")
    parser.add_argument("--decis",  default="9,10",         help="Decis separados por vírgula (padrão: 9,10)")
    parser.add_argument("--output", default=None,           help="Nome do arquivo sem extensão")
    args = parser.parse_args()

    decis = [int(d.strip()) for d in args.decis.split(",")]
    decis_label = "-".join(f"D{d}" for d in sorted(decis, reverse=True))

    if args.output:
        output_name = args.output
    else:
        month_label = datetime.strptime(args.start, "%Y-%m-%d").strftime("%B %Y").capitalize()
        output_name = f"Lead Score {month_label} {decis_label}"

    export_leads(args.start, args.end, decis, output_name)


if __name__ == "__main__":
    main()

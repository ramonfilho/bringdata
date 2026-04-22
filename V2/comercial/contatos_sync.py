"""
contatos_sync.py — CSV ↔ Google Sheets sync for commercial contacts tracking.

CSV é fonte autoritativa. Sheet é view + entrada manual pontual.

Uso:
    python V2/comercial/contatos_sync.py --push           # CSV → Sheet
    python V2/comercial/contatos_sync.py --pull           # Sheet → CSV
    python V2/comercial/contatos_sync.py --push --dry-run
    python V2/comercial/contatos_sync.py --pull --dry-run
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import gspread
import pandas as pd
from google.auth import default as gauth_default


# ============================================================
# CONFIG & SCHEMA
# ============================================================

SHEET_ID = "1jJWKPiuFz5SbtQCkqE6CLUPn7FHe7taoQjnRelwcSvI"
WORKSHEET = "Contatos"
CSV_PATH = Path(__file__).parent / "contatos.csv"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    width_px: int
    wrap: bool = False


COLUMNS: list[ColumnSpec] = [
    ColumnSpec("Nome",             180),
    ColumnSpec("Tipo de empresa",  160),
    ColumnSpec("Site",             170),
    ColumnSpec("Email",            220),
    ColumnSpec("Telefone",         120),
    ColumnSpec("Copy",             400, wrap=True),
    ColumnSpec("Status de envio",  130),
    ColumnSpec("Data de envio",    110),
    ColumnSpec("Observações",      300, wrap=True),
]
COLUMN_NAMES = [c.name for c in COLUMNS]
N_COLS = len(COLUMNS)
LAST_COL_LETTER = chr(ord("A") + N_COLS - 1)        # "I"
STATUS_COL_INDEX = COLUMN_NAMES.index("Status de envio")   # 6 (0-indexed)
STATUS_COL_LETTER = chr(ord("A") + STATUS_COL_INDEX)       # "G"

STATUS_VALUES = [
    "A enviar",
    "Enviado",
    "Follow-up",
    "Sem resposta",
    "Reunião agendada",
    "Pós-reunião",
    "Proposta enviada",
    "Fechado",
    "Perdido",
]

# Cor de fundo da LINHA INTEIRA por status
STATUS_ROW_COLORS: dict[str, tuple[float, float, float]] = {
    "Fechado":   (0.82, 0.95, 0.82),  # verde
    "Follow-up": (0.82, 0.92, 1.00),  # azul
    "Enviado":   (1.00, 0.98, 0.80),  # amarelo
    "A enviar":  (1.00, 0.87, 0.87),  # vermelho (inclui status vazio)
}

HEADER_BG  = (0.137, 0.196, 0.263)
HEADER_TXT = (1.0, 1.0, 1.0)
BORDER_RGB = (0.86, 0.86, 0.86)


# ============================================================
# AUTH
# ============================================================

def connect() -> tuple[gspread.Spreadsheet, gspread.Worksheet]:
    creds, _ = gauth_default(scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(WORKSHEET)
    return sh, ws


# ============================================================
# VALIDATION
# ============================================================

class SchemaError(Exception):
    pass


def validate(df: pd.DataFrame, source: str) -> None:
    """Falha alto se df não bater com o schema esperado."""
    actual = list(df.columns)
    if actual != COLUMN_NAMES:
        missing = set(COLUMN_NAMES) - set(actual)
        extra = set(actual) - set(COLUMN_NAMES)
        raise SchemaError(
            f"Schema mismatch em {source}:\n"
            f"  Esperado ({len(COLUMN_NAMES)}): {COLUMN_NAMES}\n"
            f"  Obtido   ({len(actual)}): {actual}\n"
            f"  Faltando: {sorted(missing)}\n"
            f"  Extra: {sorted(extra)}"
        )

    allowed = {""} | set(STATUS_VALUES)
    bad = df[~df["Status de envio"].isin(allowed)]
    if not bad.empty:
        raise SchemaError(
            f"Status fora do enum em {source}:\n"
            f"{bad[['Nome', 'Status de envio']].to_string(index=False)}"
        )


# ============================================================
# CSV I/O
# ============================================================

def load_csv() -> pd.DataFrame:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV não existe: {CSV_PATH}")
    df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False, encoding="utf-8")
    validate(df, source=f"CSV ({CSV_PATH.name})")
    return df


def save_csv(df: pd.DataFrame) -> None:
    validate(df, source="DataFrame antes de salvar CSV")
    df.to_csv(CSV_PATH, index=False, encoding="utf-8")


# ============================================================
# SHEET I/O
# ============================================================

def fetch_sheet_df(ws: gspread.Worksheet) -> pd.DataFrame:
    rows = ws.get_all_values()
    if not rows:
        raise RuntimeError("Sheet vazio.")
    header = [h.strip() for h in rows[0] if h.strip()]
    data: list[list[str]] = []
    for r in rows[1:]:
        padded = (r + [""] * N_COLS)[:N_COLS]
        a_val = padded[0].strip()
        if a_val.lower().startswith("legenda"):
            break                               # pára na legenda
        if not a_val:
            continue                            # pula linhas brancas no meio
        data.append(padded)
    df = pd.DataFrame(data, columns=header[:N_COLS])
    validate(df, source="Sheet")
    return df


def write_sheet_values(ws: gspread.Worksheet, df: pd.DataFrame) -> None:
    # Limpa faixa ampla (valores apenas; formatação vem do UI kit)
    ws.batch_clear([f"A2:{LAST_COL_LETTER}200"])
    values = [COLUMN_NAMES] + df.values.tolist()
    ws.update(
        values=values,
        range_name=f"A1:{LAST_COL_LETTER}{len(df) + 1}",
        value_input_option="USER_ENTERED",
    )


# ============================================================
# UI KIT
# ============================================================

def _rgb_dict(rgb: tuple[float, float, float]) -> dict:
    return {"red": rgb[0], "green": rgb[1], "blue": rgb[2]}


def apply_ui_kit(sh: gspread.Spreadsheet, ws: gspread.Worksheet, n_rows: int) -> None:
    """Freeze + header + corpo + larguras + dropdown + condicional + bordas."""
    sid = ws.id
    last_data_row = n_rows + 1                  # header em 1, dados começam em 2

    ws.freeze(rows=1)

    # Header
    ws.format(f"A1:{LAST_COL_LETTER}1", {
        "backgroundColor": _rgb_dict(HEADER_BG),
        "textFormat": {"bold": True, "fontSize": 11,
                       "foregroundColor": _rgb_dict(HEADER_TXT)},
        "horizontalAlignment": "CENTER",
        "verticalAlignment": "MIDDLE",
        "wrapStrategy": "WRAP",
    })

    # Corpo
    ws.format(f"A2:{LAST_COL_LETTER}{last_data_row}", {
        "backgroundColor": {"red": 1, "green": 1, "blue": 1},
        "textFormat": {"italic": False, "bold": False, "fontSize": 10,
                       "foregroundColor": {"red": 0, "green": 0, "blue": 0}},
        "verticalAlignment": "TOP",
        "horizontalAlignment": "LEFT",
        "wrapStrategy": "WRAP",
    })

    # Monta batch: limpar condicionais + larguras + dropdown + condicionais + bordas
    meta = sh.fetch_sheet_metadata()
    existing_rules = 0
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == sid:
            existing_rules = len(s.get("conditionalFormats", []))
            break

    requests: list[dict] = [
        {"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}}
        for _ in range(existing_rules)
    ]

    # Column widths
    for i, col in enumerate(COLUMNS):
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": col.width_px},
            "fields": "pixelSize",
        }})

    # Altura do header
    requests.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS",
                  "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 36},
        "fields": "pixelSize",
    }})

    # Dropdown na coluna de Status
    requests.append({"setDataValidation": {
        "range": {"sheetId": sid,
                  "startRowIndex": 1, "endRowIndex": last_data_row,
                  "startColumnIndex": STATUS_COL_INDEX,
                  "endColumnIndex": STATUS_COL_INDEX + 1},
        "rule": {
            "condition": {"type": "ONE_OF_LIST",
                          "values": [{"userEnteredValue": v} for v in STATUS_VALUES]},
            "showCustomUi": True,
            "strict": False,
        }
    }})

    # Conditional formatting — linha inteira por status.
    # addConditionalFormatRule com index=0 sempre empurra as existentes para baixo.
    # Ordem de PRIORIDADE final desejada (topo vence):
    #   1. Fechado (verde)
    #   2. Follow-up (azul)
    #   3. Enviado (amarelo)
    #   4. A enviar / status vazio (vermelho)
    # Insiro em ordem INVERSA: vermelho, "A enviar" literal, amarelo, azul, verde.
    def row_rule(formula: str, rgb: tuple[float, float, float]) -> dict:
        return {"addConditionalFormatRule": {
            "rule": {
                "ranges": [{"sheetId": sid,
                            "startRowIndex": 1, "endRowIndex": last_data_row,
                            "startColumnIndex": 0, "endColumnIndex": N_COLS}],
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA",
                                  "values": [{"userEnteredValue": formula}]},
                    "format": {"backgroundColor": _rgb_dict(rgb)},
                }
            },
            "index": 0,
        }}

    # Insertion order (reverse of priority)
    insert_rules = [
        (f'=AND(${STATUS_COL_LETTER}2="",$A2<>"")',   STATUS_ROW_COLORS["A enviar"]),
        (f'=${STATUS_COL_LETTER}2="A enviar"',        STATUS_ROW_COLORS["A enviar"]),
        (f'=${STATUS_COL_LETTER}2="Enviado"',         STATUS_ROW_COLORS["Enviado"]),
        (f'=${STATUS_COL_LETTER}2="Follow-up"',       STATUS_ROW_COLORS["Follow-up"]),
        (f'=${STATUS_COL_LETTER}2="Fechado"',         STATUS_ROW_COLORS["Fechado"]),
    ]
    for formula, rgb in insert_rules:
        requests.append(row_rule(formula, rgb))

    # Bordas
    border = {"style": "SOLID",
              "colorStyle": {"rgbColor": _rgb_dict(BORDER_RGB)}}
    requests.append({"updateBorders": {
        "range": {"sheetId": sid,
                  "startRowIndex": 0, "endRowIndex": last_data_row,
                  "startColumnIndex": 0, "endColumnIndex": N_COLS},
        "innerHorizontal": border, "innerVertical": border,
        "top": border, "bottom": border, "left": border, "right": border,
    }})

    sh.batch_update({"requests": requests})


# ============================================================
# OPERATIONS
# ============================================================

def push(dry_run: bool = False) -> None:
    df = load_csv()
    print(f"CSV válido: {len(df)} linhas, {len(df.columns)} colunas.")
    counts = df["Status de envio"].replace("", "A enviar (vazio)").value_counts()
    print(f"Distribuição de status:\n{counts.to_string()}")
    if dry_run:
        print("\nDRY-RUN: nada foi escrito no Sheet.")
        return
    sh, ws = connect()
    write_sheet_values(ws, df)
    apply_ui_kit(sh, ws, n_rows=len(df))
    print(f"\n✓ Push concluído: {len(df)} linhas escritas + UI kit reaplicado.")


def pull(dry_run: bool = False) -> None:
    sh, ws = connect()
    df_sheet = fetch_sheet_df(ws)
    print(f"Sheet válido: {len(df_sheet)} linhas.")
    if dry_run:
        if CSV_PATH.exists():
            df_csv = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)
            added = set(df_sheet["Nome"]) - set(df_csv["Nome"])
            removed = set(df_csv["Nome"]) - set(df_sheet["Nome"])
            print(f"CSV atual: {len(df_csv)} linhas.")
            print(f"Diff: +{len(added)} -{len(removed)}")
            if added:
                print(f"  Novos: {sorted(added)[:5]}{'...' if len(added) > 5 else ''}")
            if removed:
                print(f"  Removidos: {sorted(removed)[:5]}{'...' if len(removed) > 5 else ''}")
        print("\nDRY-RUN: CSV não foi sobrescrito.")
        return
    save_csv(df_sheet)
    print(f"\n✓ Pull concluído: {len(df_sheet)} linhas escritas em {CSV_PATH.name}.")


# ============================================================
# CLI
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync CSV ↔ Google Sheets para tracking de contatos.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--push", action="store_true", help="CSV → Sheet (CSV é a fonte)")
    mode.add_argument("--pull", action="store_true", help="Sheet → CSV (após edição no browser)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Não grava nada; só valida e mostra diff.")
    args = parser.parse_args()

    try:
        if args.push:
            push(dry_run=args.dry_run)
        elif args.pull:
            pull(dry_run=args.dry_run)
        return 0
    except SchemaError as e:
        print(f"\n✗ Schema error:\n{e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"\n✗ {e.__class__.__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

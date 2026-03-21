"""
Monitoramento Parcial LF47 — Segunda a Quinta (dias 0–3 de vendas).

Para cada lançamento histórico, lê a aba "Detalhes das Conversões" do relatório
mais recente e computa vendas acumuladas por dia relativo ao início do carrinho
(dia 0 = segunda, dia 1 = terça, etc.).

Compara o acumulado dos dias 0–3 do LF47 com o mesmo janela dos lançamentos
anteriores, tanto em números absolutos quanto em % do total final.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from glob import glob
import pandas as pd

_V2_ROOT = Path(__file__).parent.parent

# ──────────────────────────────────────────────────────────────────────────────
# Mapa de períodos: pasta → data de início de vendas (segunda-feira)
# ──────────────────────────────────────────────────────────────────────────────
PERIODOS = [
    ("LF40",  "08:12 - 14:12", date(2025, 12,  8)),
    ("LF41",  "15:12 - 21:12", date(2025, 12, 15)),
    ("LF42",  "22:12 - 28:12", date(2025, 12, 22)),
    ("DEV19", "19:01 - 25:01", date(2026,  1, 19)),
    ("LF43",  "02:02 - 08:02", date(2026,  2,  2)),
    ("LF44",  "09:02 - 15:02", date(2026,  2,  9)),
    ("LF45",  "02:03 - 08:03", date(2026,  3,  2)),
    ("LF46",  "09:03 - 15:03", date(2026,  3,  9)),
    ("LF47",  "16:03 - 22:03", date(2026,  3, 16)),
]

# Até qual dia relativo comparar (0=seg, 1=ter, 2=qua, 3=qui)
CUTOFF_DAY = 3
CUTOFF_HOUR = 13  # 13:00 do dia 3


def latest_report(folder: str) -> Path | None:
    base = _V2_ROOT / "outputs" / "validation" / folder
    if not base.exists():
        return None
    reports = sorted(base.glob("validation_report_*.xlsx"))
    return reports[-1] if reports else None


def load_conversoes(report_path: Path, sales_start: date) -> pd.DataFrame:
    """Lê Detalhes das Conversões e retorna DataFrame com coluna day_offset."""
    df = pd.read_excel(report_path, sheet_name="Detalhes das Conversões", header=2)
    df["Data Venda"] = pd.to_datetime(df["Data Venda"], errors="coerce")
    df = df.dropna(subset=["Data Venda"])
    df["day_offset"] = (df["Data Venda"].dt.date - sales_start).apply(lambda x: x.days)
    return df


def summarise(label: str, df: pd.DataFrame, total_days: int = 7) -> dict:
    total = len(df)
    by_day = df.groupby("day_offset").size()

    # Acumulado por dia
    cumul = {}
    running = 0
    for d in range(total_days):
        running += int(by_day.get(d, 0))
        cumul[d] = running

    through_cutoff = cumul.get(CUTOFF_DAY, running)
    pct = (through_cutoff / total * 100) if total else 0.0

    return {
        "label": label,
        "total_final": total,
        "cutoff_acum": through_cutoff,
        "pct_cutoff": pct,
        "by_day": {d: int(by_day.get(d, 0)) for d in range(total_days)},
        "cumul": cumul,
    }


def main():
    results = []
    lf47_found = False

    for label, folder, sales_start in PERIODOS:
        report = latest_report(folder)
        if report is None:
            print(f"  {label}: pasta não encontrada — {folder}")
            continue
        try:
            df = load_conversoes(report, sales_start)
            if df.empty:
                print(f"  {label}: sem conversões no relatório")
                continue
            s = summarise(label, df)
            s["sales_start"] = sales_start
            s["report"] = report.name
            results.append(s)
            if label == "LF47":
                lf47_found = True
        except Exception as e:
            print(f"  {label}: ERRO — {e}")

    if not results:
        print("Nenhum dado encontrado.")
        sys.exit(1)

    # ──────────────────────────────────────────────────────────────────────────
    # Tabela 1 — Vendas acumuladas por dia (seg→dom)
    # ──────────────────────────────────────────────────────────────────────────
    day_labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    header = f"{'Período':<8} {'Total':>6}  " + "  ".join(f"{d:>5}" for d in day_labels)
    separator = "-" * len(header)

    print()
    print("=" * 70)
    print("  VENDAS ACUMULADAS POR DIA (seg–dom)")
    print(f"  Marcador ★ = até qui 13h (dia de referência LF47 parcial)")
    print("=" * 70)
    print(header)
    print(separator)

    for s in results:
        cumul = s["cumul"]
        cells = []
        for d in range(7):
            val = cumul.get(d, cumul.get(max(cumul.keys(), default=0)))
            marker = " ★" if d == CUTOFF_DAY else "  "
            cells.append(f"{val:>5}{marker}")
        row = f"{s['label']:<8} {s['total_final']:>6}  " + "  ".join(cells)
        print(row)

    # ──────────────────────────────────────────────────────────────────────────
    # Tabela 2 — Comparativo Seg–Qui: LF47 vs histórico
    # ──────────────────────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print(f"  COMPARATIVO: ACUMULADO ATÉ QUI 13H (dias 0–{CUTOFF_DAY})")
    print("=" * 70)
    print(f"{'Período':<8} {'Seg-Qui':>8} {'Total Final':>12} {'% do Total':>11}")
    print("-" * 50)

    historico = [s for s in results if s["label"] != "LF47"]
    lf47 = next((s for s in results if s["label"] == "LF47"), None)

    for s in historico:
        print(f"{s['label']:<8} {s['cutoff_acum']:>8} {s['total_final']:>12} {s['pct_cutoff']:>10.1f}%")

    if historico:
        avg_acum = sum(s["cutoff_acum"] for s in historico) / len(historico)
        avg_total = sum(s["total_final"] for s in historico) / len(historico)
        avg_pct = sum(s["pct_cutoff"] for s in historico) / len(historico)

        # Mediana (excl DEV19 que é outlier de escala)
        sem_dev = [s for s in historico if s["label"] != "DEV19"]
        med_acum = sorted(s["cutoff_acum"] for s in sem_dev)[len(sem_dev) // 2] if sem_dev else 0
        med_total = sorted(s["total_final"] for s in sem_dev)[len(sem_dev) // 2] if sem_dev else 0
        med_pct = sorted(s["pct_cutoff"] for s in sem_dev)[len(sem_dev) // 2] if sem_dev else 0

        print("-" * 50)
        print(f"{'Média':8} {avg_acum:>8.1f} {avg_total:>12.1f} {avg_pct:>10.1f}%")
        print(f"{'Med(excDEV)':8} {med_acum:>8} {med_total:>12} {med_pct:>10.1f}%")

    if lf47:
        print()
        print(f"{'LF47 ★':<8} {lf47['cutoff_acum']:>8} {'(parcial)':>12} {'(parcial)':>11}")
        if historico:
            ratio_acum = lf47["cutoff_acum"] / avg_acum if avg_acum else 0
            ratio_med  = lf47["cutoff_acum"] / med_acum if med_acum else 0
            print()
            print(f"  LF47 Seg–Qui = {lf47['cutoff_acum']} vendas")
            print(f"  vs média histórica:   {ratio_acum:.2f}x  ({'+' if ratio_acum>=1 else ''}{(ratio_acum-1)*100:.0f}%)")
            print(f"  vs mediana (excDEV): {ratio_med:.2f}x  ({'+' if ratio_med>=1 else ''}{(ratio_med-1)*100:.0f}%)")
            print()
            # Projeção
            if sem_dev:
                pct_tipica = med_pct / 100  # % tipicamente fechada até qui
                if pct_tipica > 0:
                    proj = lf47["cutoff_acum"] / pct_tipica
                    print(f"  Projeção total LF47 (se curva típica {med_pct:.0f}% até qui): ~{proj:.0f} vendas")
    else:
        if not lf47_found:
            print()
            print("  ⚠ Relatório LF47 ainda não gerado — rode primeiro o validate_ml_performance.py.")

    # ──────────────────────────────────────────────────────────────────────────
    # Tabela 3 — Distribuição diária (delta, não acumulado)
    # ──────────────────────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("  VENDAS POR DIA (não acumulado)")
    print("=" * 70)
    header2 = f"{'Período':<8}  " + "  ".join(f"{d:>5}" for d in day_labels)
    print(header2)
    print("-" * len(header2))

    for s in results:
        by_day = s["by_day"]
        cells = [f"{by_day.get(d,0):>5}" for d in range(7)]
        marker = "  ★" if s["label"] == "LF47" else ""
        print(f"{s['label']:<8}  " + "  ".join(cells) + marker)

    print()
    print(f"Dados de: {', '.join(s['report'] for s in results)}")


if __name__ == "__main__":
    main()

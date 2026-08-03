"""Job da referência rolante: calcula a conversão de referência + o calibrador da
janela madura (na régua do Challenger) e faz upsert em analytics.reference_rolling.

Roda SEMANALMENTE, pós-maturação (uma janela madura de 90d quase não muda de um dia
pro outro, então diário seria desperdício). O relatório das 06:00 só LÊ a tabela.

Uso:
    python -m scripts.refresh_rolling_reference                 # calcula e grava
    python -m scripts.refresh_rolling_reference --dry-run        # calcula e imprime, não grava
    python -m scripts.refresh_rolling_reference --as-of 2026-07-29
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, datetime

from src.data.matured_window import DEFAULT_MATURATION_DAYS
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_bucket_map(client_id: str):
    """bucket_map (tag→balde) da fonte única do YAML (ABTestConfig). None → o split
    de balde cai no legado; Total/decil/canal seguem intactos."""
    try:
        from src.core.client_config import ABTestConfig
        root = Path(__file__).resolve().parents[1]
        path = root / "configs" / "active_models" / f"{client_id}.yaml"
        return ABTestConfig.from_active_model_yaml(str(path)).campaign_bucket_map()
    except Exception as e:
        logger.warning("[refresh_rolling_reference] bucket_map indisponível: %s", e)
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client", default="devclub")
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD (default hoje)")
    ap.add_argument("--window-days", type=int, default=90)
    ap.add_argument("--maturation-days", type=int, default=DEFAULT_MATURATION_DAYS,
                    help="dias que o lead tem pra comprar (default: ciclo do LF)")
    ap.add_argument("--dry-run", action="store_true", help="calcula e imprime, não grava")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date() if args.as_of else date.today()

    from src.data.analytics_connection import open_analytics_connection
    from src.monitoring.rolling_reference import (
        build_conversion_reference, sample_calibration_curve,
    )
    from src.monitoring.buyer_profile import build_buyer_profile
    from src.data.reference_store import upsert_reference

    conn = open_analytics_connection(timeout=180)
    try:
        ref = build_conversion_reference(
            as_of=as_of, window_days=args.window_days, maturation_days=args.maturation_days,
            client_id=args.client, bucket_map=_resolve_bucket_map(args.client), conn=conn,
        )
        curve = sample_calibration_curve(ref["calibrator"])
        ov = ref["conversion"]["overall"]
        by_dec = ref["conversion"]["by_decile"]
        d10 = (by_dec.get("D10") or {}).get("rate", 0.0)
        print(f"janela {ref['window_start']} → {ref['window_end']} · régua {(ref['ruler_run_id'] or '?')[:8]}")
        print(f"  n_leads={ref['n_leads']:,} · conv geral {ov['rate']*100:.3f}% · D10 {d10*100:.2f}% "
              f"(lift {d10/ov['rate']:.2f}x)" if ov["rate"] else "")
        print(f"  canal/balde de {ref['conversion']['channel_bucket_coverage']['leads_com_utm']:,} leads c/ UTM")

        # Perfil de comprador (Fase 1) — best-effort: janela de COMPRA própria
        # (ancorada em as_of, não na madura), thin/erro não derruba a conversão.
        profile = None
        try:
            profile = build_buyer_profile(
                as_of=as_of, window_days=args.window_days, client_id=args.client, conn=conn,
            )
            print(f"  perfil comprador: {profile['n_buyers_surveyed']:,}/{profile['n_buyers_total']:,} "
                  f"c/ survey (cobertura {profile['coverage']*100:.1f}%)")
        except Exception as e:
            print(f"  perfil comprador: indisponível ({e})")

        if args.dry_run:
            print("[dry-run] nada gravado.")
            return

        upsert_reference(
            conn, client_id=args.client,
            window_start=ref["window_start"], window_end=ref["window_end"], as_of=ref["as_of"],
            ruler_run_id=ref.get("ruler_run_id") or "", n_leads=ref["n_leads"],
            conversion=ref["conversion"], calibration=curve, audience_profile=profile,
        )
        print(f"gravado em analytics.reference_rolling (window_end={ref['window_end']}, source=rolling).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

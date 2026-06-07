"""Job de refresh do lookup de custo por adset (Bloco B/3 do
EVENTOS_E_DECIS_PLANO).

Lê da Meta Insights API o spend e leads agregados da janela móvel dos
últimos N dias (default 30) e popula as tabelas `cpl_adset` e
`ad_to_adset_map` no Railway via UPSERT.

Janela exclui o dia corrente — spend intraday flutua muito. A janela
canônica é `[today() - N, today() - 1]`, garantindo dados consolidados.

Idempotente: rodar 2× no mesmo dia produz o mesmo estado final (UPSERT
sobrescreve com os mesmos números).

Fontes:
  - Spend e leads por adset: `MetaAPIClient.get_daily_adset_metrics`
  - Mapeamento ad→adset:     `MetaAPIClient.get_ad_adset_mapping`
Ambas reusam a camada Meta refinada em `src/validation/meta_api_client.py`
(batch + v24.0, filtro padrão `campaign_name contém 'CAP'`).

CLI:
  RAILWAY_ENV_FILE=/abs/V2/.env python -m src.data.cost_attribution.refresh \\
      --client devclub [--window-days 30] [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefreshStats:
    """Resumo do que o refresh fez. Vai pro log do job e (depois) pra
    coluna de health no `registros_ml`/observabilidade."""
    client_id: str
    window_start: date
    window_end: date
    n_adsets_upserted: int
    n_mappings_upserted: int
    total_spend: float
    total_leads: int
    cpl_global: Optional[float]    # spend / leads no agregado
    duration_seconds: float


def _load_env() -> None:
    """Mesmo pattern de `scripts/create_cpl_tables.py` e `create_registros_ml.py`."""
    if os.environ.get("RAILWAY_DB_HOST") and os.environ.get("RAILWAY_DB_PASSWORD"):
        return
    candidates = []
    if os.environ.get("RAILWAY_ENV_FILE"):
        candidates.append(os.environ["RAILWAY_ENV_FILE"])
    candidates.append(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".env")
    )
    for path in candidates:
        if path and os.path.isfile(path):
            for line in open(path):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


UPSERT_CPL = """
INSERT INTO cpl_adset (
    client_id, adset_id, cpl_30d, n_leads_30d, spend_30d, campaign_id,
    window_start, window_end, updated_at
) VALUES (
    :client_id, :adset_id, :cpl_30d, :n_leads_30d, :spend_30d, :campaign_id,
    :window_start, :window_end, now()
)
ON CONFLICT (client_id, adset_id) DO UPDATE SET
    cpl_30d      = EXCLUDED.cpl_30d,
    n_leads_30d  = EXCLUDED.n_leads_30d,
    spend_30d    = EXCLUDED.spend_30d,
    campaign_id  = EXCLUDED.campaign_id,
    window_start = EXCLUDED.window_start,
    window_end   = EXCLUDED.window_end,
    updated_at   = now();
"""

UPSERT_MAPPING = """
INSERT INTO ad_to_adset_map (
    client_id, campaign_id, ad_name, adset_id, updated_at
) VALUES (
    :client_id, :campaign_id, :ad_name, :adset_id, now()
)
ON CONFLICT (client_id, campaign_id, ad_name) DO UPDATE SET
    adset_id   = EXCLUDED.adset_id,
    updated_at = now();
"""


def refresh_cpl_for_client(
    client_id: str,
    railway_conn,
    meta_client,
    window_days: int = 30,
    today: Optional[date] = None,
    dry_run: bool = False,
) -> RefreshStats:
    """Pega spend + leads + mapeamento ad→adset da Meta e popula Railway.

    Args:
        client_id: identificador lógico do cliente (`devclub`, etc.). Vai
            pra coluna `client_id` das tabelas.
        railway_conn: conexão `pg8000.native.Connection` aberta pro Railway.
        meta_client: instância de `validation.meta_api_client.MetaAPIClient`
            já inicializada com o `account_id` certo. Injetada pra teste.
        window_days: tamanho da janela móvel (default 30).
        today: data de referência (default `date.today()`). Injetada pra
            reprodutibilidade em testes.
        dry_run: se True, calcula tudo mas não escreve nas tabelas.

    Returns:
        `RefreshStats` com resumo do que aconteceu.
    """
    start_clock = datetime.utcnow()
    today = today or date.today()
    window_end = today - timedelta(days=1)
    window_start = today - timedelta(days=window_days)

    logger.info(
        "[refresh_cpl] client=%s window=[%s, %s] dry_run=%s",
        client_id, window_start, window_end, dry_run,
    )

    # 1. Spend + leads por adset por dia → agregar por adset
    df_daily = meta_client.get_daily_adset_metrics(
        date_start=window_start.isoformat(),
        date_end=window_end.isoformat(),
    )
    if df_daily.empty:
        logger.warning("[refresh_cpl] Meta retornou 0 linhas de daily_adset_metrics")
        return RefreshStats(
            client_id=client_id,
            window_start=window_start, window_end=window_end,
            n_adsets_upserted=0, n_mappings_upserted=0,
            total_spend=0.0, total_leads=0, cpl_global=None,
            duration_seconds=(datetime.utcnow() - start_clock).total_seconds(),
        )

    agg = (
        df_daily
        .groupby(['adset_id', 'campaign_id'], as_index=False)
        .agg(spend_30d=('spend_dia', 'sum'), n_leads_30d=('leads_dia', 'sum'))
    )
    # Adsets sem nenhum lead na janela não entram (cpl_30d indefinido).
    # Documentado: aparecem só quando começarem a trazer leads.
    agg = agg[agg['n_leads_30d'] > 0].copy()
    agg['cpl_30d'] = agg['spend_30d'] / agg['n_leads_30d']

    # 2. Mapeamento ad→adset
    df_map = meta_client.get_ad_adset_mapping(
        date_start=window_start.isoformat(),
        date_end=window_end.isoformat(),
    )
    # Pode vir vazio se nenhum anúncio rodou na janela; isso quebra o
    # lookup mais tarde (todo lead cai em `cpl_source=missing`) mas não
    # é falha do refresh em si — vale alertar e seguir.
    if df_map.empty:
        logger.warning("[refresh_cpl] Meta retornou 0 mapeamentos ad→adset")

    # 3. UPSERTs
    n_cpl = 0
    n_map = 0
    if not dry_run:
        for _, row in agg.iterrows():
            railway_conn.run(
                UPSERT_CPL,
                client_id=client_id,
                adset_id=str(row['adset_id']),
                cpl_30d=float(row['cpl_30d']),
                n_leads_30d=int(row['n_leads_30d']),
                spend_30d=float(row['spend_30d']),
                campaign_id=str(row['campaign_id']),
                window_start=window_start,
                window_end=window_end,
            )
            n_cpl += 1

        # `df_map` pode ter o mesmo (campaign_id, ad_name) repetido em
        # múltiplas linhas (ads diferentes com nome igual no mesmo período).
        # O UPSERT na chave (client_id, campaign_id, ad_name) vai garantir
        # idempotência — o último vence. Como todas devem casar com o
        # mesmo adset_id, ordem não importa pro estado final.
        for _, row in df_map.iterrows():
            ad_name = (row.get('ad_name') or '').strip()
            adset_id = str(row.get('adset_id') or '').strip()
            campaign_id = str(row.get('campaign_id') or '').strip()
            if not ad_name or not adset_id or not campaign_id:
                continue
            railway_conn.run(
                UPSERT_MAPPING,
                client_id=client_id,
                campaign_id=campaign_id,
                ad_name=ad_name,
                adset_id=adset_id,
            )
            n_map += 1
    else:
        n_cpl = len(agg)
        n_map = len(df_map)
        logger.info("[refresh_cpl] dry_run=True — nada escrito")

    total_spend = float(agg['spend_30d'].sum())
    total_leads = int(agg['n_leads_30d'].sum())
    cpl_global = total_spend / total_leads if total_leads > 0 else None

    stats = RefreshStats(
        client_id=client_id,
        window_start=window_start, window_end=window_end,
        n_adsets_upserted=n_cpl, n_mappings_upserted=n_map,
        total_spend=total_spend, total_leads=total_leads, cpl_global=cpl_global,
        duration_seconds=(datetime.utcnow() - start_clock).total_seconds(),
    )
    logger.info(
        "[refresh_cpl] OK %d adsets, %d mapeamentos, spend R$ %.2f, %d leads, "
        "CPL global R$ %s, %.1fs",
        stats.n_adsets_upserted, stats.n_mappings_upserted,
        stats.total_spend, stats.total_leads,
        f"{stats.cpl_global:.2f}" if stats.cpl_global else "—",
        stats.duration_seconds,
    )
    return stats


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--client", default="devclub",
                   help="client_id (default devclub)")
    p.add_argument("--account-id", default=None,
                   help="Meta ads account_id. Default = DEFAULT_ACCOUNT_ID "
                        "do MetaAPIClient (DevClub). Multi-cliente futuro "
                        "lê do ClientConfig.meta.")
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--dry-run", action="store_true",
                   help="Não escreve no Railway. Útil pra validar Meta+agg.")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    _load_env()
    required = ("RAILWAY_DB_HOST", "RAILWAY_DB_PORT", "RAILWAY_DB_USER",
                "RAILWAY_DB_PASSWORD", "RAILWAY_DB_NAME")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"[FAIL] env Railway ausente: {missing}")
        return 2

    # Imports tardios pra não pagar custo do `facebook_business` no module
    # load — o refresh job só roda 1×/dia e quem importa este módulo pra
    # tests/lib não precisa do SDK.
    import pg8000.native
    from src.validation.meta_api_client import MetaAPIClient

    conn = pg8000.native.Connection(
        host=os.environ["RAILWAY_DB_HOST"],
        port=int(os.environ["RAILWAY_DB_PORT"]),
        user=os.environ["RAILWAY_DB_USER"],
        password=os.environ["RAILWAY_DB_PASSWORD"],
        database=os.environ["RAILWAY_DB_NAME"],
    )
    meta = MetaAPIClient(account_id=args.account_id)

    try:
        stats = refresh_cpl_for_client(
            client_id=args.client,
            railway_conn=conn,
            meta_client=meta,
            window_days=args.window_days,
            dry_run=args.dry_run,
        )
        print(f"[OK] {stats}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

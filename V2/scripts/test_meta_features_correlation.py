"""
test_meta_features_correlation.py

Testa se métricas diárias da Meta (CPL, CPM, frequência) no dia de captura
do lead são preditivas de compra (target=1).

Join key (adset level):
    utm_content → extrai código DEV-ADxxxx → busca ad_name na Meta API
    → adset_id → métricas diárias do adset naquele dia

Fallback (campaign level):
    Leads com utm_content = '{{ad.name}}' ou sem correspondência no mapeamento
    usam métricas agregadas da campanha no dia.

Fontes de venda: Guru API + Hotmart API + TMB (auto-detect) + Asaas API

Uso:
  python V2/scripts/test_meta_features_correlation.py
  python V2/scripts/test_meta_features_correlation.py --lancamentos LF45 LF46 LF47

Output:
  V2/outputs/validation/meta_features_test/
    leads_enriched_<ts>.csv
    correlation_summary_<ts>.csv
    group_stats_<ts>.csv
    meta_adset_metrics_<ts>.csv
"""

import sys
import re
import argparse
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
from scipy import stats
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / 'V2' / '.env')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

ALL_PERIODS = [
    {
        'name': 'LF43',
        'cap_start': '2026-01-13', 'cap_end': '2026-01-26',
        'vendas_start': '2026-02-02', 'vendas_end': '2026-02-08',
    },
    {
        'name': 'LF44',
        'cap_start': '2026-01-27', 'cap_end': '2026-02-03',
        'vendas_start': '2026-02-09', 'vendas_end': '2026-02-15',
    },
    {
        'name': 'LF45',
        'cap_start': '2026-02-03', 'cap_end': '2026-02-23',
        'vendas_start': '2026-03-02', 'vendas_end': '2026-03-08',
    },
    {
        'name': 'LF46',
        'cap_start': '2026-02-24', 'cap_end': '2026-03-02',
        'vendas_start': '2026-03-09', 'vendas_end': '2026-03-15',
    },
    {
        'name': 'LF47',
        'cap_start': '2026-03-03', 'cap_end': '2026-03-09',
        'vendas_start': '2026-03-16', 'vendas_end': '2026-03-22',
    },
]

META_ACCOUNT_IDS = ['act_188005769808959', 'act_786790755803474']
OUTPUT_DIR = ROOT / 'V2' / 'outputs' / 'validation' / 'meta_features_test'
TMB_DIR    = ROOT / 'V2' / 'data' / 'devclub'

AD_CODE_RE = re.compile(r'(DEV-AD\d+)', re.IGNORECASE)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def extract_ad_code(utm_content) -> str | None:
    """Extrai código de anúncio (DEV-ADxxxx) do utm_content."""
    if pd.isna(utm_content):
        return None
    m = AD_CODE_RE.search(str(utm_content))
    return m.group(1).upper() if m else None


def extract_campaign_id_15(utm_campaign) -> str | None:
    """Extrai campaign_id (15 dígitos) do utm_campaign 'NOME|ID'."""
    if pd.isna(utm_campaign):
        return None
    m = re.search(r'\|\s*(\d{10,})\s*$', str(utm_campaign))
    return m.group(1)[:15] if m else None


def detect_tmb_files() -> list:
    if not TMB_DIR.exists():
        return []
    files = []
    for fpath in TMB_DIR.glob('*.xls*'):
        try:
            cols = pd.read_excel(fpath, nrows=0).columns.tolist()
            if 'Pedido' in cols and 'Parcela' in cols and 'Grau de risco' in cols:
                files.append(str(fpath))
        except Exception:
            pass
    return files


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Leads + Target por período
# ─────────────────────────────────────────────────────────────────────────────

def load_period_data(period: dict, use_cache: bool = True) -> pd.DataFrame:
    from V2.src.validation.data_loader import LeadDataLoader, SalesDataLoader
    from V2.src.validation.matching import match_leads_to_sales

    name = period['name']
    logger.info(f"\n{'─'*60}")
    logger.info(f" {name}: cap {period['cap_start']}→{period['cap_end']}  "
                f"vendas {period['vendas_start']}→{period['vendas_end']}")

    lead_loader = LeadDataLoader()
    leads_df = lead_loader.load_leads_from_sheets(
        start_date=period['cap_start'],
        end_date=period['cap_end'],
        use_cache=use_cache,
    )
    if leads_df.empty:
        logger.warning(f"  Nenhum lead para {name}")
        return pd.DataFrame()
    logger.info(f"  Leads: {len(leads_df)}")

    sales_loader = SalesDataLoader()
    tmb_files = detect_tmb_files()
    guru_df = sales_loader.load_guru_sales_from_api(
        start_date=period['vendas_start'],
        end_date=period['vendas_end'],
        save_excel=False,
        include_canceled=False,
    )
    sales_df = sales_loader.combine_sales(
        guru_df=guru_df,
        tmb_paths=tmb_files or None,
        hotmart_api_start=period['vendas_start'],
        hotmart_api_end=period['vendas_end'],
        asaas_api_start=period['vendas_start'],
        asaas_api_end=period['vendas_end'],
        include_canceled=False,
    )
    logger.info(f"  Vendas: {len(sales_df)}")

    matched = match_leads_to_sales(leads_df, sales_df, use_temporal_validation=False)
    n_buy = int(matched['converted'].sum())
    logger.info(f"  Compradores: {n_buy} ({n_buy/len(matched)*100:.1f}% tracking)")

    matched['lancamento'] = name
    return matched


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Meta: mapeamento ad → adset + métricas diárias de adset
# ─────────────────────────────────────────────────────────────────────────────

def fetch_meta_data(periods: list) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Retorna (ad_adset_map_df, adset_daily_df).

    ad_adset_map_df colunas: ad_code, adset_id, adset_name, campaign_id
    adset_daily_df  colunas: adset_id, date, cpl_dia, cpm_dia, frequency_dia, ...
    """
    from V2.src.validation.meta_api_client import MetaAPIClient

    map_frames   = []
    daily_frames = []

    for period in periods:
        # Uma data-range por período cobre todo o captação
        date_start = period['cap_start']
        date_end   = period['cap_end']

        for account_id in META_ACCOUNT_IDS:
            logger.info(f"  Meta [{account_id}] {period['name']}")
            try:
                client = MetaAPIClient(account_id=account_id)

                # Mapeamento ad_name → adset_id (uma chamada, sem breakdown diário)
                mapping = client.get_ad_adset_mapping(date_start, date_end)
                if not mapping.empty:
                    mapping['ad_code'] = mapping['ad_name'].apply(
                        lambda x: (AD_CODE_RE.search(str(x)) or type('', (), {'group': lambda s, i: None})()).group(1)
                    )
                    mapping['ad_code'] = mapping['ad_name'].apply(extract_ad_code)
                    map_frames.append(mapping[['ad_code', 'adset_id', 'adset_name', 'campaign_id']].dropna(subset=['ad_code']))
                    logger.info(f"    Mapeamento: {len(mapping)} anúncios")

                # Métricas diárias por adset
                daily = client.get_daily_adset_metrics(date_start, date_end)
                if not daily.empty:
                    daily['lancamento'] = period['name']
                    daily_frames.append(daily)
                    logger.info(f"    Adset diário: {len(daily)} linhas")

            except Exception as e:
                logger.warning(f"    Erro: {e}")

    ad_map   = pd.concat(map_frames,   ignore_index=True).drop_duplicates('ad_code') if map_frames   else pd.DataFrame()
    adset_daily = pd.concat(daily_frames, ignore_index=True)                          if daily_frames else pd.DataFrame()

    return ad_map, adset_daily


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Join leads ↔ métricas Meta
# ─────────────────────────────────────────────────────────────────────────────

def enrich_leads(
    leads_df: pd.DataFrame,
    ad_map: pd.DataFrame,
    adset_daily: pd.DataFrame,
) -> pd.DataFrame:
    """
    Estratégia em dois passos:
    1. utm_content → ad_code → adset_id → métricas do adset no dia (adset-level)
    2. Fallback: campaign_id_15 + date → média ponderada dos adsets da campanha
    """
    leads = leads_df.copy()
    leads['ad_code']         = leads['content'].apply(extract_ad_code)
    leads['campaign_id_15']  = leads['campaign'].apply(extract_campaign_id_15)
    leads['cap_date']        = pd.to_datetime(leads['data_captura']).dt.strftime('%Y-%m-%d')

    adset = adset_daily.copy()
    adset['cap_date'] = pd.to_datetime(adset['date']).dt.strftime('%Y-%m-%d')

    METRIC_COLS = ['cpl_dia', 'cpm_dia', 'frequency_dia', 'spend_dia', 'impressions_dia', 'leads_dia']

    # ── Passo 1: adset-level via ad_code ─────────────────────────────────────
    if not ad_map.empty and not adset.empty:
        leads = leads.merge(
            ad_map[['ad_code', 'adset_id']],
            on='ad_code', how='left',
        )
        adset_keyed = adset[['adset_id', 'cap_date'] + METRIC_COLS]
        leads = leads.merge(adset_keyed, on=['adset_id', 'cap_date'], how='left')
    else:
        leads['adset_id'] = None
        for c in METRIC_COLS:
            leads[c] = None

    n_adset = leads['cpl_dia'].notna().sum()
    logger.info(f"  Join adset-level: {n_adset}/{len(leads)} leads")

    # ── Passo 2: fallback campaign-level ─────────────────────────────────────
    if not adset.empty:
        # Agrega adsets → campanha por dia (média ponderada por spend)
        camp_daily = (
            adset.groupby(['campaign_id', 'cap_date'])
            .apply(lambda g: pd.Series({
                'cpl_dia_camp':       (g['spend_dia'].sum() / g['leads_dia'].sum()) if g['leads_dia'].sum() > 0 else None,
                'cpm_dia_camp':       (g['spend_dia'].sum() / g['impressions_dia'].sum() * 1000) if g['impressions_dia'].sum() > 0 else None,
                'frequency_dia_camp': (g['frequency_dia'] * g['impressions_dia']).sum() / g['impressions_dia'].sum() if g['impressions_dia'].sum() > 0 else None,
            }), include_groups=False)
            .reset_index()
        )
        # Ajusta campaign_id para 15 dígitos
        camp_daily['campaign_id_15'] = camp_daily['campaign_id'].astype(str).str[:15]
        camp_daily = camp_daily.drop(columns='campaign_id')

        needs_fallback = leads['cpl_dia'].isna()
        fallback = leads.loc[needs_fallback, ['campaign_id_15', 'cap_date']].merge(
            camp_daily, on=['campaign_id_15', 'cap_date'], how='left'
        )
        leads.loc[needs_fallback, 'cpl_dia']       = fallback['cpl_dia_camp'].values
        leads.loc[needs_fallback, 'cpm_dia']        = fallback['cpm_dia_camp'].values
        leads.loc[needs_fallback, 'frequency_dia']  = fallback['frequency_dia_camp'].values
        leads.loc[needs_fallback, 'join_level']     = 'campaign'
        leads.loc[~needs_fallback & leads['cpl_dia'].notna(), 'join_level'] = 'adset'

    n_total   = len(leads)
    n_matched = leads['cpl_dia'].notna().sum()
    n_fb      = (leads.get('join_level') == 'campaign').sum() if 'join_level' in leads else 0
    logger.info(f"  Total com métricas: {n_matched}/{n_total} "
                f"({n_matched/n_total*100:.1f}%)  —  adset: {n_adset}, fallback campanha: {n_fb}")

    return leads


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Correlação
# ─────────────────────────────────────────────────────────────────────────────

def correlation_analysis(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    FEATURES = {
        'cpl_dia':       'CPL dia (R$)',
        'cpm_dia':       'CPM dia (R$)',
        'frequency_dia': 'Frequência dia',
    }

    valid = df[df['converted'].notna()].copy()
    logger.info(f"\n  Leads para análise: {len(valid)} | "
                f"compradores: {int(valid['converted'].sum())}")

    corr_rows, group_rows = [], []

    for feat, label in FEATURES.items():
        sub = valid[valid[feat].notna()].copy()
        if sub.empty:
            continue

        target    = sub['converted'].astype(int)
        buyers    = sub.loc[sub['converted'] == True,  feat]
        nonbuyers = sub.loc[sub['converted'] == False, feat]

        if len(sub) > 10 and len(buyers) >= 5 and len(nonbuyers) >= 5:
            pb_r, pb_p = stats.pointbiserialr(target, sub[feat])
            t_stat, t_p = stats.ttest_ind(buyers, nonbuyers, equal_var=False)
        else:
            pb_r = pb_p = t_stat = t_p = float('nan')

        sig  = 'SIM' if (not np.isnan(pb_p) and pb_p < 0.05) else 'NÃO'
        direc = (f"compradores têm {'menor' if pb_r < 0 else 'maior'} {label}"
                 if not np.isnan(pb_r) and pb_r != 0 else '—')

        corr_rows.append({
            'feature':           label,
            'n_leads':           len(sub),
            'n_compradores':     len(buyers),
            'n_nao_compradores': len(nonbuyers),
            'r_pointbiserial':   round(pb_r, 4)  if not np.isnan(pb_r)  else None,
            'p_valor':           round(pb_p, 4)  if not np.isnan(pb_p)  else None,
            'significativo_p05': sig,
            'direcao':           direc,
            't_stat':            round(t_stat, 3) if not np.isnan(t_stat) else None,
            't_pval':            round(t_p, 4)   if not np.isnan(t_p)   else None,
        })
        group_rows.append({
            'feature':             label,
            'media_compradores':   round(buyers.mean(),    2) if len(buyers)    > 0 else None,
            'media_nao_comp':      round(nonbuyers.mean(), 2) if len(nonbuyers) > 0 else None,
            'mediana_compradores': round(buyers.median(),  2) if len(buyers)    > 0 else None,
            'mediana_nao_comp':    round(nonbuyers.median(), 2) if len(nonbuyers) > 0 else None,
            'std_compradores':     round(buyers.std(),     2) if len(buyers)    > 0 else None,
            'std_nao_comp':        round(nonbuyers.std(),  2) if len(nonbuyers) > 0 else None,
        })

    return pd.DataFrame(corr_rows), pd.DataFrame(group_rows)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Teste de correlação: métricas diárias Meta × compra'
    )
    parser.add_argument('--lancamentos', nargs='+',
                        help='Ex: LF44 LF45 LF46. Padrão: todos.')
    parser.add_argument('--no-cache', action='store_true')
    args = parser.parse_args()

    periods = [p for p in ALL_PERIODS if p['name'] in args.lancamentos] \
              if args.lancamentos else ALL_PERIODS
    if not periods:
        logger.error(f"Períodos não encontrados: {args.lancamentos}")
        return

    logger.info('=' * 60)
    logger.info(' TESTE: Métricas Meta diárias × Probabilidade de Compra')
    logger.info('=' * 60)
    logger.info(f' Lançamentos: {[p["name"] for p in periods]}')

    # 1. Leads + targets
    logger.info('\n[1/4] Carregando leads e vendas...')
    frames = [load_period_data(p, use_cache=not args.no_cache) for p in periods]
    frames = [f for f in frames if not f.empty]
    if not frames:
        logger.error('Nenhum dado carregado.')
        return
    leads_df = pd.concat(frames, ignore_index=True)
    logger.info(f'\n  Total: {len(leads_df)} leads | {int(leads_df["converted"].sum())} compradores')

    # 2. Meta API
    logger.info('\n[2/4] Buscando dados da Meta API...')
    ad_map, adset_daily = fetch_meta_data(periods)
    if adset_daily.empty:
        logger.error('Nenhuma métrica Meta carregada.')
        return
    logger.info(f'  Mapeamento: {len(ad_map)} ad_codes únicos')
    logger.info(f'  Adset diário: {len(adset_daily)} linhas')

    # 3. Enriquecer
    logger.info('\n[3/4] Fazendo join leads ↔ métricas Meta...')
    enriched = enrich_leads(leads_df, ad_map, adset_daily)

    # 4. Correlação
    logger.info('\n[4/4] Calculando correlações...')
    corr_df, group_df = correlation_analysis(enriched)

    # Salvar
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    enriched.to_csv(    OUTPUT_DIR / f'leads_enriched_{ts}.csv',      index=False)
    corr_df.to_csv(     OUTPUT_DIR / f'correlation_summary_{ts}.csv', index=False)
    group_df.to_csv(    OUTPUT_DIR / f'group_stats_{ts}.csv',         index=False)
    adset_daily.to_csv( OUTPUT_DIR / f'meta_adset_metrics_{ts}.csv',  index=False)
    if not ad_map.empty:
        ad_map.to_csv(  OUTPUT_DIR / f'ad_adset_map_{ts}.csv',        index=False)

    # Resumo
    print('\n' + '=' * 70)
    print(' RESULTADO: CORRELAÇÃO MÉTRICAS META × COMPRA')
    print('=' * 70)
    print(f'\n Lançamentos : {[p["name"] for p in periods]}')
    print(f' Total leads : {len(enriched)}')
    print(f' Compradores : {int(enriched["converted"].sum())}')
    n_adset = (enriched.get('join_level') == 'adset').sum()   if 'join_level' in enriched.columns else 0
    n_camp  = (enriched.get('join_level') == 'campaign').sum() if 'join_level' in enriched.columns else 0
    print(f' Com métricas: {int(enriched["cpl_dia"].notna().sum())} '
          f'(adset: {n_adset}, campanha fallback: {n_camp})\n')

    if not corr_df.empty:
        print(corr_df[['feature', 'n_leads', 'r_pointbiserial',
                        'p_valor', 'significativo_p05', 'direcao']].to_string(index=False))
        print('\n MÉDIAS POR GRUPO:')
        print(group_df.to_string(index=False))

    print(f'\n Outputs: {OUTPUT_DIR}')


if __name__ == '__main__':
    main()

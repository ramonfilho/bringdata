"""
Recompõe ROAS por LF usando 'valor realizado' (dinheiro recebido) em vez de
'valor contratado ajustado por inadimplência'.

Fontes:
  - Guru   : [API] Vendas Guru no raw_data_latest.pkl — status='Aprovada', valor cheio
  - Hotmart: idem, [API] Vendas Hotmart
  - Asaas  : files/validation/cache/asaas_*.parquet — já filtra primeira parcela paga
  - TMB    : data/devclub/pedidos_<...>.xlsx — Data Efetivado not null AND Data Cancelado is null
             Receita TMB = Ticket × (1/12) — TMB padrão de 12 parcelas iguais
             (validado em 5.709 pedidos: p25/p50/p75 do ratio Valor/Ticket = 0.0833)

Atribuição a LF:
  - Grace_days=7d após vendas_end (boletos atrasam até ~1 semana)
  - Sem overlap entre LFs sequenciais (vendas_windows são 1 semana cada)
  - Vendas fora de qualquer janela ficam unmatched

Spend: lido do evolucao_ml_devclub_*.xlsx aba "Resumo" (já consolidado pelo
relatório oficial). Não recomputa.

Output:
  - outputs/analysis/roas_realized.csv
  - print da tabela comparando ROAS_atual (do xlsx) vs ROAS_realized
"""
from __future__ import annotations

import argparse
import logging
import pickle
import re
import sys
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_PKL = REPO_ROOT / 'outputs' / 'cache' / 'raw_data_latest.pkl'
ASAAS_REALIZED = REPO_ROOT / 'outputs' / 'analysis' / 'asaas_realized.parquet'
LAUNCHES_YAML = REPO_ROOT / 'configs' / 'launches.yaml'
EVOLUCAO_XLSX = REPO_ROOT / 'outputs' / 'validation' / 'historico' / 'evolucao_ml_devclub_20260504_180800.xlsx'
TMB_PEDIDOS_GLOB = 'data/devclub/pedidos_*.xlsx'
OUTPUT_CSV = REPO_ROOT / 'outputs' / 'analysis' / 'roas_realized.csv'

TMB_PRIMEIRA_PARCELA_FRAC = 1 / 12  # TMB padrão: 12 parcelas iguais

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def load_launches() -> dict:
    return yaml.safe_load(LAUNCHES_YAML.read_text())


def load_guru_hotmart() -> pd.DataFrame:
    """Vendas Guru + Hotmart, status='Aprovada'. Retorna df com (sale_date, valor, source)."""
    with open(CACHE_PKL, 'rb') as f:
        raw = pickle.load(f)

    out = []
    for key, source in [('[API] Vendas Guru', 'guru'), ('[API] Vendas Hotmart', 'hotmart')]:
        df = raw[key]['Sheet1'].copy()
        df = df[df['status'].str.lower() == 'aprovada']
        df['sale_date'] = pd.to_datetime(df['data'], errors='coerce')
        df['sale_value'] = pd.to_numeric(df['valor'], errors='coerce')
        df = df[df['sale_date'].notna() & df['sale_value'].notna()]
        df['source'] = source
        out.append(df[['sale_date', 'sale_value', 'source']])
    return pd.concat(out, ignore_index=True)


def load_asaas() -> pd.DataFrame:
    """Lê outputs/analysis/asaas_realized.parquet — gerado por
    scripts/refetch_asaas_realized.py. payment.value = valor real
    recebido na cobrança (não ticket cheio). Ids únicos do Asaas (sem dedup
    necessário). billingType e installmentNumber preservados pra debug."""
    if not ASAAS_REALIZED.exists():
        logger.warning(f'  {ASAAS_REALIZED.name} ausente — rode `python -m scripts.refetch_asaas_realized` primeiro')
        return pd.DataFrame(columns=['sale_date', 'sale_value', 'source'])
    df = pd.read_parquet(ASAAS_REALIZED)
    df['sale_date'] = pd.to_datetime(df['sale_date'], errors='coerce')
    df['sale_value'] = pd.to_numeric(df['sale_value'], errors='coerce')
    df = df[df['sale_date'].notna() & df['sale_value'].notna()].copy()
    df['source'] = 'asaas'
    logger.info(f'  Asaas: {len(df)} cobranças (payment.value = real recebido)')
    return df[['sale_date', 'sale_value', 'source']]


def load_tmb_realized() -> pd.DataFrame:
    """TMB do relatório de PEDIDOS (1 linha por pedido):
       - Filtrar: Data Efetivado not null AND Data Cancelado is null
       - Receita por pedido = Ticket × (1/12) — primeira parcela paga
         (validado em 5.709 pedidos: ratio Valor_Parcela/Ticket = 0.0833)
       - sale_date = Data Efetivado (= momento da primeira parcela paga)
    Pega o arquivo mais recente em data/devclub/pedidos_*.xlsx.
    """
    matches = sorted((REPO_ROOT).glob(TMB_PEDIDOS_GLOB), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        logger.warning('  Sem relatório TMB (data/devclub/pedidos_*.xlsx)')
        return pd.DataFrame(columns=['sale_date', 'sale_value', 'source'])
    path = matches[0]
    df = pd.read_excel(path)
    n_total = len(df)
    df['Data Efetivado'] = pd.to_datetime(df['Data Efetivado'], errors='coerce')
    df['Data Cancelado'] = pd.to_datetime(df['Data Cancelado'], errors='coerce')
    df = df[df['Data Efetivado'].notna() & df['Data Cancelado'].isna()]
    df['Ticket do pedido'] = pd.to_numeric(df['Ticket do pedido'], errors='coerce')
    df = df[df['Ticket do pedido'].notna() & (df['Ticket do pedido'] > 0)]
    out = pd.DataFrame({
        'sale_date': df['Data Efetivado'].values,
        'sale_value': df['Ticket do pedido'].values * TMB_PRIMEIRA_PARCELA_FRAC,
        'source': 'tmb_p1',
    })
    logger.info(f'  TMB ({path.name}): {n_total} pedidos → {len(out)} efetivados não-cancelados (1ª parcela = Ticket×1/12)')
    return out


def attribute_to_launch(df_sales: pd.DataFrame, launches: dict, grace_days: int = 7) -> pd.DataFrame:
    """
    Atribui cada venda ao LF cuja janela de vendas [vendas_start, vendas_end + grace]
    contém sale_date. Janelas de vendas dos LFs são típicamente de 1 semana e
    sequenciais — com grace=7d não há overlap entre LFs consecutivos.
    Vendas fora de qualquer janela ficam sem LF.
    """
    df = df_sales.copy()
    df['lf'] = None
    df['_sale_dt'] = pd.to_datetime(df['sale_date'])
    for name, cfg in launches.items():
        vs = pd.to_datetime(cfg.get('vendas_start'))
        ve = pd.to_datetime(cfg.get('vendas_end'))
        if pd.isna(vs) or pd.isna(ve):
            continue
        ve_grace = ve + pd.Timedelta(days=grace_days)
        mask = (df['_sale_dt'] >= vs) & (df['_sale_dt'] <= ve_grace)
        df.loc[mask, 'lf'] = name
    df = df.drop(columns='_sale_dt')
    return df


def load_spend(launches: list) -> pd.DataFrame:
    """Lê 'Gasto total (R$)' por LF da aba Resumo do evolucao_ml.
    Localiza linhas por label de coluna 0 (estrutura da planilha pode variar)."""
    df = pd.read_excel(EVOLUCAO_XLSX, sheet_name='Resumo', header=None)
    label_col = df.iloc[:, 0].astype(str).str.strip()

    def _row_idx(label: str) -> int:
        matches = label_col[label_col == label].index.tolist()
        if not matches:
            raise ValueError(f'Linha "{label}" não encontrada na aba Resumo')
        return matches[0]

    header_idx = _row_idx('Métrica')
    spend_idx = _row_idx('Gasto total (R$)')
    receita_idx = _row_idx('Receita (R$)')
    roas_idx = _row_idx('ROAS')

    header = df.iloc[header_idx].tolist()
    spend_row = df.iloc[spend_idx].tolist()
    receita_row = df.iloc[receita_idx].tolist()
    roas_row = df.iloc[roas_idx].tolist()

    out = []
    for i, name in enumerate(header):
        if not isinstance(name, str) or not name.startswith(('LF', 'DEV')):
            continue
        spend = spend_row[i]
        rec = receita_row[i]
        roas = roas_row[i]
        if isinstance(rec, str):
            rec = float(re.sub(r'[^\d.,]', '', rec).replace(',', ''))
        if isinstance(roas, str):
            roas = float(re.sub(r'[^\d.]', '', roas))
        out.append({'lf': name, 'spend': spend, 'receita_atual': rec, 'roas_atual': roas})
    return pd.DataFrame(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--grace-days', type=int, default=7,
                        help='Dias de tolerância após vendas_end pra atribuir vendas a LF (default: 7)')
    args = parser.parse_args()

    launches = load_launches()
    logger.info('Carregando vendas...')
    df_gh = load_guru_hotmart()
    df_asaas = load_asaas()
    df_tmb = load_tmb_realized()
    df_all = pd.concat([df_gh, df_asaas, df_tmb], ignore_index=True)
    logger.info(f'  Total combinado: {len(df_all)} vendas realizadas')

    df_attr = attribute_to_launch(df_all, launches, grace_days=args.grace_days)
    n_unmatched = df_attr['lf'].isna().sum()
    logger.info(f'  {n_unmatched} vendas sem LF (fora de janelas)')

    # Receita realizada por LF
    receita_realized = (
        df_attr.dropna(subset=['lf'])
        .groupby('lf')['sale_value'].sum().rename('receita_realized')
        .reset_index()
    )
    n_vendas_realized = (
        df_attr.dropna(subset=['lf'])
        .groupby('lf').size().rename('n_vendas_realized')
        .reset_index()
    )
    # Por source
    receita_por_source = (
        df_attr.dropna(subset=['lf'])
        .groupby(['lf', 'source'])['sale_value'].sum().unstack(fill_value=0)
        .reset_index()
    )

    # Spend e ROAS atual do evolucao_ml
    df_spend = load_spend(launches)
    df_out = df_spend.merge(receita_realized, on='lf', how='left').merge(n_vendas_realized, on='lf', how='left')
    df_out['receita_realized'] = df_out['receita_realized'].fillna(0)
    df_out['roas_realized'] = df_out['receita_realized'] / df_out['spend']
    df_out['delta_receita'] = df_out['receita_realized'] - df_out['receita_atual']
    df_out['delta_roas'] = df_out['roas_realized'] - df_out['roas_atual']
    df_out = df_out.merge(receita_por_source, on='lf', how='left').fillna(0)

    # Ordenar por LF cronológico
    lf_order = list(launches.keys())
    df_out['_order'] = df_out['lf'].map({n: i for i, n in enumerate(lf_order)})
    df_out = df_out.sort_values('_order').drop(columns='_order').reset_index(drop=True)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(OUTPUT_CSV, index=False)
    logger.info(f'\n→ CSV salvo em: {OUTPUT_CSV.relative_to(REPO_ROOT)}')

    # Print tabela
    print()
    print('=' * 110)
    print('ROAS REALIZADO vs ATUAL (ajustado por inadimplência TMB) — por lançamento')
    print('=' * 110)
    print(f'{"LF":<8} {"Spend":>10}  {"Rec.atual":>10} {"ROAS at":>7}  {"Rec.real":>10} {"ROAS real":>9}  {"Δ ROAS":>7}  {"Guru":>9} {"Hot":>7} {"Asa":>9} {"TMB(P1)":>9}')
    print('-' * 110)
    for _, r in df_out.iterrows():
        sp = r['spend'] if pd.notna(r['spend']) else 0
        ra = r.get('receita_atual', 0) or 0
        roa_a = r.get('roas_atual', 0) or 0
        rr = r['receita_realized']
        roa_r = r['roas_realized']
        dro = r['delta_roas']
        guru = r.get('guru', 0)
        hot = r.get('hotmart', 0)
        asa = r.get('asaas', 0)
        tmb = r.get('tmb_p1', 0)
        print(f"{r['lf']:<8} {sp:>10,.0f}  {ra:>10,.0f} {roa_a:>6.2f}x  {rr:>10,.0f} {roa_r:>8.2f}x  {dro:>+6.2f}x  {guru:>9,.0f} {hot:>7,.0f} {asa:>9,.0f} {tmb:>9,.0f}")
    print('=' * 110)


if __name__ == '__main__':
    main()

"""
Re-busca vendas Asaas via API preservando billingType e installmentCount —
sem usar product_value (= mantém payment.value, que é o valor REAL DA COBRANÇA).

- Para cobranças únicas (installmentNumber is None): payment.value = ticket cheio recebido (cartão à vista / PIX)
- Para cobranças parceladas (installmentNumber == 1): payment.value = primeira parcela paga

Output: outputs/analysis/asaas_realized.parquet
Schema: email, nome, telefone, sale_value, sale_date, billingType, installmentCount, installmentNumber, payment_id, customer_id

Uso:
  python -m scripts.refetch_asaas_realized --start 2025-12-02 --end 2026-05-09
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.validation.asaas_sales_extractor import AsaasSalesExtractor, PAID_STATUSES  # noqa: E402

OUTPUT_PARQUET = REPO_ROOT / 'outputs' / 'analysis' / 'asaas_realized.parquet'

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def fetch_with_full_metadata(extractor: AsaasSalesExtractor, start: str, end: str) -> pd.DataFrame:
    """Reusa fetch_payments do extractor (já filtra installmentNumber==1 ou null
    e PAID_STATUSES), mas mapeia preservando billingType e installmentCount."""
    payments = extractor.fetch_payments(start, end)
    logger.info(f'Carregando dados de clientes para {len(payments)} pagamentos...')
    customer_ids = sorted({p.get('customer') for p in payments if p.get('customer')})
    customer_cache = extractor.fetch_customers_batch(customer_ids)

    rows = []
    for p in payments:
        cust_id = p.get('customer')
        cust = customer_cache.get(cust_id, {}) if cust_id else {}
        # Email/nome
        email_raw = cust.get('email') or ''
        from src.core.utils import normalizar_email, normalizar_telefone_robusto
        email = normalizar_email(email_raw) if email_raw else None
        phone_raw = cust.get('mobilePhone') or cust.get('phone') or ''
        telefone = normalizar_telefone_robusto(phone_raw) if phone_raw else None
        nome = cust.get('name') or ''

        # Valor REAL DA COBRANÇA (não product_value cheio).
        sale_value = float(p.get('value') or 0)

        # Data
        date_str = p.get('clientPaymentDate') or p.get('paymentDate') or ''
        try:
            sale_date = pd.to_datetime(date_str) if date_str else pd.NaT
        except Exception:
            sale_date = pd.NaT

        rows.append({
            'email': email,
            'nome': nome,
            'telefone': telefone,
            'sale_value': sale_value,
            'sale_date': sale_date,
            'billingType': p.get('billingType'),
            'installmentNumber': p.get('installmentNumber'),
            'installmentCount': p.get('installmentCount'),
            'payment_id': p.get('id'),
            'customer_id': cust_id,
            'status': p.get('status'),
            'origem': 'asaas_realized',
        })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2025-12-02', help='Data inicial (YYYY-MM-DD)')
    parser.add_argument('--end', default=None, help='Data final (YYYY-MM-DD); default=hoje')
    args = parser.parse_args()

    end = args.end or pd.Timestamp.now().strftime('%Y-%m-%d')

    extractor = AsaasSalesExtractor()
    df = fetch_with_full_metadata(extractor, args.start, end)
    df = df[df['sale_date'].notna() & df['email'].notna()]

    OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df_export = df.copy()
    for c in df_export.select_dtypes(include='object').columns:
        df_export[c] = df_export[c].astype('string')
    df_export.to_parquet(OUTPUT_PARQUET, index=False)

    logger.info(f'\nSalvo em {OUTPUT_PARQUET.relative_to(REPO_ROOT)}')
    logger.info(f'  Total: {len(df)} cobranças')
    logger.info(f'\nbillingType:')
    print(df['billingType'].value_counts(dropna=False).to_string())
    logger.info(f'\ninstallmentNumber (None=pagamento simples):')
    print(df['installmentNumber'].value_counts(dropna=False).to_string())
    logger.info(f'\ninstallmentCount (None=pagamento simples):')
    print(df['installmentCount'].value_counts(dropna=False).head(15).to_string())
    logger.info(f'\nsale_value distribuição:')
    print(df['sale_value'].describe().round(2).to_string())


if __name__ == '__main__':
    main()

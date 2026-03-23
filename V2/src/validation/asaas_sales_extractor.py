"""
Extrator de vendas da API do Asaas.

Busca cobranças pagas e retorna no mesmo formato padronizado
usado pelos outros extratores (Guru, TMB, HotPay).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os
import requests
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Optional
import time
import logging

# Carregar variáveis de ambiente do .env (mesmo padrão de validate_ml_performance.py)
_env_file = Path(__file__).parent.parent.parent / '.env'
if _env_file.exists():
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from src.core.utils import normalizar_email, normalizar_telefone_robusto

logger = logging.getLogger(__name__)

ASAAS_BASE_URL = 'https://api.asaas.com/v3'

# Status que representam pagamento efetivo
PAID_STATUSES = {'RECEIVED', 'CONFIRMED', 'RECEIVED_IN_CASH'}


class AsaasSalesExtractor:
    """Extrai vendas pagas da API Asaas."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get('ASAAS_API_KEY')
        if not self.api_key:
            raise ValueError(
                "ASAAS_API_KEY não encontrada. "
                "Defina a variável de ambiente ou passe api_key no construtor."
            )
        self.headers = {
            'access_token': self.api_key,
            'Content-Type': 'application/json',
            'User-Agent': 'SmartAds-ValidationSystem',
        }
        self._customer_cache: Dict[str, Dict] = {}

    def _get(self, endpoint: str, params: Dict = None) -> Dict:
        """Faz GET na API Asaas com retry básico."""
        url = f'{ASAAS_BASE_URL}/{endpoint.lstrip("/")}'
        for attempt in range(3):
            try:
                response = requests.get(url, headers=self.headers, params=params, timeout=30)
                if response.status_code == 429:
                    logger.warning(' Rate limit atingido, aguardando 10s...')
                    time.sleep(10)
                    continue
                if response.status_code != 200:
                    logger.error(f' Erro {response.status_code} em {endpoint}: {response.text[:300]}')
                    return {}
                return response.json()
            except Exception as e:
                logger.error(f' Tentativa {attempt + 1} falhou em {endpoint}: {e}')
                if attempt < 2:
                    time.sleep(2)
        return {}

    def fetch_payments(
        self,
        start_date: str,
        end_date: str,
    ) -> List[Dict[str, Any]]:
        """
        Busca todas as cobranças pagas no período (por clientPaymentDate).

        Args:
            start_date: Data inicial (YYYY-MM-DD)
            end_date: Data final (YYYY-MM-DD)

        Returns:
            Lista de objetos de pagamento da API
        """
        all_payments = []
        offset = 0
        limit = 100
        page = 1

        logger.info(f' Buscando pagamentos Asaas de {start_date} a {end_date}...')

        while True:
            params = {
                'clientPaymentDate[ge]': start_date,
                'clientPaymentDate[le]': end_date,
                'limit': limit,
                'offset': offset,
            }

            data = self._get('/payments', params)
            if not data:
                break

            payments = data.get('data', [])

            # Filtrar apenas status de pagamento efetivo
            # E apenas primeira parcela (installmentNumber == 1 ou ausente = pagamento simples)
            # Parcelas 2, 3, ... são cobranças recorrentes, não novas vendas
            paid = [
                p for p in payments
                if p.get('status') in PAID_STATUSES
                and (p.get('installmentNumber') is None or p.get('installmentNumber') == 1)
            ]
            all_payments.extend(paid)

            logger.debug(f'   Página {page}: {len(payments)} cobranças, {len(paid)} primeiras parcelas/pagamentos únicos')

            if not data.get('hasMore', False):
                break

            offset += limit
            page += 1
            time.sleep(0.2)  # Rate limiting preventivo

        logger.info(f' Total de pagamentos pagos encontrados: {len(all_payments)}')
        return all_payments

    def fetch_customer(self, customer_id: str) -> Dict[str, Any]:
        """
        Busca dados do cliente pelo ID (com cache para evitar requests duplicados).

        Args:
            customer_id: ID do cliente no Asaas

        Returns:
            Dicionário com dados do cliente
        """
        if customer_id in self._customer_cache:
            return self._customer_cache[customer_id]

        data = self._get(f'/customers/{customer_id}')
        self._customer_cache[customer_id] = data
        return data

    def fetch_customers_batch(self, customer_ids: List[str]) -> Dict[str, Dict]:
        """
        Busca dados de múltiplos clientes, evitando requests repetidos.

        Args:
            customer_ids: Lista de IDs únicos de clientes

        Returns:
            Dicionário {customer_id: customer_data}
        """
        unique_ids = [cid for cid in set(customer_ids) if cid and cid not in self._customer_cache]
        total = len(unique_ids)

        if total > 0:
            logger.info(f' Buscando dados de {total} clientes únicos...')
            for i, customer_id in enumerate(unique_ids, 1):
                self.fetch_customer(customer_id)
                if i % 50 == 0:
                    logger.debug(f'   {i}/{total} clientes carregados')
                time.sleep(0.1)

        return self._customer_cache

    def map_payment_to_row(
        self,
        payment: Dict[str, Any],
        customer: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Mapeia pagamento + cliente para as colunas padronizadas do sistema.

        Args:
            payment: Objeto de pagamento da API
            customer: Objeto de cliente da API

        Returns:
            Dicionário com colunas: email, nome, telefone, sale_value, sale_date, utm_campaign, origem
        """
        # Email
        email_raw = customer.get('email') or ''
        email = normalizar_email(email_raw) if email_raw else None

        # Telefone: prefere mobilePhone, fallback para phone
        phone_raw = customer.get('mobilePhone') or customer.get('phone') or ''
        telefone = normalizar_telefone_robusto(phone_raw) if phone_raw else None

        # Nome
        nome = customer.get('name') or ''

        # Valor
        sale_value = float(payment.get('value') or 0)

        # Data: clientPaymentDate (data que o cliente pagou)
        date_str = payment.get('clientPaymentDate') or payment.get('paymentDate') or ''
        try:
            sale_date = pd.to_datetime(date_str) if date_str else pd.NaT
        except Exception:
            sale_date = pd.NaT

        return {
            'email': email,
            'nome': nome,
            'telefone': telefone,
            'sale_value': sale_value,
            'sale_date': sale_date,
            'utm_campaign': None,  # Asaas não tem UTM nativo
            'origem': 'asaas',
            # Campos extras para debug (não usados no matching)
            '_asaas_payment_id': payment.get('id'),
            '_asaas_customer_id': payment.get('customer'),
            '_asaas_billing_type': payment.get('billingType'),
            '_asaas_status': payment.get('status'),
        }

    def generate_report(
        self,
        start_date: str,
        end_date: str,
        output_path: str = None,
    ) -> pd.DataFrame:
        """
        Gera DataFrame de vendas Asaas no período.

        Args:
            start_date: Data inicial (YYYY-MM-DD)
            end_date: Data final (YYYY-MM-DD)
            output_path: Se fornecido, salva Excel

        Returns:
            DataFrame padronizado com origem='asaas'
        """
        # 1. Buscar pagamentos
        payments = self.fetch_payments(start_date, end_date)
        if not payments:
            logger.warning(' Nenhum pagamento Asaas encontrado no período.')
            return pd.DataFrame(columns=[
                'email', 'nome', 'telefone', 'sale_value',
                'sale_date', 'utm_campaign', 'origem',
            ])

        # 2. Buscar clientes únicos em batch
        customer_ids = [p.get('customer') for p in payments if p.get('customer')]
        self.fetch_customers_batch(customer_ids)

        # 3. Mapear para linhas
        rows = []
        for payment in payments:
            customer_id = payment.get('customer', '')
            customer = self._customer_cache.get(customer_id, {})
            row = self.map_payment_to_row(payment, customer)
            rows.append(row)

        df = pd.DataFrame(rows)

        # 4. Remover sem email e sem data válida
        before = len(df)
        df = df[df['email'].notna() & df['email'].ne('')]
        df = df[df['sale_date'].notna()]
        removed = before - len(df)
        if removed > 0:
            logger.warning(f' {removed} pagamentos removidos por falta de email ou data.')

        # 5. Ordenar por data
        df = df.sort_values('sale_date').reset_index(drop=True)

        logger.info(f' Asaas: {len(df)} vendas carregadas ({start_date} a {end_date})')

        if output_path:
            df_export = df.drop(columns=[c for c in df.columns if c.startswith('_')])
            df_export.to_excel(output_path, index=False)
            logger.info(f' Salvo em {output_path}')

        return df


def fetch_asaas_sales(
    start_date: str,
    end_date: str,
    api_key: str = None,
    save_excel: bool = False,
    output_path: str = None,
) -> pd.DataFrame:
    """
    Função auxiliar para buscar vendas Asaas — interface equivalente a fetch_guru_sales_from_api().

    Args:
        start_date: Data inicial (YYYY-MM-DD)
        end_date: Data final (YYYY-MM-DD)
        api_key: Chave da API (usa ASAAS_API_KEY do .env se não fornecida)
        save_excel: Se True, salva Excel
        output_path: Caminho do Excel (obrigatório se save_excel=True)

    Returns:
        DataFrame com vendas Asaas
    """
    extractor = AsaasSalesExtractor(api_key=api_key)
    return extractor.generate_report(
        start_date=start_date,
        end_date=end_date,
        output_path=output_path if save_excel else None,
    )


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    df = fetch_asaas_sales(
        start_date='2026-03-01',
        end_date='2026-03-18',
        save_excel=True,
        output_path='V2/files/validation/vendas/Asaas-Vendas-marco-2026.xlsx',
    )
    print(f'\nTotal: {len(df)} vendas')
    if len(df) > 0:
        print(df[['email', 'nome', 'sale_value', 'sale_date', 'origem']].head(10))

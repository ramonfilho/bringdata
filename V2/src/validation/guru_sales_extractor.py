"""
Extrator de vendas da API do Digital Manager Guru

Gera relatório de vendas no mesmo formato do export manual da Guru.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any
import time

from api.guru_config import GURU_CONFIG, GURU_HEADERS


class GuruSalesExtractor:
    """Extrai vendas da API Guru e gera relatório Excel"""

    def __init__(self):
        self.base_url = GURU_CONFIG['transactions_endpoint']
        self.headers = GURU_HEADERS

    def fetch_transactions(
        self,
        start_date: str,
        end_date: str,
        date_type: str = 'ordered'  # 'ordered', 'confirmed', 'cancelled'
    ) -> List[Dict[str, Any]]:
        """
        Busca todas as transações de um período (com paginação).

        Args:
            start_date: Data inicial (YYYY-MM-DD)
            end_date: Data final (YYYY-MM-DD)
            date_type: Tipo de data para filtrar

        Returns:
            Lista de transações
        """
        all_transactions = []
        cursor = None
        page = 1

        # Mapear tipo de data
        date_field_map = {
            'ordered': 'ordered_at',
            'confirmed': 'confirmed_at',
            'cancelled': 'cancelled_at',
        }
        date_field = date_field_map.get(date_type, 'ordered_at')

        params = {
            f'{date_field}_ini': start_date,
            f'{date_field}_end': end_date,
            'per_page': 100,  # Máximo permitido pela API
        }

        print(f'🔍 Buscando transações de {start_date} a {end_date}...')

        while True:
            if cursor:
                params['cursor'] = cursor

            try:
                response = requests.get(
                    self.base_url,
                    headers=self.headers,
                    params=params,
                    timeout=30
                )

                if response.status_code != 200:
                    print(f'❌ Erro na requisição: {response.status_code}')
                    print(response.text[:500])
                    break

                data = response.json()
                transactions = data.get('data', [])
                all_transactions.extend(transactions)

                print(f'   Página {page}: {len(transactions)} transações')

                # Verificar se tem mais páginas
                if not data.get('has_more_pages'):
                    break

                cursor = data.get('next_cursor')
                page += 1

                # Rate limiting (reduzido)
                time.sleep(0.2)

            except Exception as e:
                print(f'❌ Erro ao buscar página {page}: {e}')
                break

        print(f'✅ Total de transações buscadas: {len(all_transactions)}')
        return all_transactions

    def map_transaction_to_row(self, transaction: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mapeia uma transação da API para as colunas do relatório Excel.

        Args:
            transaction: Transação da API

        Returns:
            Dicionário com dados mapeados para as colunas do Excel
        """
        # Contact info
        contact = transaction.get('contact', {})
        lead = contact.get('lead', [{}])[0] if contact.get('lead') else {}

        # Payment info
        payment = transaction.get('payment', {})
        acquirer = payment.get('acquirer', {})
        installments = payment.get('installments', {})
        credit_card = payment.get('credit_card', {})

        # Product info
        product = transaction.get('product', {})
        offer = product.get('offer', {})
        producer = product.get('producer', {})

        # Items (pegar primeiro item)
        items = transaction.get('items', [{}])
        first_item = items[0] if items else {}
        item_offer = first_item.get('offer', {})

        # Dates
        dates = transaction.get('dates', {})

        # Trackings (pode ser lista ou dict)
        trackings = transaction.get('trackings', [])
        if isinstance(trackings, list) and len(trackings) > 0:
            first_tracking = trackings[0]
        elif isinstance(trackings, dict):
            first_tracking = trackings
        else:
            first_tracking = {}

        # Shipment
        shipment = transaction.get('shipment', {})

        # Subscription (pode ser dict ou lista)
        subscription = transaction.get('subscription', {})
        if isinstance(subscription, list):
            subscription = subscription[0] if len(subscription) > 0 else {}

        # Coupon
        coupon = payment.get('coupon', {})

        # Self attribution
        self_attribution = transaction.get('self_attribution', {})

        # Converter timestamps para datetime
        def ts_to_datetime(ts):
            if ts:
                try:
                    return datetime.fromtimestamp(int(ts))
                except:
                    return None
            return None

        row = {
            # Colunas 1-10
            'id transação': transaction.get('id'),
            'nome marketplace': payment.get('marketplace_name'),
            'id marketplace': payment.get('marketplace_id'),
            'status': transaction.get('status'),
            'tipo': transaction.get('type'),
            'pagamento': payment.get('method'),
            'parcelas': installments.get('qty', 1),
            'moeda': payment.get('currency', 'BRL'),
            'valor venda': payment.get('total', 0),
            'valor marketplace': payment.get('marketplace_value', 0),

            # Colunas 11-20
            'valor afiliado': payment.get('affiliate_value', 0),
            'valor frete': shipment.get('value', 0),
            'valor líquido': payment.get('net', 0),
            'valor produtos': payment.get('gross', 0),
            'valor desconto': payment.get('discount_value', 0),
            'valor imposto': payment.get('tax', {}).get('value', 0),
            'valor parcelas': installments.get('value', payment.get('total', 0)),
            'id produto': first_item.get('marketplace_id'),
            'nome produto': first_item.get('name'),
            'quantidade produto': first_item.get('qty', 1),

            # Colunas 21-30
            'retorno marketplace': payment.get('refuse_reason'),
            'motivo reembolso': payment.get('refund_reason'),
            'nome martketplace ultima venda': None,  # Não disponível na API
            'id marketplace ultima venda': None,  # Não disponível na API
            'id contato': contact.get('id'),
            'nome empresa contato': contact.get('company_name'),
            'nome contato': contact.get('name'),
            'doc contato': contact.get('doc'),
            'email contato': contact.get('email'),
            'logradouro contato': contact.get('address'),

            # Colunas 31-40
            'número contato': contact.get('address_number'),
            'complemento contato': contact.get('address_comp'),
            'bairro contato': contact.get('address_district'),
            'cidade contato': contact.get('address_city'),
            'estado contato': contact.get('address_state'),
            'país contato': contact.get('address_country'),
            'cep contato': contact.get('address_zip_code'),
            'codigo telefone contato': contact.get('phone_local_code'),
            'telefone contato': contact.get('phone_number'),
            'primeira captura': lead.get('first_capture_origin'),

            # Colunas 41-50
            'primeira origem': lead.get('first_origin'),
            'data 1ª captura': ts_to_datetime(lead.get('first_capture_at')),
            'última captura': lead.get('last_capture_origin'),
            'última origem': lead.get('last_origin'),
            'data última captura': ts_to_datetime(lead.get('last_capture_at')),
            'data pedido': ts_to_datetime(dates.get('ordered_at')),
            'data aprovacao': ts_to_datetime(dates.get('confirmed_at')),
            'data cancelamento': ts_to_datetime(dates.get('canceled_at')),
            'data garantia': ts_to_datetime(dates.get('warranty_until')),
            'data indisponível': ts_to_datetime(dates.get('unavailable_until')),

            # Colunas 51-60 (tracking RPPC - Real Person Post Click)
            'rppc venda': first_tracking.get('rppc_sale'),
            'origem rppc venda': first_tracking.get('rppc_sale_origin'),
            'rppc utm campaign': first_tracking.get('rppc_utm_campaign'),
            'rppc utm medium': first_tracking.get('rppc_utm_medium'),
            'rppc utm term': first_tracking.get('rppc_utm_term'),
            'rppc utm content': first_tracking.get('rppc_utm_content'),
            'rppc checkout': first_tracking.get('rppc_checkout'),
            'origem 1': first_tracking.get('origin_1'),
            'origem 2': first_tracking.get('origin_2'),
            'origem 3': first_tracking.get('origin_3'),

            # Colunas 61-70 (UTMs normais)
            'utm_source': first_tracking.get('utm_source'),
            'utm_campaign': first_tracking.get('utm_campaign'),
            'utm_medium': first_tracking.get('utm_medium'),
            'utm_content': first_tracking.get('utm_content'),
            'url do boleto': None,  # Disponível em invoice
            'linha digitável do boleto': None,  # Disponível em invoice
            'vencimento do boleto': None,  # Disponível em invoice
            'nome oferta': offer.get('name') or item_offer.get('name'),
            'url oferta': transaction.get('checkout_url'),
            'nome da transportadora': shipment.get('carrier'),

            # Colunas 71-80
            'serviço da transportadora': shipment.get('service'),
            'código de rastreamento': shipment.get('tracking'),
            'valor da transportadora': shipment.get('value', 0),
            'tempo de entrega': shipment.get('delivery_time'),
            'assinatura código': subscription.get('code'),
            'assinatura ciclo': subscription.get('cycle'),
            'cupom código': coupon.get('code') if isinstance(coupon, dict) else coupon,
            'cupom valor': coupon.get('value', 0) if isinstance(coupon, dict) else 0,
            'adquirente nome': acquirer.get('name'),
            'adquirente tid': acquirer.get('tid'),

            # Colunas 81-82
            'pix': payment.get('pix_code'),
            'resposta auto atribuição': self_attribution.get('response') if self_attribution else None,
        }

        return row

    def generate_report(
        self,
        start_date: str,
        end_date: str,
        output_path: str = None
    ) -> pd.DataFrame:
        """
        Gera relatório de vendas completo.

        Se o período for maior que 180 dias, divide em múltiplas requisições.

        Args:
            start_date: Data inicial (YYYY-MM-DD)
            end_date: Data final (YYYY-MM-DD)
            output_path: Caminho para salvar Excel (opcional)

        Returns:
            DataFrame com relatório
        """
        from datetime import datetime, timedelta

        # Converter datas
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        total_days = (end - start).days

        # Se período <= 180 dias, buscar diretamente
        if total_days <= 180:
            transactions = self.fetch_transactions(start_date, end_date)
        else:
            # Dividir em chunks de 180 dias
            print(f'\n⚠️  Período de {total_days} dias excede limite de 180 dias')
            print(f'📦 Dividindo em múltiplas requisições...\n')

            transactions = []
            current_start = start
            chunk_num = 1

            while current_start < end:
                # Calcular fim do chunk (max 180 dias)
                current_end = min(current_start + timedelta(days=180), end)

                chunk_start_str = current_start.strftime('%Y-%m-%d')
                chunk_end_str = current_end.strftime('%Y-%m-%d')

                print(f'📦 Chunk {chunk_num}: {chunk_start_str} a {chunk_end_str}')
                chunk_transactions = self.fetch_transactions(chunk_start_str, chunk_end_str)
                transactions.extend(chunk_transactions)

                # Próximo chunk
                current_start = current_end + timedelta(days=1)
                chunk_num += 1

                # Pequena pausa entre chunks
                if current_start < end:
                    time.sleep(0.5)

            print(f'\n✅ Total de transações de todos os chunks: {len(transactions)}')

        # Mapear para DataFrame
        print(f'\n📊 Mapeando {len(transactions)} transações...')
        rows = [self.map_transaction_to_row(t) for t in transactions]
        df = pd.DataFrame(rows)

        # Mapear status para português (igual ao export manual)
        status_map = {
            'approved': 'Aprovada',
            'canceled': 'Cancelada',
            'expired': 'Expirada',
            'refunded': 'Reembolsada',
            'chargeback': 'Reclamada',
            'waiting_payment': 'Ag. Pagamento',
            'scheduled': 'Agendada',
        }
        df['status'] = df['status'].map(status_map).fillna(df['status'])

        # Ordenar por data pedido (do mais antigo para o mais recente)
        df['_data_pedido_sort'] = pd.to_datetime(df['data pedido'], errors='coerce')
        df = df.sort_values('_data_pedido_sort', ascending=True)
        df = df.drop(columns=['_data_pedido_sort'])
        df = df.reset_index(drop=True)

        # Formatar datas para padrão brasileiro (dd/mm/yyyy HH:MM:SS)
        date_columns = [
            'data pedido', 'data aprovacao', 'data cancelamento',
            'data garantia', 'data indisponível', 'data 1ª captura', 'data última captura'
        ]
        for col in date_columns:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')
                df[col] = df[col].dt.strftime('%d/%m/%Y %H:%M:%S')
                df[col] = df[col].replace('NaT', '')

        # Salvar se caminho fornecido
        if output_path:
            print(f'\n💾 Salvando relatório: {output_path}')
            df.to_excel(output_path, index=False)
            print(f'✅ Relatório salvo com sucesso!')

        return df


if __name__ == '__main__':
    # Gerar relatório dos últimos 7 dias
    extractor = GuruSalesExtractor()

    # Período: últimos 7 dias (2026-01-14 a 2026-01-21)
    df = extractor.generate_report(
        start_date='2026-01-14',
        end_date='2026-01-21',
        output_path='V2/files/validation/vendas/Guru-Vendas-API-ultimos-7-dias.xlsx'
    )

    print(f'\n📊 Relatório gerado com {len(df)} transações')

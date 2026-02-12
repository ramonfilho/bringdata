"""
Calculador de Períodos de Análise

Este módulo contém funções para calcular automaticamente os períodos de
captação, CPL e vendas baseados na lógica de negócio do lançamento.

Lógica de Períodos:
-------------------
SEMANA 1 - CAPTAÇÃO DE LEADS (7 dias):
  - Início: Terça-feira
  - Fim: Segunda-feira (7 dias depois)

SEMANA 2 - ANÁLISE DE CPL (6 dias):
  - Início: Terça-feira (dia seguinte ao fim da captação)
  - Fim: Domingo (6 dias depois)

SEMANA 3 - VENDAS (7 dias):
  - Início: Segunda-feira (abertura do carrinho)
  - Fim: Domingo (fechamento do carrinho - 7 dias depois)

Exemplo:
--------
>>> calc = PeriodCalculator()
>>> periods = calc.calculate_periods('2025-10-28')
>>> print(periods)
{
    'lead_capture': {
        'start': '2025-10-28',  # Terça
        'end': '2025-11-03'      # Segunda (7 dias)
    },
    'cpl_analysis': {
        'start': '2025-11-04',  # Terça
        'end': '2025-11-09'      # Domingo (6 dias)
    },
    'sales': {
        'start': '2025-11-10',  # Segunda
        'end': '2025-11-16'      # Domingo (7 dias)
    }
}
"""

from datetime import datetime, timedelta
from typing import Dict, Tuple


class PeriodCalculator:
    """Calculador de períodos de análise baseado na data de início da captação."""

    # Constantes de duração
    LEAD_CAPTURE_DAYS = 7  # Terça a Segunda (7 dias)
    CPL_ANALYSIS_DAYS = 6   # Terça a Domingo (6 dias)
    SALES_PERIOD_DAYS = 7   # Segunda a Domingo (7 dias)

    # Dias da semana (0=Monday, 1=Tuesday, ..., 6=Sunday)
    TUESDAY = 1
    MONDAY = 0
    SUNDAY = 6

    def __init__(self):
        """Inicializa o calculador de períodos."""
        pass

    def calculate_periods(self, lead_capture_start: str) -> Dict[str, Dict[str, str]]:
        """
        Calcula todos os períodos baseado na data de início da captação.

        A data de início DEVE ser uma terça-feira. Se não for, um warning será
        emitido mas o cálculo continuará.

        Args:
            lead_capture_start: Data de início da captação (formato: YYYY-MM-DD)
                                Deve ser uma terça-feira

        Returns:
            Dicionário com 3 períodos:
            {
                'lead_capture': {'start': 'YYYY-MM-DD', 'end': 'YYYY-MM-DD'},
                'cpl_analysis': {'start': 'YYYY-MM-DD', 'end': 'YYYY-MM-DD'},
                'sales': {'start': 'YYYY-MM-DD', 'end': 'YYYY-MM-DD'}
            }

        Raises:
            ValueError: Se a data não estiver no formato correto
        """
        try:
            start_date = datetime.strptime(lead_capture_start, '%Y-%m-%d')
        except ValueError as e:
            raise ValueError(
                f"Data deve estar no formato YYYY-MM-DD. Recebido: {lead_capture_start}"
            ) from e

        # Validar que é terça-feira (opcional, apenas warning)
        if start_date.weekday() != self.TUESDAY:
            weekday_names = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
            actual_day = weekday_names[start_date.weekday()]
            print(f" AVISO: Data de início ({lead_capture_start}) é {actual_day}, "
                  f"mas deveria ser Terça-feira conforme a lógica de negócio.")

        # Calcular períodos
        periods = {}

        # 1. SEMANA 1 - CAPTAÇÃO DE LEADS (Terça a Segunda - 7 dias)
        lead_start = start_date
        lead_end = lead_start + timedelta(days=self.LEAD_CAPTURE_DAYS - 1)  # -1 porque inclui o dia inicial
        periods['lead_capture'] = {
            'start': lead_start.strftime('%Y-%m-%d'),
            'end': lead_end.strftime('%Y-%m-%d')
        }

        # 2. SEMANA 2 - ANÁLISE DE CPL (Terça a Domingo - 6 dias)
        cpl_start = lead_end + timedelta(days=1)  # Dia seguinte ao fim da captação
        cpl_end = cpl_start + timedelta(days=self.CPL_ANALYSIS_DAYS - 1)
        periods['cpl_analysis'] = {
            'start': cpl_start.strftime('%Y-%m-%d'),
            'end': cpl_end.strftime('%Y-%m-%d')
        }

        # 3. SEMANA 3 - VENDAS (Segunda a Domingo - 7 dias)
        sales_start = cpl_end + timedelta(days=1)  # Dia seguinte ao fim do CPL
        sales_end = sales_start + timedelta(days=self.SALES_PERIOD_DAYS - 1)
        periods['sales'] = {
            'start': sales_start.strftime('%Y-%m-%d'),
            'end': sales_end.strftime('%Y-%m-%d')
        }

        return periods

    def get_sales_period(self, lead_capture_start: str, lead_capture_end: str) -> Tuple[str, str]:
        """
        Retorna apenas o período de vendas baseado no período de captação.

        Esta é uma função simplificada quando você já tem o período de captação
        completo e só precisa calcular o período de vendas.

        Args:
            lead_capture_start: Data de início da captação (YYYY-MM-DD)
            lead_capture_end: Data de fim da captação (YYYY-MM-DD)

        Returns:
            Tupla (sales_start, sales_end) no formato YYYY-MM-DD

        Example:
            >>> calc = PeriodCalculator()
            >>> sales_start, sales_end = calc.get_sales_period('2025-10-28', '2025-11-03')
            >>> print(sales_start, sales_end)
            2025-11-10 2025-11-16
        """
        periods = self.calculate_periods(lead_capture_start)
        return periods['sales']['start'], periods['sales']['end']

    def validate_period_logic(self, lead_start: str, lead_end: str,
                             sales_start: str, sales_end: str) -> Dict[str, bool]:
        """
        Valida se os períodos fornecidos seguem a lógica de negócio esperada.

        Args:
            lead_start: Data de início da captação
            lead_end: Data de fim da captação
            sales_start: Data de início das vendas
            sales_end: Data de fim das vendas

        Returns:
            Dicionário com validações:
            {
                'lead_duration_ok': bool,        # Captação tem 7 dias?
                'sales_duration_ok': bool,       # Vendas tem 7 dias?
                'gap_ok': bool,                  # Gap de 7 dias entre períodos?
                'lead_start_is_tuesday': bool,  # Início é terça?
                'sales_start_is_monday': bool   # Vendas começa segunda?
            }
        """
        lead_s = datetime.strptime(lead_start, '%Y-%m-%d')
        lead_e = datetime.strptime(lead_end, '%Y-%m-%d')
        sales_s = datetime.strptime(sales_start, '%Y-%m-%d')
        sales_e = datetime.strptime(sales_end, '%Y-%m-%d')

        # Durações
        lead_duration = (lead_e - lead_s).days + 1  # +1 porque inclui ambos os dias
        sales_duration = (sales_e - sales_s).days + 1

        # Gap entre fim de captação e início de vendas
        gap = (sales_s - lead_e).days - 1  # -1 porque não conta os dias de fronteira

        return {
            'lead_duration_ok': lead_duration == self.LEAD_CAPTURE_DAYS,
            'sales_duration_ok': sales_duration == self.SALES_PERIOD_DAYS,
            'gap_ok': gap == self.CPL_ANALYSIS_DAYS,
            'lead_start_is_tuesday': lead_s.weekday() == self.TUESDAY,
            'sales_start_is_monday': sales_s.weekday() == self.MONDAY,
            'all_valid': (
                lead_duration == self.LEAD_CAPTURE_DAYS and
                sales_duration == self.SALES_PERIOD_DAYS and
                gap == self.CPL_ANALYSIS_DAYS and
                lead_s.weekday() == self.TUESDAY and
                sales_s.weekday() == self.MONDAY
            )
        }


def calculate_periods_from_start(lead_capture_start: str) -> Dict[str, Dict[str, str]]:
    """
    Função de conveniência para calcular períodos.

    Args:
        lead_capture_start: Data de início da captação (YYYY-MM-DD)

    Returns:
        Dicionário com os 3 períodos calculados
    """
    calc = PeriodCalculator()
    return calc.calculate_periods(lead_capture_start)


if __name__ == '__main__':
    # Teste com o exemplo do problema
    print("TESTE: Calculador de Períodos")
    print()

    calc = PeriodCalculator()

    # Exemplo do período problemático
    lead_start = '2025-10-28'
    print(f" Data de início da captação: {lead_start}")
    print()

    periods = calc.calculate_periods(lead_start)

    print("PERÍODOS CALCULADOS:")
    print("-" * 80)
    print(f" CAPTAÇÃO DE LEADS:")
    print(f"   Início: {periods['lead_capture']['start']} (Terça)")
    print(f"   Fim:    {periods['lead_capture']['end']} (Segunda)")
    print(f"   Duração: 7 dias")
    print()

    print(f" ANÁLISE DE CPL:")
    print(f"   Início: {periods['cpl_analysis']['start']} (Terça)")
    print(f"   Fim:    {periods['cpl_analysis']['end']} (Domingo)")
    print(f"   Duração: 6 dias")
    print()

    print(f" PERÍODO DE VENDAS:")
    print(f"   Início: {periods['sales']['start']} (Segunda)")
    print(f"   Fim:    {periods['sales']['end']} (Domingo)")
    print(f"   Duração: 7 dias")
    print()

    # Validação
    print("VALIDAÇÃO:")
    print("-" * 80)
    validation = calc.validate_period_logic(
        periods['lead_capture']['start'],
        periods['lead_capture']['end'],
        periods['sales']['start'],
        periods['sales']['end']
    )

    for key, value in validation.items():
        status = "" if value else ""
        print(f"{status} {key}: {value}")
    print()

    if validation['all_valid']:
        print(" Todos os períodos estão corretos!")
    else:
        print(" Alguns períodos não seguem a lógica esperada")

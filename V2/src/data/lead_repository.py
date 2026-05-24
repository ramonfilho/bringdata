"""Interface do bibliotecário de leads + função de composição.

`LeadRepository` é a interface que cada adaptador implementa. Consumidores
recebem um `LeadRepository` (injeção de dependência) e chamam seus métodos
sem saber qual adaptador está por trás.

Adicionar método na interface é decisão consciente: só quando 2+ consumidores
precisam da mesma coisa. Atalho específico de um consumidor deve viver no
consumidor, agregando em cima do raw que a interface já oferece.
"""
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from .lead_record import LeadRecord


# Limites operacionais — proteção contra uso abusivo (ex.: "me dá 10 anos de leads").
WINDOW_MAX_DAYS = 90
DEFAULT_LIMIT = 10_000


@runtime_checkable
class LeadRepository(Protocol):
    """Devolve leads no formato interno (`LeadRecord`), escondendo a fonte."""

    def recent_leads(
        self, window_minutes: int, limit: int = DEFAULT_LIMIT,
    ) -> list[LeadRecord]:
        """Leads dos últimos N minutos. Janela máxima: 90 dias."""
        ...

    def leads_in_range(
        self, start: datetime, end: datetime, limit: int = DEFAULT_LIMIT,
    ) -> list[LeadRecord]:
        """Leads no intervalo [start, end). Range máximo: 90 dias."""
        ...


def _validate_window(window_minutes: int) -> None:
    if window_minutes <= 0:
        raise ValueError(
            f"window_minutes deve ser positivo, recebi {window_minutes}"
        )
    if window_minutes > WINDOW_MAX_DAYS * 24 * 60:
        raise ValueError(
            f"window_minutes={window_minutes} excede limite de "
            f"{WINDOW_MAX_DAYS} dias ({WINDOW_MAX_DAYS * 24 * 60} min)"
        )


def _validate_range(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValueError(f"end ({end}) deve ser maior que start ({start})")
    delta = end - start
    if delta > timedelta(days=WINDOW_MAX_DAYS):
        raise ValueError(
            f"range de {delta} excede limite de {WINDOW_MAX_DAYS} dias"
        )


def compose_repository(source: str = 'registros_ml', **conn_kwargs) -> LeadRepository:
    """Monta o adaptador certo pra contexto.

    Chamado pelos pontos de entrada (endpoints, schedulers, scripts). Consumidor
    não chama — recebe o repositório pronto.

    Args:
        source: identificador da fonte. Valores aceitos:
            - 'registros_ml' (default): ledger novo populado pelo consumer
              Pub/Sub desde 2026-05-23. Fonte canônica do monitoramento
              corrente.
            - 'legacy': tabela `Lead` antiga (parou de receber leads em
              17/05/2026, mas histórico ainda serve pro baseline rolling 30d
              da regra de desvio de score). Some quando o ledger novo
              acumular 30 dias (≈22/06/2026).
        conn_kwargs: kwargs específicos do adaptador (ex.:
                     `railway_conn=conn_pg8000`).

    Raises:
        ValueError: se a fonte não for reconhecida.
    """
    if source == 'registros_ml':
        from .adapters.registros_ml import RegistrosMLAdapter
        return RegistrosMLAdapter(**conn_kwargs)
    if source == 'legacy':
        from .adapters.legacy import LegacyAdapter
        return LegacyAdapter(**conn_kwargs)
    raise ValueError(
        f"fonte desconhecida: {source!r}. Valores aceitos: 'registros_ml', 'legacy'."
    )

"""
Leitura do custo de infraestrutura do Google Cloud, dia a dia.

Este é o ÚNICO lugar do projeto que sabe o nome da tabela de faturamento e o SQL
que a lê. Quem consome (hoje só o alerta de custo em `cost_alert.py`) recebe um
objeto `CustoDiario` já pronto e não faz ideia de que existe BigQuery no meio -
se um dia a fonte virar a API de Billing ou o export padrão, muda só aqui.

Fonte: `billing_export.gcp_billing_export_resource_v1_*` - o export DETALHADO da
conta de faturamento, que traz o campo `resource.name`. É esse campo que permite
dizer QUAL serviço do Cloud Run gastou (`smart-ads-api`, `smart-ads-monitoring`,
cada job de ingestão…). O export padrão (`gcp_billing_export_v1_*`) daria só o
total do Cloud Run, sem culpado.

Dois números, sempre os dois:
  - BRUTO    = o uso antes da camada gratuita. É o que dispara primeiro quando
               algo sai do controle (um loop, um cron travado segurando CPU).
  - LÍQUIDO  = o que de fato vai ser cobrado, já descontados os créditos da
               camada gratuita. Na prática fica em zero na maior parte dos dias.

A diferença é grande e enganosa: em agosto de 2026 o Cloud Run acumulou R$ 33,12
de uso bruto e apenas R$ 4,74 de cobrança real. Vigiar só o líquido esconde uma
disparada enquanto a camada gratuita ainda está absorvendo; vigiar o bruto avisa
com dias de antecedência.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

BRT = timezone(timedelta(hours=-3))

# Coordenadas do export de faturamento. Ficam em variável de ambiente pra não
# precisar de deploy se a conta de faturamento mudar de ID.
BILLING_PROJECT = os.getenv('BILLING_EXPORT_PROJECT', 'smart-ads-451319')
BILLING_DATASET = os.getenv('BILLING_EXPORT_DATASET', 'billing_export')
BILLING_TABLE = os.getenv(
    'BILLING_EXPORT_TABLE',
    'gcp_billing_export_resource_v1_01A389_7A22A8_CE679F',
)

# Serviço vigiado por default. O nome é o mesmo que aparece no relatório de
# faturamento do console ("Cloud Run", "Cloud SQL", "BigQuery"…).
SERVICO_DEFAULT = 'Cloud Run'


@dataclass
class CustoDiario:
    """Custo de UM serviço do Google Cloud em UM dia (calendário BRT)."""
    dia: date
    servico: str
    bruto: float                                   # uso, antes da camada gratuita
    liquido: float                                 # o que será cobrado de fato
    moeda: str = 'BRL'
    # (nome do recurso, custo bruto) - do mais caro pro mais barato. Nome é o do
    # serviço/job no Cloud Run: 'smart-ads-api', 'ingestion-sales-daily'…
    por_recurso: List[Tuple[str, float]] = field(default_factory=list)
    linhas: int = 0                                # nº de linhas lidas no export
    export_time: Optional[datetime] = None         # última atualização do export

    @property
    def tem_dados(self) -> bool:
        """False quando o export não tem NENHUMA linha do dia pedido.

        Distinguir "custou zero" de "não consegui medir" é o ponto: um export
        quebrado devolveria zero e o alerta ficaria calado justamente quando
        parou de enxergar a conta.
        """
        return self.linhas > 0

    def as_dict(self) -> dict:
        return {
            'dia': self.dia.isoformat(),
            'servico': self.servico,
            'bruto': round(self.bruto, 2),
            'liquido': round(self.liquido, 2),
            'moeda': self.moeda,
            'por_recurso': [{'recurso': r, 'bruto': round(v, 2)}
                            for r, v in self.por_recurso],
            'linhas': self.linhas,
            'export_time': self.export_time.isoformat() if self.export_time else None,
        }


_SQL = """
SELECT
  IFNULL(resource.name, '(sem recurso)')                                   AS recurso,
  SUM(cost)                                                                AS bruto,
  SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS liquido,
  ANY_VALUE(currency)                                                      AS moeda,
  MAX(export_time)                                                         AS export_time,
  COUNT(*)                                                                 AS linhas
FROM `{tabela}`
WHERE _PARTITIONTIME >= @particao_desde
  AND usage_start_time >= @inicio
  AND usage_start_time <  @fim
  AND service.description = @servico
GROUP BY recurso
ORDER BY bruto DESC
"""


def janela_do_dia_brt(dia: date) -> Tuple[datetime, datetime]:
    """Converte um dia do calendário BRT no par de instantes UTC que o delimita.

    O faturamento do Google carimba tudo em UTC; todos os relatórios do projeto
    falam em BRT. Traduzir aqui evita que o alerta chame de "ontem" um pedaço de
    dois dias diferentes.
    """
    inicio = datetime(dia.year, dia.month, dia.day, tzinfo=BRT)
    return inicio.astimezone(timezone.utc), (inicio + timedelta(days=1)).astimezone(timezone.utc)


def ler_custo_diario(dia: date, servico: str = SERVICO_DEFAULT,
                     client=None) -> CustoDiario:
    """
    Lê no export de faturamento quanto `servico` custou no dia `dia` (BRT).

    `client`: cliente BigQuery já construído. Existe pra teste poder injetar um
    dublê; em produção fica None e o cliente é criado aqui.

    Nunca levanta por "não achei nada": dia sem linhas volta com `tem_dados`
    False e zeros, e quem chama decide se isso é silêncio normal ou export
    quebrado.
    """
    from google.cloud import bigquery

    client = client or bigquery.Client(project=BILLING_PROJECT)
    tabela = f'{BILLING_PROJECT}.{BILLING_DATASET}.{BILLING_TABLE}'
    inicio, fim = janela_do_dia_brt(dia)

    # Poda de partição: a tabela é particionada pela hora em que a LINHA chegou,
    # não pelo dia de uso. Uso do dia D pode ser gravado de D em diante, então o
    # piso é D-1 (margem) e não há teto - linha atrasada ainda entra na conta.
    particao_desde = datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc) - timedelta(days=1)

    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter('particao_desde', 'TIMESTAMP', particao_desde),
        bigquery.ScalarQueryParameter('inicio', 'TIMESTAMP', inicio),
        bigquery.ScalarQueryParameter('fim', 'TIMESTAMP', fim),
        bigquery.ScalarQueryParameter('servico', 'STRING', servico),
    ])
    linhas = list(client.query(_SQL.format(tabela=tabela), job_config=job_config).result())

    bruto = sum(float(r['bruto'] or 0) for r in linhas)
    liquido = sum(float(r['liquido'] or 0) for r in linhas)
    total_linhas = sum(int(r['linhas'] or 0) for r in linhas)
    moeda = next((r['moeda'] for r in linhas if r['moeda']), 'BRL')
    exports = [r['export_time'] for r in linhas if r['export_time']]

    # Recursos que custaram zero (um job que rodou 2s dentro da cota) só poluem
    # a mensagem - o que interessa é quem puxou a conta pra cima.
    por_recurso = [(str(r['recurso']), float(r['bruto'] or 0))
                   for r in linhas if float(r['bruto'] or 0) > 0]

    custo = CustoDiario(
        dia=dia, servico=servico, bruto=bruto, liquido=liquido, moeda=moeda,
        por_recurso=por_recurso, linhas=total_linhas,
        export_time=max(exports) if exports else None,
    )
    logger.info(
        f"[gcp_cost] {servico} em {dia.isoformat()} (BRT): bruto={bruto:.2f} "
        f"liquido={liquido:.2f} {moeda} - {total_linhas} linhas, "
        f"{len(por_recurso)} recursos com custo"
    )
    return custo

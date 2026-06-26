"""Cliente de LEITURA da Google Ads API — o "funil Google" (espelho de
`meta_api_client.py`).

Papel: puxar custo/cliques/conversões por campanha pra superfície do
monitoramento (digest das 06:00), análogo ao que `MetaAPIClient` faz pro
Meta. **Read-only** — só `SELECT` (GAQL via `GoogleAdsService.search_stream`).

NÃO confundir com `api/google_ads_integration.py`: aquele ENVIA conversão
pela **Data Manager API** (service account, sem developer token); este LÊ
relatório pela **Google Ads API** (developer token + OAuth do usuário +
`login_customer_id` do MCC). APIs e credenciais diferentes.

Anti-corrupção na borda: o vocabulário físico do Google (`cost_micros`,
`conversion_action_name`) é traduzido pro nosso aqui dentro — quem consome
recebe `spend` em BRL e nomes de ação já agregados, sem o jargão da API
vazar pro digest.

Multi-cliente: `customer_id` e `login_customer_id` vêm da config do cliente
(`GoogleAdsConfig` no yaml). As credenciais (developer token / OAuth) são
globais (uma conta MCC BringData) e moram no `.env`.

Injeção pra teste: `__init__` aceita `ga_service` pronto; se None, constrói
do `.env`. Os testes injetam um fake e validam o parsing/agregação sem rede.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# Conversão de micros → unidade monetária (a Google reporta custo/valor em
# milionésimos da moeda da conta).
_MICROS = 1_000_000


def _build_ga_service_from_env():
    """Constrói o `GoogleAdsService` a partir das credenciais do `.env`.

    Mesmas env vars das probes/criação de conversion action. Falha alto e
    claro se faltar credencial (não retorna cliente meia-boca).
    """
    from google.ads.googleads.client import GoogleAdsClient

    required = (
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    )
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            "[google_ads_api_client] credenciais ausentes no ambiente: "
            f"{', '.join(missing)}. Ver V2/docs/google_ads_pendencias.md "
            "seção 'Leitura de campanhas e dados'. Se for refresh token "
            "expirado (invalid_grant), rodar scripts/google_ads_oauth_refresh_token.py."
        )
    cfg = {
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "login_customer_id": os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"].replace("-", ""),
        "use_proto_plus": True,
    }
    client = GoogleAdsClient.load_from_dict(cfg)
    return client.get_service("GoogleAdsService")


class GoogleAdsReportingClient:
    """Leitura de relatório de campanhas de UMA conta Google Ads.

    Args:
        customer_id: conta do cliente (só dígitos), ex. DevClub `6266441811`.
        ga_service: `GoogleAdsService` já construído. Injetado em teste; se
            None, constrói do `.env` no primeiro uso.
    """

    def __init__(self, customer_id: str, ga_service=None):
        self.customer_id = str(customer_id).replace("-", "")
        self._ga_service = ga_service

    @property
    def ga(self):
        if self._ga_service is None:
            self._ga_service = _build_ga_service_from_env()
        return self._ga_service

    def _stream(self, query: str):
        for batch in self.ga.search_stream(customer_id=self.customer_id, query=query):
            for row in batch.results:
                yield row

    def get_campaign_metrics(
        self,
        date_start: str,
        date_end: str,
        statuses: Optional[tuple] = ("ENABLED",),
    ) -> List[Dict]:
        """Custo + cliques + conversões por campanha, agregado na janela.

        Uma linha por campanha (somada no intervalo `[date_start, date_end]`,
        ambos inclusivos, formato 'YYYY-MM-DD'). Anti-corrupção: `cost_micros`
        vira `spend` em BRL aqui.

        Args:
            statuses: filtra por `campaign.status` (default só ENABLED — as
                que rodam). None = todas.

        Returns:
            list de dict: `{campaign_id, campaign_name, status, spend, clicks,
            conversions, all_conversions}`. `spend` em BRL (float).
        """
        where = [f"segments.date BETWEEN '{date_start}' AND '{date_end}'"]
        if statuses:
            joined = ", ".join(f"'{s}'" for s in statuses)
            where.append(f"campaign.status IN ({joined})")
        query = (
            "SELECT campaign.id, campaign.name, campaign.status, "
            "metrics.cost_micros, metrics.clicks, metrics.conversions, "
            "metrics.all_conversions FROM campaign WHERE "
            + " AND ".join(where)
        )
        agg: Dict[int, Dict] = {}
        for r in self._stream(query):
            cid = r.campaign.id
            row = agg.setdefault(cid, {
                "campaign_id": str(cid),
                "campaign_name": r.campaign.name,
                "status": r.campaign.status.name,
                "spend": 0.0, "clicks": 0,
                "conversions": 0.0, "all_conversions": 0.0,
            })
            row["spend"] += r.metrics.cost_micros / _MICROS
            row["clicks"] += r.metrics.clicks
            row["conversions"] += r.metrics.conversions
            row["all_conversions"] += r.metrics.all_conversions
        out = list(agg.values())
        for row in out:
            row["spend"] = round(row["spend"], 2)
            row["conversions"] = round(row["conversions"], 2)
            row["all_conversions"] = round(row["all_conversions"], 2)
        return out

    def get_campaign_conversions_by_action(
        self,
        date_start: str,
        date_end: str,
        action_names: Optional[tuple] = None,
    ) -> List[Dict]:
        """Conversões por (campanha × ação de conversão) na janela.

        É como se descobre quais campanhas estão recebendo o nosso evento
        (`LeadQualified` / `LeadQualifiedHighQuality`) e quantas.

        Gotcha respeitado: o recurso `conversion_action` rejeita
        `metrics.conversions`; por isso a contagem sai de `FROM campaign`
        segmentado por `segments.conversion_action_name`.

        Args:
            action_names: se passado, filtra (em Python) só essas ações.

        Returns:
            list de dict: `{campaign_id, campaign_name, conversion_action_name,
            conversions, all_conversions}`.
        """
        query = (
            "SELECT campaign.id, campaign.name, segments.conversion_action_name, "
            "metrics.conversions, metrics.all_conversions FROM campaign WHERE "
            f"segments.date BETWEEN '{date_start}' AND '{date_end}' "
            "AND metrics.all_conversions > 0"
        )
        wanted = set(action_names) if action_names else None
        out: List[Dict] = []
        for r in self._stream(query):
            name = r.segments.conversion_action_name
            if wanted is not None and name not in wanted:
                continue
            out.append({
                "campaign_id": str(r.campaign.id),
                "campaign_name": r.campaign.name,
                "conversion_action_name": name,
                "conversions": round(r.metrics.conversions, 2),
                "all_conversions": round(r.metrics.all_conversions, 2),
            })
        return out

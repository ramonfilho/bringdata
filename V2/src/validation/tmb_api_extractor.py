"""Extrator de vendas da API REST da TMB (Tem Mais no Boleto).

Busca pedidos EFETIVADOS via `GET https://api.tmbeducacao.com.br/api/pedidos` e
devolve no MESMO formato padronizado dos outros extratores (Asaas, Guru), pronto
pro `upsert_sales`. Irmão do `asaas_sales_extractor` — a normalização de email/
telefone é reusada de `src.core.utils` (miolo único); o que muda é a auth (Bearer),
a paginação (envelope pageNumber/totalPages) e o mapeamento.

Por que existe: a TMB é ~64% dos compradores e até agora entrava por xlsx manual
SEM telefone. A API traz telefone em ~100% e o `pedido_id` (id de transação
estável) → dedup limpa por `external_id` no `analytics.sales` e telefone pro
público de alunos da Meta.

⚠️ CLOUDFLARE: a API rejeita User-Agent de script (HTTP 403, "error code: 1010").
Por isso o Session manda UA de navegador. Se mesmo assim vier 1010, falha ALTO
(não retorna 0 em silêncio — senão o ETL "esvazia" a TMB sem ninguém perceber).
"""
from __future__ import annotations

import os
import sys
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# .env (mesmo padrão do asaas_sales_extractor)
_env_file = Path(__file__).parent.parent.parent / ".env"
if _env_file.exists():
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from src.core.utils import normalizar_email, normalizar_telefone_robusto

logger = logging.getLogger(__name__)

TMB_BASE_URL = "https://api.tmbeducacao.com.br"
# UA de navegador — a Cloudflare da TMB bloqueia UA de script (code 1010).
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_PAGE_SIZE = 100  # máximo aceito pela API
_EFETIVADO = "Efetivado"  # status_pedido que conta como venda


class TMBCloudflareBlocked(RuntimeError):
    """A API respondeu com o bloqueio da Cloudflare (1010) — UA/assinatura barrada."""


class TMBSalesExtractor:
    """Extrai pedidos Efetivados da API REST da TMB."""

    def __init__(self, token: str = None):
        self.token = token or os.environ.get("TMB_API_TOKEN")
        if not self.token:
            raise ValueError(
                "TMB_API_TOKEN não encontrada. Defina no .env ou passe token= no construtor. "
                "(Portal do Produtor TMB → Produtos → TMB API.)"
            )
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "User-Agent": _BROWSER_UA,
            "Accept": "application/json",
        })

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """GET /api/pedidos com retry. Falha ALTO no bloqueio Cloudflare (1010)."""
        url = f"{TMB_BASE_URL}/api/pedidos"
        last_exc = None
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=60)
                if r.status_code == 403 and "1010" in (r.text or ""):
                    raise TMBCloudflareBlocked(
                        "TMB API bloqueou por Cloudflare (code 1010) — User-Agent de "
                        "navegador é obrigatório; verificar _BROWSER_UA."
                    )
                r.raise_for_status()
                return r.json()
            except TMBCloudflareBlocked:
                raise  # bloqueio de UA não se resolve com retry — falha alto já
            except Exception as e:  # noqa: BLE001 — borda de rede; retry
                last_exc = e
                logger.warning("[tmb_api] tentativa %d falhou: %s", attempt + 1, str(e)[:120])
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"[tmb_api] falha após 3 tentativas: {last_exc}")

    def fetch_pedidos(self, start_date: str, end_date: str,
                      produto_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Todos os pedidos Efetivados na janela [start_date, end_date] (YYYY-MM-DD),
        de TODOS os produtos do produtor (sem produto_id) ou de um só.
        Pagina pelo envelope {totalPages, data[]} e deduplica por pedido_id."""
        by_pedido: Dict[Any, Dict] = {}
        page = 1
        total_pages = 1
        while page <= total_pages:
            params = {"data_inicio": start_date, "data_final": end_date,
                      "pageNumber": page, "pageSize": _PAGE_SIZE}
            if produto_id is not None:
                params["produto_id"] = produto_id
            body = self._get(params)
            # A API é enveloped ({totalPages, totalRecords, data:[...]}); tolera
            # também uma lista crua por segurança.
            if isinstance(body, list):
                items, total_pages = body, page
            else:
                items = body.get("data") or []
                total_pages = body.get("totalPages") or page
            for it in items:
                if (it.get("status_pedido") or "") != _EFETIVADO:
                    continue
                pid = it.get("pedido_id")
                if pid is not None:
                    by_pedido[pid] = it  # dedup por pedido_id (última página vence, dá no mesmo)
            logger.debug("[tmb_api] página %d/%s: %d itens", page, total_pages, len(items))
            page += 1
            time.sleep(0.15)  # rate-limit preventivo
        pedidos = list(by_pedido.values())
        logger.info("[tmb_api] %d pedidos Efetivados (%s→%s)", len(pedidos), start_date, end_date)
        return pedidos

    @staticmethod
    def map_pedido_to_row(pedido: Dict[str, Any]) -> Dict[str, Any]:
        """Pedido da API → linha no shape dos loaders (df_vendas)."""
        email = normalizar_email(pedido.get("email")) if pedido.get("email") else None
        telefone = normalizar_telefone_robusto(pedido.get("telefone")) if pedido.get("telefone") else None
        # sale_date = data_efetivado, fallback criado_em (mesma regra do xlsx).
        date_str = pedido.get("data_efetivado") or pedido.get("criado_em") or ""
        try:
            sale_date = pd.to_datetime(date_str) if date_str else pd.NaT
        except Exception:
            sale_date = pd.NaT
        try:
            sale_value = float(pedido.get("valor_total") or 0)
        except (TypeError, ValueError):
            sale_value = 0.0
        return {
            "email": email,
            "nome": pedido.get("cliente"),
            "telefone": telefone,
            "sale_value": sale_value,                         # valor_total (bruto do pedido)
            "sale_date": sale_date,
            "origem": "tmb",
            "status": pedido.get("status_pedido"),            # 'Efetivado'
            "external_id": str(pedido.get("pedido_id")) if pedido.get("pedido_id") is not None else None,
            "product_name": pedido.get("lancamento"),
            "utm_campaign": pedido.get("utm_campaign"),
            # informativo (não usado no matching); status financeiro p/ decisão futura de risco
            "_tmb_status_financeiro": pedido.get("status_financeiro"),
            "_tmb_produto_id": pedido.get("produto_id"),
        }

    def generate_report(self, start_date: str, end_date: str,
                        produto_id: Optional[int] = None) -> pd.DataFrame:
        """DataFrame normalizado (origem='tmb') dos pedidos Efetivados da janela."""
        pedidos = self.fetch_pedidos(start_date, end_date, produto_id=produto_id)
        if not pedidos:
            logger.info("[tmb_api] 0 pedidos na janela — DataFrame vazio")
            return pd.DataFrame()
        df = pd.DataFrame([self.map_pedido_to_row(p) for p in pedidos])
        # descarta linhas sem email E sem telefone (não dá pra casar/gravar)
        before = len(df)
        df = df[df["email"].notna() | df["telefone"].notna()].copy()
        if len(df) != before:
            logger.warning("[tmb_api] %d pedidos sem email/telefone descartados", before - len(df))
        return df

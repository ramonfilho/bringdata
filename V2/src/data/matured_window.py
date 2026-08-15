"""Janela madura rotulada de leads na régua única do Challenger (abr_28).

É a base da referência rolante do lado da CONVERSÃO/CALIBRAÇÃO: leads captados há
tempo suficiente (>= `maturation_days`) pra já terem passado pelo ciclo de venda,
com score+decil na régua. Nunca inclui lead fresco — a conversão dele é PREVISTA
pelo calibrador, não medida aqui.

(O perfil de característica do COMPRADOR é outra população, ancorada em data de
COMPRA, não de captação — sai de um builder separado, não desta janela.)

Fonte (fonte única por trecho, sem repetir o caso Sheets morto):
  - `registros_ml` (ledger VIVO, >= cutover 23/05/2026) — fonte sustentável: tem
    score+decil na régua e UTM/telefone nativos. Conforme o ledger aprofunda, a
    janela madura desliza pra dentro dele e a ponte abaixo some sozinha (~out/2026).
  - `scores_historicos` (congelada, < cutover) — PONTE transitória: tem score+decil
    da régua no passado. NÃO guarda UTM/telefone, então a fatia da ponte entra só na
    conversão TOTAL; canal/balde da referência cobre a fatia do LEDGER e melhora
    conforme o ledger aprofunda (recuperar UTM da ponte via analytics.leads teve
    plano ruim >180s — fica pra otimização se a cobertura canal/balde apertar).

Não faz o casamento com vendas aqui (isso é `build_matched_df`, reusado a jusante) —
devolve só os LEADS da janela, no shape canônico, deduplicados por email.

Reversível: read-only, não escreve nada.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from src.data.analytics_connection import open_analytics_connection

logger = logging.getLogger(__name__)

# Cutover do ledger: primeira linha de `registros_ml` (verificado 29/07/2026:
# min(created_at) = 2026-05-23). Abaixo disso a régua vem da `scores_historicos`.
LEDGER_CUTOVER = "2026-05-23"

# Shape canônico devolvido (1 linha por email, dedup preferindo o ledger).
CANONICAL_COLS = [
    "email", "telefone", "data_captura", "score_challenger", "decil_challenger",
    "utm_source", "utm_campaign", "utm_content", "source",
]


def resolve_ruler_run_id(client_id: str = "devclub",
                         config_root: Optional[Path] = None) -> Optional[str]:
    """run_id da régua única (o `active_model` = abr_28). A referência tem que nascer
    na régua ATIVA; se o modelo mudar, muda aqui e a referência se recalcula na régua
    nova (é o que resolve a auto-supressão por run_id do relatório de criativo)."""
    root = config_root or Path(__file__).resolve().parents[2]
    p = root / "configs" / "active_models" / f"{client_id}.yaml"
    try:
        cfg = yaml.safe_load(p.read_text()) or {}
        return (cfg.get("active_model") or {}).get("mlflow_run_id")
    except Exception as e:
        logger.warning("[matured_window] run_id da régua indisponível (%s): %s", p, e)
        return None


#: Dias que um lead tem pra comprar. Fonte ÚNICA da maturação: quem precisar dela
#: importa daqui em vez de repetir o número.
#:
#: 21 dias = o ciclo real de um lançamento DevClub: semana 1 captação (7d), semana 2
#: CPL/nutrição (6d), semana 3 vendas/carrinho (7d). O lead compra no lançamento em
#: que entrou; depois do carrinho fechar, ele só volta a ter oferta no lançamento
#: seguinte, que é outro evento.
#:
#: Era 60 dias até 03/08/2026, e a folga custava caro: o fim da janela recuava 60 dias
#: do hoje, o que jogava a janela inteira para ANTES do ledger (`registros_ml` nasce
#: em 23/05/2026) e derrubava a fatia com UTM para 6,6%. Com isso as taxas por canal e
#: por balde saíam de uma amostra minúscula. A do Champion vinha de 7 vendas em 438
#: leads (1,598%) e puxava o teto de CPL dele para R$20,81, quando o real é ~R$9.
#: Com 21 dias a mesma conta dá 159 vendas em 23.119 leads (0,688%) e teto R$9,29.
DEFAULT_MATURATION_DAYS = 21

#: Piso da maturação. Serve de PISO, não de resposta: quando o calendário sabe o
#: lançamento do lead, quem manda é ele (`maturacao_do_lancamento`). Este número só
#: cobre o lead que caiu fora de qualquer janela de captação.
MATURACAO_MINIMA_DIAS = DEFAULT_MATURATION_DAYS

#: Teto de sanidade. Lançamento com janela declarada acima disto é erro de planilha
#: (data trocada, ano errado), e aceitar calado empurraria a janela madura meses pra
#: trás sem ninguém notar. Medido: o maior real é 40 dias (LF45, captação de 21 dias).
MATURACAO_MAXIMA_DIAS = 75


def _d(v) -> Optional[date]:
    """Aceita date, datetime ou 'YYYY-MM-DD'. None se não der pra ler."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def maturacao_do_lancamento(entry: Optional[dict]) -> int:
    """Quantos dias o lead daquele lançamento tem pra comprar, LIDO DO CALENDÁRIO.

    A conta é `fim das vendas − início da captação`: é o tempo que o lead captado no
    PRIMEIRO dia espera até o carrinho fechar. Quem entrou depois espera menos, então
    esta é a cota que cobre todo mundo do lançamento.

    POR QUE ISTO EXISTE, e não um número fixo. O 21 fixo assumia o formato padrão
    (captação de 7 dias, nutrição de 6, vendas de 7 = 20 dias). Medido no calendário
    canônico: 6 dos 28 lançamentos passam disso, e são justamente os grandes — o LF45
    captou por 21 dias e precisa de 33. Nele a janela fixa descartava 55,6% dos
    compradores DO PRÓPRIO LANÇAMENTO, porque o carrinho fechava depois do corte.

    Args:
        entry: dict do lançamento no shape de `core.launches.load_launches()`
            (cap_start / vendas_end). None ou incompleto devolve o piso.

    Returns:
        Dias de maturação, entre `MATURACAO_MINIMA_DIAS` e `MATURACAO_MAXIMA_DIAS`.
    """
    cs = _d((entry or {}).get("cap_start"))
    ve = _d((entry or {}).get("vendas_end"))
    if not (cs and ve):
        return MATURACAO_MINIMA_DIAS
    dias = (ve - cs).days
    if dias > MATURACAO_MAXIMA_DIAS:
        logger.warning("[maturação] lançamento com janela de %d dias (cap_start=%s, "
                       "vendas_end=%s) acima do teto de %d — provável data errada na "
                       "planilha; usando o teto", dias, cs, ve, MATURACAO_MAXIMA_DIAS)
        return MATURACAO_MAXIMA_DIAS
    return max(dias, MATURACAO_MINIMA_DIAS)


def maturacao_por_lancamento(launches: Optional[dict] = None) -> dict:
    """`{lf_name: dias de maturação}` para todo o calendário.

    O calendário é injetado (padrão do projeto). Sem ele, lê a fonte corrente —
    que em produção é `analytics.launch_calendar`, alimentada do PC FORMULÁRIOS.
    """
    if launches is None:
        from src.core.launches import load_launches
        launches = load_launches()
    return {nome: maturacao_do_lancamento(e) for nome, e in (launches or {}).items()}


def lead_esta_maduro(*, lf_name: Optional[str], data_captura, as_of: Optional[date] = None,
                     launches: Optional[dict] = None) -> bool:
    """O lead já teve chance COMPLETA de comprar?

    Maturidade deixou de ser "passaram N dias" e virou **"o carrinho do MEU lançamento
    já fechou"**. É a mesma pergunta que o número fixo tentava responder, agora lida do
    calendário em vez de suposta a partir do formato padrão.

    Sem `lf_name` (lead fora de qualquer janela de captação, ~2% da base), cai no piso
    de dias — não dá pra saber o carrinho de quem não entrou em lançamento nenhum.
    """
    dia = _d(data_captura)
    if dia is None:
        return False
    hoje = as_of or date.today()
    if launches is None:
        from src.core.launches import load_launches
        launches = load_launches()
    entry = (launches or {}).get(lf_name) if lf_name else None
    ve = _d((entry or {}).get("vendas_end"))
    if ve is not None:
        return ve < hoje
    return (hoje - dia).days >= MATURACAO_MINIMA_DIAS


def compra_conta_para_o_lead(*, data_captura, data_compra, lf_name: Optional[str] = None,
                             launches: Optional[dict] = None) -> bool:
    """A compra pertence ao lançamento em que o lead entrou?

    Conta se caiu entre a captação e o fim das vendas DAQUELE lançamento. Depois disso
    o lead só volta a receber oferta no lançamento seguinte, que é outro evento com
    outra promessa — creditar aquela venda ao criativo que o captou meses antes seria
    dar crédito pelo trabalho de outro.

    Sem lançamento conhecido, cai no piso de dias a partir da captação.
    """
    dia, compra = _d(data_captura), _d(data_compra)
    if dia is None or compra is None or compra < dia:
        return False
    if launches is None and lf_name:
        from src.core.launches import load_launches
        launches = load_launches()
    entry = (launches or {}).get(lf_name) if lf_name else None
    ve = _d((entry or {}).get("vendas_end"))
    limite = ve if ve is not None else dia + timedelta(days=MATURACAO_MINIMA_DIAS)
    return compra <= limite


def limites_de_compra(datas_captura: pd.Series,
                      launches: Optional[dict] = None) -> pd.DataFrame:
    """Para cada captação, o LANÇAMENTO em que ela caiu e a DATA-LIMITE de compra.

    Mesma regra de `compra_conta_para_o_lead`, vetorizada pra janela madura (que não
    carrega `lf` — o lançamento sai da DATA: captação dentro de [cap_start, cap_end]
    de um lançamento → limite = `vendas_end` dele). Fora de qualquer lançamento, o
    limite cai no piso: captação + `MATURACAO_MINIMA_DIAS`.

    O teto de sanidade (`MATURACAO_MAXIMA_DIAS`) NÃO é reaplicado aqui: quem chama
    casa as vendas com `window_days=MATURACAO_MAXIMA_DIAS`, então compra além do teto
    já não casa — reimpor aqui seria a mesma regra em dois lugares.

    Returns:
        DataFrame alinhado ao índice de `datas_captura`, colunas `lf` (str ou None)
        e `limite` (date ou None — None só quando a captação não tem data legível).
    """
    if launches is None:
        from src.core.launches import load_launches
        launches = load_launches()

    # Mapa dia→(lf, vendas_end). Calendários são pequenos (dezenas de lançamentos ×
    # ~7 dias de captação); em colisão de datas vence o lançamento que começou depois
    # (é o que está ativo naquele dia), com aviso — colisão é erro de planilha.
    dia_map: dict = {}
    for nome, e in (launches or {}).items():
        cs, ce, ve = _d((e or {}).get("cap_start")), _d((e or {}).get("cap_end")), _d((e or {}).get("vendas_end"))
        if cs is None or ve is None:
            continue
        ce = ce or ve
        d = cs
        while d <= ce:
            prev = dia_map.get(d)
            if prev is not None and prev[2] > cs:
                d += timedelta(days=1)
                continue
            if prev is not None and prev[2] != cs:
                logger.warning("[matured_window] captação de %s e %s colidem em %s; "
                               "fica o mais recente", prev[0], nome, d)
            dia_map[d] = (nome, ve, cs)
            d += timedelta(days=1)

    dias = pd.to_datetime(datas_captura, errors="coerce")
    try:
        dias = dias.dt.tz_localize(None)
    except TypeError:
        pass  # já era naive

    lfs, limites = [], []
    for ts in dias:
        d0 = None if pd.isna(ts) else ts.date()
        hit = dia_map.get(d0) if d0 else None
        if hit:
            lfs.append(hit[0])
            limites.append(hit[1])
        else:
            lfs.append(None)
            limites.append(d0 + timedelta(days=MATURACAO_MINIMA_DIAS) if d0 else None)
    return pd.DataFrame({"lf": lfs, "limite": limites}, index=datas_captura.index)


def matured_bounds(*, window_days: int = 90,
                   maturation_days: int = DEFAULT_MATURATION_DAYS,
                   as_of: Optional[date] = None) -> tuple[datetime, datetime]:
    """Fronteiras da janela madura em captação: [as_of - maturation - window,
    as_of - maturation). O fim recua `maturation_days` do hoje pra garantir que todo
    lead da janela já teve chance de comprar."""
    as_of = as_of or date.today()
    win_end = datetime(as_of.year, as_of.month, as_of.day) - timedelta(days=maturation_days)
    win_start = win_end - timedelta(days=window_days)
    return win_start, win_end


def build_matured_window(
    *,
    window_days: int = 90,
    maturation_days: int = DEFAULT_MATURATION_DAYS,
    as_of: Optional[date] = None,
    client_id: str = "devclub",
    ruler_run_id: Optional[str] = None,
    conn=None,
    allow_empty: bool = False,
) -> pd.DataFrame:
    """Leads da janela madura na régua do Challenger, costurando ledger + ponte.

    Args:
        window_days: largura da janela de captação (default 90d).
        maturation_days: quanto o fim recua do hoje pra garantir maturação
            (default DEFAULT_MATURATION_DAYS = 21d, o ciclo do lançamento).
        as_of: "hoje" (default date.today()); injetável pra teste/backfill.
        ruler_run_id: run_id da régua; None → resolve o `active_model` (abr_28).
        conn: conexão Cloud SQL injetada; None → abre e fecha (timeout 180s).
        allow_empty: se False (default), janela vazia FALHA ALTO (uma janela madura de
            90d nunca deve vir vazia em produção — vazio = fonte quebrada).

    Returns:
        DataFrame com `CANONICAL_COLS`, 1 linha por email (dedup preferindo o ledger).
    """
    run_id = ruler_run_id or resolve_ruler_run_id(client_id)
    if not run_id:
        raise ValueError("[matured_window] sem run_id da régua — não dá pra isolar a régua única.")

    win_start, win_end = matured_bounds(window_days=window_days,
                                        maturation_days=maturation_days, as_of=as_of)
    params = {
        "run_id": run_id,
        "cut": LEDGER_CUTOVER,
        "ws": win_start.strftime("%Y-%m-%d %H:%M:%S"),
        "we": win_end.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # DUAS queries simples (plano previsível) em vez de uma costura pesada. Colunas na
    # ordem exata de CANONICAL_COLS nas duas — o concat depois é direto.
    # A régua se busca pelo run_id NAS DUAS duplas de colunas. O ledger grava a nota
    # de cada modelo na dupla do PAPEL que ele tinha no dia (champion/challenger), e
    # os papéis trocam: o abr_28 era challenger até 25/07 e virou champion depois.
    # Ler só a dupla de challenger fazia a janela perder os leads pós-troca conforme
    # ela desliza (medido 15/08: 22.100 leads do abr_28 nas colunas de champion vs
    # 1.213 nas de challenger desde 26/07). Mesmo padrão do casamento por run_id que
    # já corrigiu o painel de decis.
    ledger_sql = (
        "SELECT lower(email) AS email, phone AS telefone, created_at AS data_captura, "
        "       CASE WHEN challenger_run_id = :run_id "
        "                 AND decil_challenger IS NOT NULL AND score_challenger IS NOT NULL "
        "            THEN score_challenger ELSE score_champion END AS score_challenger, "
        "       CASE WHEN challenger_run_id = :run_id "
        "                 AND decil_challenger IS NOT NULL AND score_challenger IS NOT NULL "
        "            THEN decil_challenger ELSE decil_champion END AS decil_challenger, "
        "       utm_source, utm_campaign, utm_content, 'ledger' AS source "
        "FROM public.registros_ml "
        "WHERE created_at >= :cut AND created_at >= :ws AND created_at < :we "
        "  AND ((challenger_run_id = :run_id "
        "        AND decil_challenger IS NOT NULL AND score_challenger IS NOT NULL) "
        "    OR (champion_run_id = :run_id "
        "        AND decil_champion IS NOT NULL AND score_champion IS NOT NULL)) "
        "  AND email IS NOT NULL AND email <> ''"
    )
    bridge_sql = (
        "SELECT lower(email) AS email, NULL AS telefone, data_captura, "
        "       score_challenger, (substring(decil_challenger from 2))::int AS decil_challenger, "
        "       NULL AS utm_source, NULL AS utm_campaign, NULL AS utm_content, 'bridge' AS source "
        "FROM public.scores_historicos "
        "WHERE data_captura >= :ws AND data_captura < :cut "
        "  AND challenger_run_id = :run_id "
        "  AND decil_challenger ~ '^D[0-9]+$' AND score_challenger IS NOT NULL "
        "  AND email IS NOT NULL AND email <> ''"
    )

    own = conn is None
    conn = conn or open_analytics_connection(timeout=180)
    try:
        led_rows = conn.run(ledger_sql, **params)
        brg_rows = conn.run(bridge_sql, **params)
    finally:
        if own:
            conn.close()

    df = pd.concat(
        [pd.DataFrame(led_rows, columns=CANONICAL_COLS),
         pd.DataFrame(brg_rows, columns=CANONICAL_COLS)],
        ignore_index=True,
    )
    n_led_raw = len(led_rows)
    n_brg_raw = len(brg_rows)

    if not df.empty:
        # tz-naive UTC: o matcher (build_matched_df) compara data_captura × sale_date
        # direto e exige o mesmo tz.
        df["data_captura"] = pd.to_datetime(df["data_captura"], utc=True, errors="coerce").dt.tz_localize(None)
        df["score_challenger"] = pd.to_numeric(df["score_challenger"], errors="coerce")
        df["decil_challenger"] = pd.to_numeric(df["decil_challenger"], errors="coerce").astype("Int64")
        # Dedup por email preferindo o ledger (produção > snapshot), depois mais recente.
        df["_prio"] = (df["source"] == "ledger").astype(int)
        df = (df.sort_values(["email", "_prio", "data_captura"], ascending=[True, False, False])
                .drop_duplicates("email", keep="first")
                .drop(columns="_prio")
                .reset_index(drop=True))

    logger.info(
        "[matured_window] %s→%s (régua %s): %d leads (ledger %d + ponte %d, %d após dedup)",
        win_start.date(), win_end.date(), run_id[:8], len(df), n_led_raw, n_brg_raw, len(df),
    )

    # Fail-loud: janela madura de produção NÃO vem vazia. Vazio = régua errada,
    # cutover errado, ou fonte quebrada — não um estado legítimo silencioso.
    if df.empty and not allow_empty:
        raise ValueError(
            f"[matured_window] janela {win_start.date()}→{win_end.date()} veio VAZIA "
            f"(régua {run_id}). Fonte quebrada ou run_id/cutover errado — não silenciar."
        )
    return df

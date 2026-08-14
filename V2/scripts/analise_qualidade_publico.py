"""Qualidade dos leads e capacidade de separação dos modelos, por público.

Reproduz de ponta a ponta a análise documentada em
`docs/METODOLOGIA_QUALIDADE_POR_PUBLICO.md`: pega os leads de uma janela de
captação, resolve o decil de CADA modelo do A/B, cruza com as vendas reais e
devolve três tabelas — nota por público, conversão por público e capacidade de
separação (topo vs base).

Só LEITURA. Nada é gravado no ledger nem no warehouse.

Uso:
    python -m scripts.analise_qualidade_publico --cap-start 2026-07-21 --cap-end 2026-08-03
    python -m scripts.analise_qualidade_publico --cap-start ... --cap-end ... --sem-vendas-vivas
    python -m scripts.analise_qualidade_publico --cap-start ... --cap-end ... --json saida.json

Por que cada passo é assim está no doc; os pontos que já produziram número errado
estão marcados com `GOTCHA` aqui embaixo, no lugar onde importam.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import ssl
import sys
from pathlib import Path

_V2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_V2 / ".env")  # GOTCHA: `source .env` mutila credenciais com espaço/pipe.

import pandas as pd  # noqa: E402
import pg8000.native  # noqa: E402
import yaml  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# GOTCHA: registros_ml.created_at é `timestamp WITHOUT time zone` gravado em UTC.
# Converter UTC -> BRT antes de tirar a data. Fazer `created_at AT TIME ZONE
# 'America/Sao_Paulo'` direto desloca +3h e joga leads para o dia errado.
BRT = "((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'America/Sao_Paulo')"


def abrir_ledger(timeout: int = 300):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return pg8000.native.Connection(
        host=os.environ["LEDGER_DB_HOST"],
        port=int(os.environ.get("LEDGER_DB_PORT", "5432")),
        database=os.environ.get("LEDGER_DB_NAME", "ledger"),
        user=os.environ.get("LEDGER_DB_USER", "ledger_app"),
        password=os.environ["LEDGER_DB_PASSWORD"],
        ssl_context=ctx,
        timeout=timeout,
    )


def resolver_modelos(client_id: str = "devclub") -> dict:
    """Champion e Challenger vivos, lidos do YAML de modelo ativo.

    Ler do YAML (e não cravar no código) é o que faz esta análise continuar
    correta depois de uma promoção de modelo.
    """
    cfg = yaml.safe_load((_V2 / "configs" / "active_models" / f"{client_id}.yaml").read_text())
    champion = cfg["active_model"]["mlflow_run_id"]
    challenger = None
    for nome, v in (cfg.get("ab_test", {}).get("variants") or {}).items():
        rid = v.get("run_id")
        if rid and rid != champion and "challenger" in nome.lower():
            challenger = rid
            break
    if not challenger:
        raise SystemExit("Não achei o run_id do challenger no YAML de modelo ativo.")
    return {"champion": champion, "challenger": challenger}


def _expr_decil(run_id: str) -> str:
    """Decil DAQUELE modelo, seja qual for o papel dele no dia do lead.

    GOTCHA CENTRAL: o papel muda com o tempo. O abr_28 era Challenger até 25/07 e
    virou Champion depois. Ler a coluna `decil_champion` cega devolve o decil de
    modelos DIFERENTES em dias diferentes. Sempre casar por run_id.
    """
    return (f"CASE WHEN champion_run_id   = '{run_id}' THEN decil_champion "
            f"     WHEN challenger_run_id = '{run_id}' THEN decil_challenger END")


def carregar_leads(conn, ini: str, fim: str, modelos: dict) -> pd.DataFrame:
    dc = _expr_decil(modelos["champion"])
    dl = _expr_decil(modelos["challenger"])
    rows = conn.run(f"""
        SELECT lower(trim(email)) AS email, phone AS telefone,
               {BRT} AS data_captura, created_at,
               utm_campaign, utm_source, utm_medium,
               {dc} AS decil_champion_modelo, {dl} AS decil_challenger_modelo,
               (survey_responses IS NOT NULL) AS tem_pesquisa
        FROM registros_ml
        WHERE {BRT}::date BETWEEN DATE '{ini}' AND DATE '{fim}'
    """)
    df = pd.DataFrame(rows, columns=[
        "email", "telefone", "data_captura", "created_at", "utm_campaign",
        "utm_source", "utm_medium", "decil_champion_modelo",
        "decil_challenger_modelo", "tem_pesquisa"])
    df["data_captura"] = pd.to_datetime(df["data_captura"])
    return df


def completar_decil_faltante(conn, leads: pd.DataFrame, run_id: str, lote: int = 400) -> pd.DataFrame:
    """Pontua com o modelo pedido os leads que não têm decil dele no ledger.

    Acontece quando o modelo entrou em produção DEPOIS do início da janela: os
    leads anteriores nunca passaram por ele. Reconstrói o payload original a
    partir do `survey_responses` e roda o MESMO pipeline de produção.

    Traz um controle embutido: recalcula também o decil do OUTRO modelo e compara
    com o valor gravado no ledger. Se a reconstrução do payload estivesse errada,
    o controle acusaria. Falha alto se a taxa de acerto não for total.
    """
    from src.production_pipeline import LeadScoringPipeline
    from src.scoring.service import score_leads_from_payloads, LinhasPerdidasNoPreprocess

    faltam = leads[leads["decil_challenger_modelo"].isna() & leads["tem_pesquisa"]]
    if faltam.empty:
        logger.info("Nenhum decil faltante — nada a completar.")
        return leads
    logger.info("Completando %d leads sem decil do modelo %s…", len(faltam), run_id[:12])

    dl = _expr_decil(run_id)
    ini = leads["data_captura"].min().date()
    fim = leads["data_captura"].max().date()
    brutos = conn.run(f"""
        SELECT email, survey_responses, utm_source, utm_medium, utm_campaign, utm_content,
               utm_term, utm_url, has_computer, fbp, fbc, user_agent, ip, phone,
               first_name, last_name, event_id, created_at,
               champion_run_id, challenger_run_id, decil_champion, decil_challenger
        FROM registros_ml
        WHERE {BRT}::date BETWEEN DATE '{ini}' AND DATE '{fim}'
          AND {dl} IS NULL AND survey_responses IS NOT NULL
        ORDER BY created_at
    """)

    META = {"id", "ip", "clientEmail", "submittedAt"}

    def payload(r):
        sr = r[1] if not isinstance(r[1], str) else json.loads(r[1])
        return {
            "eventId": r[16] or sr.get("id"), "submittedAt": sr.get("submittedAt"),
            "email": r[0], "ip4": r[12] or sr.get("ip"), "phone": r[13],
            "firstName": r[14], "lastName": r[15], "hasComputer": r[8],
            "fbp": r[9], "fbc": r[10], "userAgent": r[11],
            "survey": {k: v for k, v in sr.items() if k not in META},
            "utm": {"source": r[2], "medium": r[3], "campaign": r[4],
                    "content": r[5], "term": r[6], "url": r[7]},
        }

    pipeline = LeadScoringPipeline()
    novos, ctrl_ok, ctrl_tot = {}, 0, 0
    for i in range(0, len(brutos), lote):
        chunk = brutos[i:i + lote]
        try:
            exps = score_leads_from_payloads([payload(r) for r in chunk], pipeline)
        except LinhasPerdidasNoPreprocess:
            # Dois leads idênticos colapsam no drop_duplicates do preprocess em lote.
            # O caminho de 1 lead é imune por construção.
            exps = []
            for r in chunk:
                try:
                    exps += score_leads_from_payloads([payload(r)], pipeline)
                except Exception:  # noqa: BLE001
                    exps.append(None)
        for r, e in zip(chunk, exps):
            if e is None:
                continue
            if e.decil_challenger is not None and e.challenger_run_id == run_id:
                novos[r[17]] = e.decil_challenger
            elif e.decil_champion is not None and e.champion_run_id == run_id:
                novos[r[17]] = e.decil_champion
            # controle: o decil do outro modelo tem que bater com o gravado
            gravado = r[20] if e.champion_run_id == r[18] else r[21]
            if gravado is not None and e.decil_champion is not None:
                ctrl_tot += 1
                ctrl_ok += int(gravado == e.decil_champion)
        logger.info("  %d/%d", min(i + lote, len(brutos)), len(brutos))

    if ctrl_tot:
        taxa = 100 * ctrl_ok / ctrl_tot
        logger.info("CONTROLE: %d/%d (%.2f%%) decis recalculados batem com o ledger",
                    ctrl_ok, ctrl_tot, taxa)
        assert taxa == 100.0, (
            f"[FALHA] O controle deu {taxa:.2f}%. A reconstrução do payload não está "
            "fiel ao que a produção fez — NÃO usar estes decis.")

    leads = leads.copy()
    leads["decil_challenger_modelo"] = leads.apply(
        lambda r: r["decil_challenger_modelo"] if pd.notna(r["decil_challenger_modelo"])
        else novos.get(r["created_at"]), axis=1)
    return leads


def carregar_vendas(conn, vivas: bool = True, dia_vivo: str | None = None) -> pd.DataFrame:
    """Vendas do warehouse + (opcional) pull vivo nos gateways.

    GOTCHA: `analytics.sales` é populada por job diário e fica um dia atrasada.
    Medir conversão do dia de hoje só com ela devolve ZERO e induz a concluir que
    o lançamento não vendeu. O pull vivo cobre esse buraco.
    """
    hist = pd.DataFrame(conn.run("""
        SELECT lower(trim(email)) AS email, phone AS telefone, sale_date, sale_value,
               sale_value_realizado, gateway AS origem
        FROM analytics.sales WHERE sale_date IS NOT NULL"""),
        columns=["email", "telefone", "sale_date", "sale_value", "sale_value_realizado", "origem"])
    frames = [hist]

    if vivas:
        from src.validation.data_loader import SalesDataLoader
        d = dia_vivo or pd.Timestamp.now(tz="America/Sao_Paulo").strftime("%Y-%m-%d")
        L = SalesDataLoader()
        fontes = {
            "guru": lambda: L.load_guru_sales_from_api(d, d),
            "hotmart": lambda: L.load_hotmart_sales_from_api(d, d),
            "asaas": lambda: L.load_asaas_sales(d, d),
            "boletex": lambda: L.load_boletex_sales_from_api(d, d),
            "tmb": lambda: L.load_tmb_api(d, d),
        }
        for nome, fn in fontes.items():
            try:
                df = fn()
                if df is not None and len(df):
                    cols = [c for c in ["email", "telefone", "sale_date", "sale_value", "origem"]
                            if c in df.columns]
                    d2 = df[cols].copy()
                    d2["sale_value_realizado"] = d2.get("sale_value", 0)
                    frames.append(d2)
                    logger.info("  gateway %s: %d vendas vivas em %s", nome, len(df), d)
            except Exception as e:  # noqa: BLE001 — um gateway fora não derruba o resto
                logger.warning("  gateway %s indisponível: %s", nome, str(e)[:120])

    vendas = pd.concat(frames, ignore_index=True)
    vendas["email"] = vendas["email"].astype(str).str.lower().str.strip()
    vendas["sale_date"] = pd.to_datetime(vendas["sale_date"], errors="coerce", utc=True).dt.tz_localize(None)
    return vendas.dropna(subset=["sale_date"]).drop_duplicates(subset=["email", "sale_date", "sale_value"])


def classificar_publico(campanha: str | None) -> str:
    """Quente e frio vivem no NOME da campanha, que chega inteiro no utm_campaign."""
    s = (campanha or "").upper()
    if "QUENTE" in s:
        return "quente"
    if "FRIO" in s:
        return "frio"
    return "sem rotulo"


def montar_tabelas(m: pd.DataFrame, modelos: dict) -> dict:
    publicos = ["quente", "frio", "sem rotulo", "TOTAL"]
    qualidade, separacao = [], []
    for pub in publicos:
        g = m if pub == "TOTAL" else m[m["publico"] == pub]
        if g.empty:
            continue
        linha = {"publico": pub, "leads": len(g),
                 "conversoes": int(g["converted"].sum()),
                 "taxa_conversao_pct": round(100 * g["converted"].mean(), 3)}
        for rot, col in [("champion", "decil_champion_modelo"), ("challenger", "decil_challenger_modelo")]:
            d = g[col].dropna()
            linha[f"pct_d9_d10_{rot}"] = round(100 * (d >= 9).mean(), 2) if len(d) else None
            linha[f"cobertura_{rot}"] = len(d)
        qualidade.append(linha)

        for rot, col in [("champion", "decil_champion_modelo"), ("challenger", "decil_challenger_modelo")]:
            gg = g[g[col].notna()]
            topo, base = gg[gg[col] >= 9], gg[gg[col] < 9]
            rt = topo["converted"].mean() if len(topo) else 0.0
            rb = base["converted"].mean() if len(base) else 0.0
            separacao.append({
                "modelo": rot, "run_id": modelos["champion" if rot == "champion" else "challenger"],
                "publico": pub, "n_topo": len(topo), "conv_topo": int(topo["converted"].sum()),
                "taxa_topo_pct": round(100 * rt, 3), "n_base": len(base),
                "conv_base": int(base["converted"].sum()), "taxa_base_pct": round(100 * rb, 3),
                "lift": round(rt / rb, 2) if rb else None,
            })
    return {"qualidade": qualidade, "separacao": separacao}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cap-start", required=True, help="início da captação (YYYY-MM-DD, BRT)")
    ap.add_argument("--cap-end", required=True, help="fim da captação (YYYY-MM-DD, BRT)")
    ap.add_argument("--client-id", default="devclub")
    ap.add_argument("--sem-vendas-vivas", action="store_true",
                    help="não bate nos gateways; usa só analytics.sales (que atrasa 1 dia)")
    ap.add_argument("--sem-completar-decil", action="store_true",
                    help="não pontua os leads sem decil do challenger (deixa a coluna incompleta)")
    ap.add_argument("--json", help="salva o resultado neste arquivo")
    args = ap.parse_args()

    modelos = resolver_modelos(args.client_id)
    logger.info("Champion   = %s", modelos["champion"])
    logger.info("Challenger = %s", modelos["challenger"])

    conn = abrir_ledger()
    leads = carregar_leads(conn, args.cap_start, args.cap_end, modelos)
    logger.info("Leads na janela: %d", len(leads))
    for rot, col in [("champion", "decil_champion_modelo"), ("challenger", "decil_challenger_modelo")]:
        logger.info("  com decil do %s: %d", rot, int(leads[col].notna().sum()))

    if not args.sem_completar_decil:
        leads = completar_decil_faltante(conn, leads, modelos["challenger"])

    vendas = carregar_vendas(conn, vivas=not args.sem_vendas_vivas)
    conn.close()
    logger.info("Vendas na base de cruzamento: %d", len(vendas))

    # GOTCHA: `use_temporal_validation=True` é OBRIGATÓRIO. Sem ele o matcher casa
    # compra ANTERIOR à captura do lead (já apareceu venda de 2023 casada com lead
    # de 2026), o que infla justamente o público quente, feito de quem já comprou.
    from src.validation.matching import match_leads_to_sales
    m = match_leads_to_sales(leads, vendas, use_temporal_validation=True)
    m["publico"] = m["utm_campaign"].apply(classificar_publico)

    out = {"janela": {"cap_start": args.cap_start, "cap_end": args.cap_end},
           "modelos": modelos, **montar_tabelas(m, modelos)}

    print("\n=== QUALIDADE E CONVERSÃO POR PÚBLICO ===")
    print(pd.DataFrame(out["qualidade"]).to_string(index=False))
    print("\n=== CAPACIDADE DE SEPARAÇÃO (topo D9-D10 vs base D1-D8) ===")
    print(pd.DataFrame(out["separacao"]).drop(columns=["run_id"]).to_string(index=False))

    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1, ensure_ascii=False))
        print(f"\n[salvo em {args.json}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
PROBE (descartável) — responde: ALGUMA campanha está CONFIGURADA pra
otimizar pelas nossas conversion actions (LeadQualified / LeadQualifiedHighQuality
/ custom goal LQHQ)? Independe de ter conversao reportada.

Read-only. Pode apagar depois.
"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "scripts"))
from probe_google_ads_reporting import build_client  # noqa

OUR_ACTION_IDS = {"7649573174": "LeadQualified", "7649572493": "LeadQualifiedHighQuality"}


def stream(ga, cid, q):
    for b in ga.search_stream(customer_id=cid, query=q):
        for r in b.results:
            yield r


def main():
    cid = os.environ["GOOGLE_ADS_CUSTOMER_ID"].replace("-", "")
    c = build_client()
    ga = c.get_service("GoogleAdsService")

    # 1) Custom goals e suas ações — achar o LQHQ e seu id
    print("=== CUSTOM GOALS (id, nome, status, ações) ===")
    lqhq_goal_ids = set()
    q = ("SELECT custom_conversion_goal.id, custom_conversion_goal.name, "
         "custom_conversion_goal.status, custom_conversion_goal.conversion_actions "
         "FROM custom_conversion_goal")
    for r in stream(ga, cid, q):
        g = r.custom_conversion_goal
        acts = [a.split("/")[-1] for a in g.conversion_actions]
        ours = [OUR_ACTION_IDS[a] for a in acts if a in OUR_ACTION_IDS]
        flag = f"  <<< contém {ours}" if ours else ""
        if ours:
            lqhq_goal_ids.add(str(g.id))
        print(f"  id={g.id} '{g.name}' status={g.status.name} acoes={acts}{flag}")

    # 2) Account-default: a categoria QUALIFIED_LEAD é biddable na conta?
    print("\n=== ACCOUNT-DEFAULT goals (customer_conversion_goal) ===")
    q = ("SELECT customer_conversion_goal.category, customer_conversion_goal.origin, "
         "customer_conversion_goal.biddable FROM customer_conversion_goal")
    for r in stream(ga, cid, q):
        cg = r.customer_conversion_goal
        mark = "  <<< QUALIFIED_LEAD" if cg.category.name == "QUALIFIED_LEAD" else ""
        print(f"  category={cg.category.name:20} origin={cg.origin.name:10} biddable={cg.biddable}{mark}")

    # 3) Campanhas com goal ESPECÍFICO (override) — quais e qual categoria/biddable
    print("\n=== CAMPANHAS com conversion goal configurado (category/biddable) ===")
    print("    (agregado; foco em QUALIFIED_LEAD biddable=true = otimiza p/ nossas ações)")
    q = ("SELECT campaign.id, campaign.name, campaign.status, "
         "campaign_conversion_goal.category, campaign_conversion_goal.origin, "
         "campaign_conversion_goal.biddable FROM campaign_conversion_goal "
         "WHERE campaign_conversion_goal.category = 'QUALIFIED_LEAD'")
    rows = list(stream(ga, cid, q))
    biddable_camps = {}
    for r in rows:
        if r.campaign_conversion_goal.biddable:
            biddable_camps[r.campaign.id] = (r.campaign.name, r.campaign.status.name)
    from collections import Counter
    by_status = Counter(s for _, s in biddable_camps.values())
    print(f"  Campanhas onde QUALIFIED_LEAD é biddable: {len(biddable_camps)} | por status: {dict(by_status)}")
    print("  --- só ENABLED (as que realmente rodam) ---")
    enabled = [(n, s) for n, s in biddable_camps.values() if s == "ENABLED"]
    if not enabled:
        print("    (NENHUMA campanha ENABLED otimiza por QUALIFIED_LEAD)")
    for name, status in enabled:
        print(f"    [ENABLED] {name[:75]}")

    # 4) Alguma campanha está linkada ao CUSTOM GOAL LQHQ? (tentativa)
    print("\n=== Campanhas linkadas ao custom goal LQHQ (id 6458091660) ===")
    try:
        q2 = ("SELECT campaign.id, campaign.name, campaign.status "
              "FROM campaign WHERE campaign.selective_optimization.conversion_actions "
              "CONTAINS ANY ('customers/%s/conversionActions/7649572493')" % cid)
        hits = list(stream(ga, cid, q2))
        if not hits:
            print("    (nenhuma — via selective_optimization)")
        for r in hits:
            print(f"    [{r.campaign.status.name}] {r.campaign.name}")
    except Exception as e:
        print(f"    (query selective_optimization não suportada: {type(e).__name__})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

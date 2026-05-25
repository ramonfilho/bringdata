"""Auditoria de integridade do pipeline lead→encoded features.

Re-scoreia N leads recentes do `registros_ml` via casa do scoring e olha o
vetor encodado de 52 colunas. Pra cada coluna:
  - quantos leads acenderam (valor != 0)
  - quais nunca acenderam (suspeita de divergência de nomenclatura)
  - cobertura por "família" de features de pesquisa (Tem_computador,
    Qual_a_sua_idade, etc.)

Não usa o endpoint HTTP — chama a casa direto, mais barato. Equivalente
funcional a rodar /predict/explain em loop.

Uso:
    cd V2 && python scripts/auditar_integridade_pipeline.py --limit 100
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _load_dotenv_if_present():
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if not os.path.exists(env_path) or os.environ.get('RAILWAY_DB_HOST'):
        return
    with open(env_path) as f:
        for raw in f:
            ln = raw.strip()
            if not ln or ln.startswith('#') or '=' not in ln:
                continue
            k, _, v = ln.partition('=')
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v


_load_dotenv_if_present()

import pg8000.native

from src.data import compose_repository
from src.production_pipeline import LeadScoringPipeline
from src.scoring.service import payload_from_record, score_lead_from_payload

logging.basicConfig(level=logging.WARNING, format='%(message)s')


def _family_of(feature_name: str) -> str:
    """Agrupa colunas one-hot na 'família' (prefixo até o último '_VALOR').

    Heurística: features one-hot tipicamente terminam com sufixo curto
    indicando o valor. Ex.:
      'Tem_computador_notebook_sim' -> 'Tem_computador_notebook'
      'Voc_possui_cart_o_de_cr_dito_Sim' -> 'Voc_possui_cart_o_de_cr_dito'
      'Qual_a_sua_idade_18_24_anos' -> 'Qual_a_sua_idade' (heurística falha aqui)

    Aceita falsos positivos — a tabela só serve pra dirigir o olho humano,
    não pra validação automática.
    """
    # Casos especiais: nome de coluna ordinal/numérico (não one-hot) — devolve ele mesmo
    if re.search(r'_(comprimento|valido|tem_sobrenome|valor|dia_semana)$', feature_name):
        return feature_name
    # Heurística: corta no último underscore se a parte final é curta (≤4 chars) ou conhecida
    parts = feature_name.rsplit('_', 1)
    if len(parts) == 2 and (len(parts[1]) <= 5 or parts[1].lower() in {
        'sim', 'nao', 'true', 'false', 'outros'
    }):
        return parts[0]
    return feature_name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--client-id', default='devclub')
    args = parser.parse_args()

    pipeline = LeadScoringPipeline(client_id=args.client_id)

    conn = pg8000.native.Connection(
        host=os.environ['RAILWAY_DB_HOST'],
        port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
        database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
        user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
        password=os.environ['RAILWAY_DB_PASSWORD'],
        timeout=30,
    )
    try:
        repo = compose_repository('registros_ml', railway_conn=conn)
        leads = repo.recent_leads(window_minutes=90 * 24 * 60, limit=args.limit)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Filtra: só leads com score persistido (resto foi skipped antes do scoring)
    com_score = [l for l in leads if l.score is not None]
    print(f"==> Auditoria de integridade — {len(com_score)} leads escaneados\n")

    # Re-scoreia todos, captura encoded_features
    encoded_per_lead: List[Dict[str, float]] = []
    leads_com_pesquisa: List[bool] = []
    erros: List[tuple] = []
    for lead in com_score:
        payload = payload_from_record(lead)
        try:
            exp = score_lead_from_payload(payload, pipeline)
        except Exception as e:
            erros.append((lead.event_id, f"{type(e).__name__}: {e}"))
            continue
        encoded_per_lead.append(exp.encoded_features)
        leads_com_pesquisa.append(bool(lead.survey_responses))

    if not encoded_per_lead:
        print("==> SEM DADOS PRA AUDITAR")
        return 1

    n = len(encoded_per_lead)
    com_pesquisa = sum(leads_com_pesquisa)
    print(f"   Leads com pesquisa preenchida: {com_pesquisa}/{n}")
    if erros:
        print(f"   Erros durante re-score: {len(erros)} (listados ao final)")

    # ── Contagem de ativação por feature ────────────────────────────────────
    all_features = sorted(encoded_per_lead[0].keys())
    ativacoes: Dict[str, int] = defaultdict(int)
    soma_valor: Dict[str, float] = defaultdict(float)
    for ef in encoded_per_lead:
        for k, v in ef.items():
            if v != 0:
                ativacoes[k] += 1
            soma_valor[k] += float(v)

    sempre_zero = [f for f in all_features if ativacoes[f] == 0]
    sempre_acesa = [f for f in all_features if ativacoes[f] == n]

    print(f"\n==> {len(all_features)} colunas no vetor encodado")
    print(f"   Sempre acesas (em todos os {n} leads): {len(sempre_acesa)}")
    print(f"   Sempre zeradas: {len(sempre_zero)}")

    # ── Top 15 features mais frequentes ─────────────────────────────────────
    print("\n==> TOP 15 FEATURES MAIS ACESAS")
    top = sorted(ativacoes.items(), key=lambda kv: kv[1], reverse=True)[:15]
    for f, c in top:
        media = soma_valor[f] / n
        print(f"   {f:55s} {c:4d}/{n}  ({100*c/n:5.1f}%)  média={media:.3f}")

    # ── Features sempre zeradas (suspeitas) ─────────────────────────────────
    if sempre_zero:
        print(f"\n==> FEATURES SEMPRE ZERADAS — {len(sempre_zero)}")
        print("   (esperado pra opções raras; ATENÇÃO se feature de pesquisa "
              "que algum lead deveria ter respondido)")
        for f in sempre_zero:
            print(f"   {f}")

    # ── Cobertura por família ───────────────────────────────────────────────
    # Pra cada lead com pesquisa: cada família deveria ter alguém aceso.
    familias: Dict[str, List[str]] = defaultdict(list)
    for f in all_features:
        familias[_family_of(f)].append(f)
    # Famílias com 2+ membros = one-hot (uma das opções deveria acender)
    onehot_families = {fam: cols for fam, cols in familias.items() if len(cols) >= 2}

    print(f"\n==> COBERTURA POR FAMÍLIA ONE-HOT ({len(onehot_families)} famílias)")
    print("   Pra cada família, conta quantos leads-com-pesquisa acenderam ≥1 coluna")
    falhas: List[tuple] = []
    for fam in sorted(onehot_families):
        cols = onehot_families[fam]
        leads_com_alguma_acesa = 0
        leads_relevantes = 0
        for ef, tem_pesq in zip(encoded_per_lead, leads_com_pesquisa):
            if not tem_pesq:
                continue
            leads_relevantes += 1
            if any(ef.get(c, 0) != 0 for c in cols):
                leads_com_alguma_acesa += 1
        if leads_relevantes == 0:
            continue
        pct = 100 * leads_com_alguma_acesa / leads_relevantes
        status = "✓" if pct == 100.0 else ("⚠" if pct >= 80 else "✗")
        cols_str = ", ".join(cols) if len(cols) <= 4 else f"{cols[0]}, ...({len(cols)} cols)"
        print(f"   {status}  {fam:50s} {leads_com_alguma_acesa}/{leads_relevantes} ({pct:5.1f}%)  [{cols_str}]")
        if pct < 100.0:
            falhas.append((fam, leads_com_alguma_acesa, leads_relevantes, cols))

    if falhas:
        print(f"\n==> FAMÍLIAS COM COBERTURA < 100% — {len(falhas)}")
        print("   Estes leads tinham pesquisa preenchida mas NENHUMA coluna da família foi acesa.")
        print("   Causa típica: divergência de nomenclatura entre payload e encoding.")
    else:
        print("\n==> Todas as famílias one-hot têm 100% de cobertura nos leads com pesquisa ✓")

    if erros:
        print(f"\n==> ERROS DURANTE RE-SCORE ({len(erros)})")
        for ev, msg in erros[:5]:
            print(f"   {ev[:8]}… {msg}")

    return 0


if __name__ == '__main__':
    sys.exit(main())

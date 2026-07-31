#!/usr/bin/env python3
"""Prova de equivalência: scorear N leads de uma vez == scorear N leads um a um.

POR QUE ESTE SCRIPT EXISTE
--------------------------
Em 31/07/2026 mediu-se em produção que o scoring custa ~0,73s por lead, porque
`score_lead_from_payload` monta um DataFrame de UMA linha e roda preprocess+predict
nele, 2 a 3 vezes por lead. Numa rodada de 250 leads isso vira ~750 passadas de
preprocess. Vetorizar (um DataFrame com os N leads, uma passada por variante) derruba
esse custo, mas só vale se o score de cada lead sair BIT A BIT igual ao de hoje.

Este script é o gate: enquanto ele não passar em 100% dos leads, a vetorização não vai
pra produção. Ele não testa "se roda", testa se o resultado é o mesmo.

O QUE ELE COMPARA
-----------------
Para cada lead, roda os dois caminhos com o MESMO predictor e o MESMO encoding:
  A) caminho atual  — `_score_variant` uma vez por lead (DataFrame de 1 linha)
  B) caminho novo   — `_score_variant_batch` uma vez para todos (DataFrame de N linhas)
e compara score e decil lead a lead, além de medir o tempo dos dois.

DECIL É COMPARADO COM IGUALDADE EXATA, sem tolerância: é ele que decide o que vai pro
CAPI e para qual público o lead entra. Score usa tolerância explícita (--tol), porque
operação de ponto flutuante em vetor pode diferir do escalar no último bit sem que isso
mude nenhuma decisão de negócio. Se a diferença de score chegar a mudar um decil, o
teste falha pelo decil, que é o que importa.

USO
    python scripts/validar_scoring_em_lote.py --limit 200
    python scripts/validar_scoring_em_lote.py --limit 200 --tol 1e-12

Exit 0 = equivalência provada. Exit 1 = divergiu, NÃO subir.
"""
import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

_V2 = Path(__file__).resolve().parent.parent
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))


def _load_dotenv_if_present() -> None:
    """Carrega .env via python-dotenv. NÃO usar `source .env`: senha com espaço
    ou pipe é mutilada pelo shell (ver memória reference_env_source_mutila_credenciais)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for candidate in (_V2 / '.env', _V2.parent / '.env'):
        if candidate.exists():
            load_dotenv(candidate)
            return


_load_dotenv_if_present()

import pandas as pd
import pg8000.native

from src.data import compose_repository
from src.production_pipeline import LeadScoringPipeline
from src.scoring.service import (
    LinhasPerdidasNoPreprocess,
    _score_variant,
    _score_variant_batch,
    payload_from_record,
)
from src.scoring.variants import resolve_champion_challenger
from api.survey_mapping import survey_lead_to_sheets_row
from src.core.payload_normalization import (
    payload_to_enrich,
    payload_to_survey_dict,
    payload_to_utm,
)

logging.basicConfig(level=logging.WARNING, format='%(message)s')
logger = logging.getLogger(__name__)


def _linha_do_lead(payload, pipeline) -> Optional[dict]:
    """payload → dict no formato que o pipeline espera. None se o payload não traduz."""
    try:
        survey_dict = payload_to_survey_dict(payload)
    except ValueError:
        return None  # slug fora do vocabulário: o caminho de produção também descarta
    utm = payload_to_utm(payload, pipeline._client_config.utm.source_from_url_slug)
    enrich = payload_to_enrich(payload)
    return survey_lead_to_sheets_row(
        survey_dict, utm, enrich, client_config=pipeline._client_config)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=200,
                        help='quantos leads carregar do ledger (default: 200)')
    parser.add_argument('--client-id', default='devclub')
    parser.add_argument('--tol', type=float, default=1e-9,
                        help='tolerância no score (decil é sempre exato)')
    args = parser.parse_args()

    print(f"==> Pipeline '{args.client_id}'")
    pipeline = LeadScoringPipeline(client_id=args.client_id)

    # Ledger mora no Cloud SQL desde 24/06/2026 — a `registros_ml` do Railway foi
    # dropada. O adaptador recebe a conexão por injeção, então o nome do kwarg
    # (`railway_conn`) é histórico e não amarra a fonte.
    import ssl as _ssl
    _ctx = _ssl.create_default_context()
    _ctx.check_hostname = False
    _ctx.verify_mode = _ssl.CERT_NONE
    conn = pg8000.native.Connection(
        host=os.environ['LEDGER_DB_HOST'],
        port=int(os.environ.get('LEDGER_DB_PORT', '5432')),
        database=os.environ.get('LEDGER_DB_NAME', 'ledger'),
        user=os.environ.get('LEDGER_DB_USER', 'ledger_app'),
        password=os.environ['LEDGER_DB_PASSWORD'],
        ssl_context=_ctx,
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

    rows, ids = [], []
    for lead in leads:
        row = _linha_do_lead(payload_from_record(lead), pipeline)
        if row is not None:
            rows.append(row)
            ids.append(lead.event_id)

    print(f"==> {len(rows)} leads utilizáveis (de {len(leads)} carregados)\n")
    if len(rows) < 2:
        print("!! Menos de 2 leads: não dá pra testar lote. Suba --limit.")
        return 1

    papeis = resolve_champion_challenger(pipeline)
    if not papeis:
        print("!! A/B não resolveu champion/challenger — sem o que comparar.")
        return 1

    falhas: List[str] = []

    for papel_nome in ('champion', 'challenger'):
        info = papeis[papel_nome]
        predictor = pipeline.get_variant_predictor(info['variant_name'])
        overrides = info['encoding_overrides']
        print(f"--- papel {papel_nome} (variante {info['variant_name']}) ---")

        # A) caminho atual: um DataFrame de 1 linha por lead.
        t0 = time.time()
        um_a_um = []
        for row in rows:
            s, d, _ = _score_variant(
                pipeline, pd.DataFrame([row]), predictor, overrides)
            um_a_um.append((s, d))
        t_individual = time.time() - t0

        # B) caminho novo: um DataFrame com todos.
        t0 = time.time()
        try:
            scores, decis, _ = _score_variant_batch(
                pipeline, pd.DataFrame(rows), predictor, overrides)
        except LinhasPerdidasNoPreprocess as e:
            print(f"  !! LOTE PERDEU LINHAS: {e}")
            falhas.append(f"{papel_nome}: {e}")
            continue
        t_lote = time.time() - t0

        # Comparação lead a lead.
        div_score = div_decil = 0
        for i, (s_ind, d_ind) in enumerate(um_a_um):
            if decis[i] != d_ind:
                div_decil += 1
                if div_decil <= 3:
                    print(f"  !! DECIL difere em {ids[i]}: "
                          f"individual=D{d_ind:02d} lote=D{decis[i]:02d}")
            if abs(scores[i] - s_ind) > args.tol:
                div_score += 1
                if div_score <= 3:
                    print(f"  !! SCORE difere em {ids[i]}: "
                          f"individual={s_ind!r} lote={scores[i]!r} "
                          f"(delta={abs(scores[i] - s_ind):.3e})")

        por_lead_ind = t_individual / len(rows)
        por_lead_lote = t_lote / len(rows)
        ganho = (t_individual / t_lote) if t_lote > 0 else float('inf')
        print(f"  tempo individual: {t_individual:6.2f}s  ({por_lead_ind*1000:7.1f} ms/lead)")
        print(f"  tempo em lote:    {t_lote:6.2f}s  ({por_lead_lote*1000:7.1f} ms/lead)")
        print(f"  ganho: {ganho:.0f}x")
        print(f"  divergências: decil={div_decil}  score={div_score}\n")

        if div_decil:
            falhas.append(f"{papel_nome}: {div_decil} decis divergentes")
        if div_score:
            falhas.append(f"{papel_nome}: {div_score} scores fora da tolerância")

    print("=" * 62)
    if falhas:
        print("REPROVADO — NÃO subir a vetorização:")
        for f in falhas:
            print(f"  - {f}")
        return 1
    print(f"APROVADO — {len(rows)} leads, score e decil idênticos nos dois caminhos.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

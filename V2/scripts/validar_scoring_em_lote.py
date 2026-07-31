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
    score_lead_from_payload,
    score_leads_from_payloads,
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

    # ------------------------------------------------------------------
    # Prova END-TO-END: o pacote completo (`ScoringExplanation`), não só o
    # primitivo. É o que o consumidor Pub/Sub realmente consome — inclui decil
    # dos dois papéis, score calibrado e variante roteada. Um primitivo correto
    # com um agrupamento errado passaria no teste de cima e falharia aqui.
    # ------------------------------------------------------------------
    print("--- pacote completo (ScoringExplanation) ---")
    payloads = [payload_from_record(l) for l in leads]
    payloads = [p for p in payloads if _linha_do_lead(p, pipeline) is not None]

    t0 = time.time()
    individuais = [score_lead_from_payload(p, pipeline) for p in payloads]
    t_ind = time.time() - t0

    t0 = time.time()
    em_lote = score_leads_from_payloads(payloads, pipeline)
    t_lote = time.time() - t0

    CAMPOS_EXATOS = ('decil', 'decil_champion', 'decil_challenger', 'variant',
                     'champion_run_id', 'challenger_run_id')
    CAMPOS_FLOAT = ('lead_score', 'score_champion', 'score_challenger',
                    'lead_score_calibrated')
    div_campo = {}
    colunas_extras_lote = set()
    for i, (a, b) in enumerate(zip(individuais, em_lote)):
        for campo in CAMPOS_EXATOS:
            if getattr(a, campo) != getattr(b, campo):
                div_campo[campo] = div_campo.get(campo, 0) + 1
                if div_campo[campo] <= 2:
                    print(f"  !! {campo} difere em {ids[i]}: "
                          f"individual={getattr(a, campo)!r} lote={getattr(b, campo)!r}")
        for campo in CAMPOS_FLOAT:
            va, vb = getattr(a, campo), getattr(b, campo)
            if (va is None) != (vb is None):
                div_campo[campo] = div_campo.get(campo, 0) + 1
                continue
            if va is not None and abs(va - vb) > args.tol:
                div_campo[campo] = div_campo.get(campo, 0) + 1
                if div_campo[campo] <= 2:
                    print(f"  !! {campo} difere em {ids[i]}: "
                          f"individual={va!r} lote={vb!r}")
        # encoded_features: o que FALHA é valor divergente numa chave comum. Chave a
        # mais no lote é esperado e inofensivo — o one-hot cria uma coluna por
        # categoria presente no DataFrame, então o lote traz categorias de outros
        # leads (com valor 0 para este). O alinhamento com o feature_registry
        # descarta o excedente antes do modelo, e é por isso que o score não muda.
        # Comparar os dicts com `!=` reprovaria por diferença de composição, não de
        # conteúdo, e mascararia o que realmente importa.
        comuns = set(a.encoded_features) & set(b.encoded_features)
        divergentes = [
            k for k in comuns if a.encoded_features[k] != b.encoded_features[k]
        ]
        if divergentes:
            div_campo['encoded_features'] = div_campo.get('encoded_features', 0) + 1
            if div_campo['encoded_features'] <= 2:
                k = divergentes[0]
                print(f"  !! encoded_features[{k}] difere em {ids[i]}: "
                      f"individual={a.encoded_features[k]!r} "
                      f"lote={b.encoded_features[k]!r}")
        extras = set(b.encoded_features) - set(a.encoded_features)
        if extras:
            colunas_extras_lote.update(extras)
        faltantes = set(a.encoded_features) - set(b.encoded_features)
        if faltantes:
            # Este caso NÃO é benigno: chave que existe no individual e some no lote
            # significaria feature perdida, não categoria emprestada de outro lead.
            div_campo['encoded_features_faltante'] = (
                div_campo.get('encoded_features_faltante', 0) + 1)

    print(f"  tempo individual: {t_ind:6.2f}s  ({t_ind / len(payloads) * 1000:7.1f} ms/lead)")
    print(f"  tempo em lote:    {t_lote:6.2f}s  ({t_lote / len(payloads) * 1000:7.1f} ms/lead)")
    print(f"  ganho: {(t_ind / t_lote) if t_lote else float('inf'):.0f}x")
    if div_campo:
        for campo, n in div_campo.items():
            print(f"  !! {campo}: {n} divergências")
            falhas.append(f"pacote completo, {campo}: {n} divergências")
    else:
        print(f"  divergências: NENHUMA em {len(payloads)} leads "
              f"({len(CAMPOS_EXATOS) + len(CAMPOS_FLOAT)} campos + encoded_features)")
    if colunas_extras_lote:
        print(f"  (nota: o lote expôs {len(colunas_extras_lote)} coluna(s) one-hot a "
              f"mais, de categorias presentes em outros leads do lote. Valor 0 para "
              f"quem não tem a categoria, descartadas no alinhamento com o "
              f"feature_registry — por isso o score não muda.)")
        for c in sorted(colunas_extras_lote)[:3]:
            print(f"     - {c}")
    print()

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

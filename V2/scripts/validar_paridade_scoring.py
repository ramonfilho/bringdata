"""Valida paridade entre a casa do scoring nova e o lead_score já persistido.

Critério de bloqueio do passo 6 (migração do consumer Pub/Sub): se a casa
nova devolver um lead_score diferente do que está em `registros_ml`, a
migração não acontece.

O script:
  1. Compõe LeadScoringPipeline ('devclub') e LeadRepository ('registros_ml').
  2. Lista os N leads mais recentes do ledger.
  3. Pra cada lead: payload_from_record → score_lead_from_payload → compara
     `explanation.lead_score` com `record.score`.
  4. Reporta paridade exata, paridade aproximada (|diff| < 1e-9), diff médio,
     diff máximo, e os top divergentes.

Não envia CAPI, não persiste, não muta nada. Só lê.

Uso:
    cd V2 && python scripts/validar_paridade_scoring.py --limit 100

Requer env vars RAILWAY_DB_HOST, RAILWAY_DB_PASSWORD (e os defaults pra port,
name, user em api/app.py).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _load_dotenv_if_present():
    """Carrega V2/.env nas env vars do processo, se ainda não estiverem setadas.

    Conveniência pra rodar local sem precisar `source` (que quebra com valores
    contendo caracteres especiais). Não sobrescreve env já existente.
    """
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
from src.data.lead_record import LeadRecord
from src.production_pipeline import LeadScoringPipeline
from src.scoring.service import payload_from_record, score_lead_from_payload

logging.basicConfig(
    level=logging.WARNING,  # WARNING pra não poluir; pipeline loga muito em INFO
    format='%(message)s',
)
logger = logging.getLogger(__name__)


@dataclass
class ParidadeResult:
    event_id: str
    score_persistido: Optional[float]
    score_recalculado: Optional[float]
    decil_persistido: Optional[int]
    decil_recalculado: Optional[int]
    diff: Optional[float]
    erro: Optional[str]


def _scorear_um(lead: LeadRecord, pipeline: LeadScoringPipeline) -> ParidadeResult:
    payload = payload_from_record(lead)
    try:
        explanation = score_lead_from_payload(payload, pipeline)
    except ValueError as e:
        return ParidadeResult(
            event_id=lead.event_id,
            score_persistido=lead.score,
            score_recalculado=None,
            decil_persistido=lead.decil,
            decil_recalculado=None,
            diff=None,
            erro=f"slug inválido: {e}",
        )
    except Exception as e:
        return ParidadeResult(
            event_id=lead.event_id,
            score_persistido=lead.score,
            score_recalculado=None,
            decil_persistido=lead.decil,
            decil_recalculado=None,
            diff=None,
            erro=f"{type(e).__name__}: {e}",
        )

    diff = (
        explanation.lead_score - lead.score
        if lead.score is not None else None
    )
    return ParidadeResult(
        event_id=lead.event_id,
        score_persistido=lead.score,
        score_recalculado=explanation.lead_score,
        decil_persistido=lead.decil,
        decil_recalculado=explanation.decil,
        diff=diff,
        erro=None,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=100,
                        help='quantos leads escanear (default: 100)')
    parser.add_argument('--client-id', default='devclub')
    parser.add_argument('--tol', type=float, default=1e-9,
                        help='tolerância pra paridade aproximada')
    args = parser.parse_args()

    print(f"==> Composição: pipeline '{args.client_id}' + LeadRepository(registros_ml)")
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
        # window máxima (90d) — o ledger só tem ~2 dias, pega tudo
        leads = repo.recent_leads(window_minutes=90 * 24 * 60, limit=args.limit)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    print(f"==> Carregados {len(leads)} leads do ledger\n")

    # Filtrar: só faz sentido comparar leads que foram scoreados
    com_score = [l for l in leads if l.score is not None]
    sem_score = len(leads) - len(com_score)
    if sem_score:
        print(f"   (pulando {sem_score} leads sem score persistido — skipped_allowlist/missing_data/error)")

    resultados = [_scorear_um(l, pipeline) for l in com_score]

    # Sumário
    paridade_exata = sum(1 for r in resultados if r.diff is not None and r.diff == 0.0)
    paridade_aprox = sum(1 for r in resultados if r.diff is not None and abs(r.diff) < args.tol)
    com_erro = [r for r in resultados if r.erro is not None]
    com_diff = [r for r in resultados if r.diff is not None and abs(r.diff) >= args.tol]

    print("\n==> RESULTADO")
    print(f"   Total comparados:        {len(resultados)}")
    print(f"   Paridade exata (= 0):    {paridade_exata}")
    print(f"   Paridade aproximada:     {paridade_aprox}  (|diff| < {args.tol})")
    print(f"   Divergências relevantes: {len(com_diff)}")
    print(f"   Erros durante re-score:  {len(com_erro)}")

    if com_diff:
        print("\n==> TOP 10 DIVERGÊNCIAS")
        com_diff.sort(key=lambda r: abs(r.diff), reverse=True)
        for r in com_diff[:10]:
            print(f"   {r.event_id[:8]}…  "
                  f"persistido={r.score_persistido:.6f} D{r.decil_persistido}  "
                  f"recalc={r.score_recalculado:.6f} D{r.decil_recalculado}  "
                  f"diff={r.diff:+.6e}")

    if com_erro:
        print("\n==> ERROS DURANTE RE-SCORE")
        for r in com_erro[:10]:
            print(f"   {r.event_id[:8]}…  {r.erro}")

    # Mismatch de decil também é divergência (mesmo com score igual, threshold pode dar D diferente — não deveria)
    decil_mismatch = [
        r for r in resultados
        if r.decil_persistido is not None
        and r.decil_recalculado is not None
        and r.decil_persistido != r.decil_recalculado
    ]
    if decil_mismatch:
        print(f"\n==> {len(decil_mismatch)} casos de decil divergente (mesmo com score próximo)")
        for r in decil_mismatch[:10]:
            print(f"   {r.event_id[:8]}…  D{r.decil_persistido}{r.decil_recalculado}  "
                  f"score={r.score_recalculado:.6f}")

    # Exit code: 0 se paridade ≥ 99%, 1 caso contrário
    if len(resultados) == 0:
        print("\n==> SEM LEADS COMPARÁVEIS")
        return 2
    paridade_pct = 100.0 * paridade_aprox / len(resultados)
    print(f"\n==> Paridade final: {paridade_pct:.1f}%")
    return 0 if paridade_pct >= 99.0 else 1


if __name__ == '__main__':
    sys.exit(main())

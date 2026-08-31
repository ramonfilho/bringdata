#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""releitura_teto — teto por criativo com histórico ATUALIZADO até hoje.

    python3 scripts/releitura_teto.py LF65 [filtro-do-criativo]

Decisão do Ramon (31/08): o teto do PAINEL é point-in-time (o histórico corta
no início da captação, então o último LF fechado fica de fora — o AD0424 rodou
no LF64 e o teto dele no painel do LF65 não sabia disso). Enquanto a
atualização automática do teto não vira arquitetura, este script força a
releitura por query, 2x POR SEMANA: mesmo cálculo do painel, histórico com
corte = amanhã (todo lançamento já fechado entra). NÃO grava nada em lugar
nenhum; imprime teto relido vs teto do painel, pro semáforo das ações.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_V2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2))
os.chdir(_V2)
os.environ.setdefault("LAUNCHES_SOURCE", "table")
from dotenv import load_dotenv  # noqa: E402

load_dotenv(_V2 / ".env")


def main() -> int:
    lf = sys.argv[1] if len(sys.argv) > 1 else "LF65"
    filtro = (sys.argv[2] if len(sys.argv) > 2 else "").lower()
    import json

    from src.core.launches import load_launches
    from src.data.analytics_connection import open_analytics_connection
    from src.data.criativo_historico import (calcula_historico,
                                             criativo_do_lead, mapa_de_nomes)
    from src.data.ledger_connection import open_ledger_read_connection
    from src.data.reference_reader import read_rolling_reference
    from src.monitoring.teto import CalculadoraDeTeto
    from src.monitoring.teto_por_chave import tetos_completos
    from src.validation.lancamento_unidades import (BRT,
                                                    _historico_para_consulta)

    cfg = load_launches().get(lf)
    if not cfg:
        print(f"{lf} não está no calendário", file=sys.stderr)
        return 2
    cs = datetime.strptime(str(cfg["cap_start"])[:10], "%Y-%m-%d").date()
    ce = datetime.strptime(str(cfg["cap_end"])[:10], "%Y-%m-%d").date()

    an = open_analytics_connection(timeout=900)
    lg = open_ledger_read_connection()
    try:
        ref = read_rolling_reference("devclub", conn=an)
        calc = CalculadoraDeTeto.de_referencia_carregada(ref)
        mapa = mapa_de_nomes(an, client_id="devclub")
        hist = _historico_para_consulta(
            calcula_historico(an, client_id="devclub",
                              corte=date.today() + timedelta(days=1)), mapa)
        ws = datetime.combine(cs, datetime.min.time(), BRT) \
            .astimezone(timezone.utc).replace(tzinfo=None)
        we = datetime.combine(ce + timedelta(days=1), datetime.min.time(), BRT) \
            .astimezone(timezone.utc).replace(tzinfo=None)
        _, por_unidade, _ = tetos_completos(
            an, lg, run_id=ref["ruler_run_id"], win_start=ws, win_end=we,
            client_id="devclub", calc=calc, historico=hist,
            chave_criativo=lambda c: criativo_do_lead(c, mapa))
    finally:
        for c in (lg, an):
            try:
                c.close()
            except Exception:
                pass

    # teto do PAINEL (point-in-time) pra comparação, se o contrato existir
    velho: dict = {}
    pc = _V2 / f"docs/relatorios/{lf.lower()}_resultado/contrato.json"
    if pc.exists():
        for x in json.loads(pc.read_text())["tabelas"]["unidades"]:
            if x.get("teto") is not None:
                velho.setdefault(x["criativo"], []).append(float(x["teto"]))

    agg: dict = {}
    for u in por_unidade:
        if not u["teto"].ok:
            continue
        a = agg.setdefault(str(u["criativo"]), [0.0, 0])
        a[0] += float(u["teto"].valor) * int(u["n"])
        a[1] += int(u["n"])

    print(f"{lf} — teto por criativo com histórico até HOJE "
          f"(ponderado por leads; 'painel' = point-in-time do contrato)")
    for k, (soma, n) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
        if filtro and filtro not in k.lower():
            continue
        t2 = soma / n
        v = (sum(velho[k]) / len(velho[k])) if velho.get(k) else None
        vtx = f"{v:7.2f}" if v is not None else "      —"
        print(f"  {k[:42]:42} leads {n:>6,}  relido: teto2 {t2:7.2f}  "
              f"teto1,5 {t2 * 4 / 3:7.2f}  | painel teto2 {vtx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

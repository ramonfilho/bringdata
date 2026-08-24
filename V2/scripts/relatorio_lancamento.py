#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""relatorio_lancamento — o relatório por lançamento em UM comando.

    python3 scripts/relatorio_lancamento.py --lf LF64 --out docs/relatorios/lf64_resultado

Roda a máquina (`src.validation.lancamento_unidades.constroi_lancamento`) e
congela TUDO num `contrato.json`: as tabelas, os julgamentos e — crucial — o
payload inteiro da referência usada, porque a tabela viva é sobrescrita pelo
refresh semanal e o relatório não pode depender de a linha continuar lá.

O renderizador do painel lê SÓ o contrato (não toca em banco): re-rodar o
relatório quando as vendas caírem é rodar o MESMO comando de novo — o único
delta legítimo entre os dois contratos é a receita.

Saídas de falha (silêncio é proibido):
  exit 2  sem referência rolante (o teto não tem âncora)
  exit 3  cobertura de gasto casado abaixo do piso (--piso-gasto, default 90%)
"""
import argparse
import json
import math
import os
import sys
from datetime import date, datetime
from pathlib import Path

_V2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2))
os.chdir(_V2)
os.environ.setdefault("LAUNCHES_SOURCE", "table")   # LF novo mora na tabela

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_V2 / ".env")       # nunca `source .env` (mutila credenciais)


def _jsonable(o):
    """Contrato 100% JSON: datas viram texto, NaN vira null (NaN não é JSON e
    quebraria o renderizador no primeiro parse), DataFrame vira lista de linhas."""
    import pandas as pd
    if isinstance(o, (datetime, date)):
        return str(o)
    if isinstance(o, float) and math.isnan(o):
        return None
    if isinstance(o, pd.DataFrame):
        return json.loads(o.to_json(orient="records", force_ascii=False))
    if isinstance(o, set):
        return sorted(o)
    return str(o)


def main() -> int:
    ap = argparse.ArgumentParser(description="Relatório por lançamento (um comando)")
    ap.add_argument("--lf", required=True, help="Nome do lançamento (ex.: LF64)")
    ap.add_argument("--as-of", default=None, help="Data de referência (default: hoje BRT)")
    ap.add_argument("--out", default=None,
                    help="Pasta de saída (default: docs/relatorios/<lf>_resultado)")
    ap.add_argument("--piso-gasto", type=float, default=0.90,
                    help="Piso da fração do gasto Meta casado por unidade (exit 3 abaixo)")
    args = ap.parse_args()

    from src.validation.lancamento_unidades import constroi_lancamento

    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    r = constroi_lancamento(args.lf, as_of=as_of)
    meta, cob = r["meta"], r["meta"]["cobertura"]

    # ── linha de cobertura (obrigatória, é a prova de que o relatório viu tudo)
    pct = cob["pct_gasto_casado"]
    print(f"\n{args.lf}  cap {meta['cap_start']}→{meta['cap_end']}  vendas "
          f"{meta['vendas_start']}→{meta['vendas_end']}  estado={meta['estado']}")
    print(f"referência {meta['referencia_id']}  fator {meta['fator_rastreamento']:.4f} "
          f"({meta['fator_procedencia']})  crédito {meta['credito_nao_respondente']}  "
          f"régua {meta['ruler_run_id'][:8]}")
    print(f"cadastros {cob['cadastros']:,}  unidades {len(r['unidades'])}  "
          f"campanhas {len(r['campanhas'])}")
    print(f"gasto Meta R$ {cob['gasto_meta_total']:,.2f}  casado por unidade "
          f"R$ {cob['gasto_meta_casado']:,.2f}"
          + (f"  ({100*pct:.1f}%)" if pct is not None else ""))
    print(f"sem criativo {cob['leads_sem_criativo']}  macro quebrada "
          f"{cob['leads_criativo_macro']}  ids não resolvidos {cob['ids_nao_resolvidos']}")

    # ── régua de produto: produto órfão (vendeu, não casou padrão) GRITA
    orfaos = [p for p in meta["produtos_janela"] if not p["casou_padrao"]]
    if orfaos:
        print("\n⚠ PRODUTOS FORA DA RÉGUA (vendidos na janela, sem padrão no yaml):")
        for p in orfaos:
            print(f"   {p['produto']}  [{p['gateway']}]  n={p['n']}  R$ {p['valor']:,.2f}")
        print("   → decidir com o dono se entram, antes de publicar faturamento.")

    j = r["julgamento"]
    modo = "PREVISÃO (sem venda ingerida)" if not meta["tem_venda"] else "MEDIDO"
    print(f"\nteto ({modo}): {j['julgaveis']} unidades julgáveis "
          f"(cortes ≥{meta['corte_leads']} leads e ≥R$ {meta['corte_gasto']:.0f}) — "
          f"dentro {j['dentro']['n']} (R$ {j['dentro']['gasto']:,.2f}) · "
          f"acima {j['acima']['n']} (R$ {j['acima']['gasto']:,.2f})")
    if meta["tem_venda"]:
        for lado in ("dentro", "acima"):
            b = j[lado]
            print(f"  {lado:>6}: vendas {b['vendas']}  ROAS {b['roas_ponderado']:.2f}  "
                  f"lucro R$ {b['lucro']:,.2f}  | bateu meta {b['bateu_meta']}  "
                  f"lucro>1000 {b['lucro_acima_1000']}  positivo {b['roas_positivo']}")
        if j["fisher_p"] is not None:
            print(f"  Fisher p={j['fisher_p']:.4f}  Mann-Whitney p={j['mannwhitney_p']}")

    # ── contrato congelado
    out = Path(args.out or f"docs/relatorios/{args.lf.lower()}_resultado")
    out.mkdir(parents=True, exist_ok=True)
    contrato = dict(
        lf=args.lf, meta=meta, julgamento=j,
        tabelas=dict(
            campanhas=r["campanhas"],
            unidades=r["unidades"],
            criativos_por_tipo=r["criativos_por_tipo"],
        ),
    )
    dst = out / "contrato.json"
    dst.write_text(json.dumps(contrato, ensure_ascii=False, indent=1,
                              default=_jsonable))
    print(f"\ncontrato congelado em {dst}  ({dst.stat().st_size:,} bytes)")

    # ── pisos (depois de gravar: o contrato existe mesmo quando o piso grita,
    #    senão o diagnóstico do problema fica sem o dado que o mostraria)
    if pct is not None and pct < args.piso_gasto:
        print(f"\n✗ cobertura de gasto casado {100*pct:.1f}% abaixo do piso "
              f"{100*args.piso_gasto:.0f}% — investigar antes de publicar", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

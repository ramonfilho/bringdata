#!/usr/bin/env python3
"""Vigia pós-deploy: depois dos 100%, olha a revisão viva por N minutos e volta sozinho.

O progression_gate vigia até o último degrau. Este script cobre a hora seguinte. A cada
`--intervalo` minutos colhe dois sinais que são DA REVISÃO, não do serviço inteiro:
  1. feature-report filtrado por revisão (severity ERROR = feature crítica ausente ou mal
     formada nos lotes que essa revisão scoreou);
  2. taxa de 5xx da revisão nos logs de requisição do Cloud Run.

ROLLBACK quando o feature-report está em ERROR, ou quando a taxa de 5xx passa de
`--max-5xx` com pelo menos `--min-requisicoes` requisições na janela (uma requisição ruim
em dez não é sinal, é ruído). Sem lote na janela não é motivo para voltar: só diz que
ainda não chegou lead.

Rollback = deploy-gate promote --revision <anterior> --to 100 --rollback --yes, o mesmo
caminho dos degraus (scripts/promover_com_rollback.sh). Se o rollback falhar, o comando
para rodar na mão fica impresso.

Uso (o deploy.yml chama no job `vigia`, logo depois do job `production`):
    python3 scripts/vigia_pos_deploy.py --revision R --rollback PREV --minutos 60 --intervalo 5

Exit: 0 vigiou até o fim sem motivo para voltar; 1 fez rollback (ou tentou); 3 infra.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

try:  # como módulo: python -m scripts.x, a partir de V2/
    from scripts.progression_gate import (MIN_REQUISICOES_5XX, check_feature_report,
                                          get_5xx_rate, instalar_auth_gcp)
    from scripts.cloud_run_urls import get_service_url
except ModuleNotFoundError:  # por caminho: python V2/scripts/x.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from progression_gate import (MIN_REQUISICOES_5XX, check_feature_report,  # noqa: E402
                                  get_5xx_rate, instalar_auth_gcp)
    from cloud_run_urls import get_service_url  # noqa: E402

_V2 = Path(__file__).resolve().parents[1]


def julgar(feat: dict, cinco_xx: dict, max_5xx: float = 0.01,
           min_requisicoes: int = MIN_REQUISICOES_5XX):
    """Decide a partir dos dois sinais. Devolve (veredito, motivos).

    veredito: 'ROLLBACK' | 'OK' | 'SEM_DADOS'.
    """
    motivos = []
    if feat.get('ok') and feat.get('status') == 'ERROR':
        motivos.append("[T1-11] feature_validator severity=ERROR na revisão viva")
    total = int((cinco_xx or {}).get('total') or 0)
    taxa = (cinco_xx or {}).get('rate')
    if taxa is not None and total >= min_requisicoes and taxa > max_5xx:
        motivos.append(f"[5xx] {cinco_xx.get('n_5xx', 0)} de {total} requisições ({taxa:.2%}) > {max_5xx:.2%}")
    if motivos:
        return 'ROLLBACK', motivos
    sem_lote = not feat.get('ok') or int(feat.get('total_batches') or 0) == 0
    if sem_lote and total < min_requisicoes:
        return 'SEM_DADOS', ["sem lote e poucas requisições na janela; nada a julgar ainda"]
    return 'OK', [f"feature_report={feat.get('status')} lotes={feat.get('total_batches', 0)}; 5xx={taxa} em {total} req."]


def colher_sinais(base_url: str, revision: str, project: str, janela_horas: int) -> tuple:
    feat = check_feature_report(base_url, revision, janela_horas)
    cinco = get_5xx_rate(revision, project, janela_horas)
    return feat, cinco


def comando_rollback(anterior: str) -> list:
    return ["bash", str(_V2 / "api" / "deploy-gate.sh"), "promote", "--revision", anterior,
            "--to", "100", "--rollback", "--yes"]


def vigiar(revision: str, anterior: str, minutos: int, intervalo: int, colher, rodar=subprocess.run,
           relogio=time.monotonic, dormir=time.sleep, max_5xx: float = 0.01,
           min_requisicoes: int = MIN_REQUISICOES_5XX, resumo=print) -> int:
    inicio = relogio()
    rodada = 0
    while True:
        rodada += 1
        try:
            feat, cinco = colher()
        except Exception as e:  # infra: não é motivo para voltar, mas fica registrado
            resumo(f"[vigia] rodada {rodada}: erro colhendo sinais ({e}); segue.")
            feat, cinco = {'ok': False, 'reason': str(e)}, {}
        veredito, motivos = julgar(feat, cinco, max_5xx, min_requisicoes)
        decorrido = (relogio() - inicio) / 60.0
        resumo(f"[vigia] {decorrido:.0f} min: {veredito}: " + "; ".join(motivos))
        if veredito == 'ROLLBACK':
            resumo(f"[vigia] ROLLBACK AUTOMÁTICO: devolvendo 100% para {anterior}.")
            r = rodar(comando_rollback(anterior))
            if getattr(r, 'returncode', 1) == 0:
                resumo(f"[vigia] rollback feito: {anterior} com 100%, {revision} fora do tráfego.")
            else:
                resumo("[vigia] ROLLBACK FALHOU. Rode na mão: " + " ".join(comando_rollback(anterior)[1:]))
            return 1
        if decorrido >= minutos:
            resumo(f"[vigia] {minutos} min sem motivo para voltar. {revision} segue com 100%.")
            return 0
        dormir(intervalo * 60)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--revision', required=True, help='revisão que acabou de receber 100%')
    ap.add_argument('--rollback', required=True, help='revisão que tinha 100% antes (alvo do rollback)')
    ap.add_argument('--minutos', type=int, default=60)
    ap.add_argument('--intervalo', type=int, default=5, help='minutos entre colheitas')
    ap.add_argument('--janela-horas', type=int, default=1, help='horas para trás em cada colheita')
    ap.add_argument('--max-5xx', type=float, default=0.01)
    ap.add_argument('--min-requisicoes', type=int, default=MIN_REQUISICOES_5XX)
    ap.add_argument('--service', default='smart-ads-api')
    ap.add_argument('--region', default='us-central1')
    ap.add_argument('--project', default='smart-ads-451319')
    args = ap.parse_args()

    instalar_auth_gcp()
    try:
        base_url = get_service_url(args.service, args.region, args.project)
    except Exception as e:
        print(f"[vigia] ERRO: sem URL do serviço ({e})", file=sys.stderr)
        return 3
    print(f"[vigia] {args.revision} por {args.minutos} min, a cada {args.intervalo} min, janela {args.janela_horas}h; volta para {args.rollback} se der ruim.")
    return vigiar(args.revision, args.rollback, args.minutos, args.intervalo,
                  colher=lambda: colher_sinais(base_url, args.revision, args.project, args.janela_horas),
                  max_5xx=args.max_5xx, min_requisicoes=args.min_requisicoes)


if __name__ == '__main__':
    sys.exit(main())

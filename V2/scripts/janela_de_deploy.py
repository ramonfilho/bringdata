#!/usr/bin/env python3
"""Janela de deploy: decide se o tráfego real pode andar AGORA.

Substitui o clique humano nos environments do GitHub por um freio de calendário, que
é o que o padrão de entrega progressiva usa: o gate (progression_gate.py) responde
"pode?" pelos números; esta janela responde "é hora?".

Regras (fuso America/Sao_Paulo):
  1. dia útil, de segunda a sexta;
  2. das 09:00 às 18:00;
  3. nenhum lançamento com carrinho aberto (vendas_start <= hoje <= vendas_end no
     calendário de LFs, analytics.launch_calendar com fallback para configs/launches.yaml).

Saída (stdout e, se existir, $GITHUB_OUTPUT):
  aberta=true|false
  motivo=<por que fechou, ou "dentro da janela">
  proxima=<próxima abertura em ISO, ou vazio>

Exit 0 sempre que decidiu (aberta ou fechada); 1 só em erro inesperado.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")
DIAS_UTEIS = {0, 1, 2, 3, 4}          # segunda=0 ... sexta=4
HORA_INICIO = time(9, 0)
HORA_FIM = time(18, 0)
NOMES_DIA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


@dataclass
class Decisao:
    aberta: bool
    motivos: List[str] = field(default_factory=list)
    proxima: Optional[datetime] = None

    @property
    def motivo(self) -> str:
        return "; ".join(self.motivos) if self.motivos else "dentro da janela"


def carrinhos_abertos(calendario: Dict[str, dict], hoje: date) -> List[str]:
    """LFs com carrinho aberto em `hoje`: `vendas_start <= hoje <= vendas_end`.

    Entrada sem as duas datas, ou com data que não parseia, é ignorada: o calendário
    tem LFs antigos com `vendas_end` vazio e isso não é motivo para travar deploy.
    """
    abertos = []
    for lf, e in (calendario or {}).items():
        vs, ve = (e or {}).get("vendas_start"), (e or {}).get("vendas_end")
        if not vs or not ve:
            continue
        try:
            ds, de = date.fromisoformat(str(vs)), date.fromisoformat(str(ve))
        except ValueError:
            continue
        if ds <= hoje <= de:
            abertos.append(f"{lf} ({ds} a {de})")
    return sorted(abertos)


def _dia_livre(calendario: Dict[str, dict], d: date) -> bool:
    return d.weekday() in DIAS_UTEIS and not carrinhos_abertos(calendario, d)


def proxima_abertura(agora: datetime, calendario: Dict[str, dict], horizonte_dias: int = 90) -> Optional[datetime]:
    """Primeiro instante >= agora em que a janela está aberta (ou None dentro do horizonte)."""
    for i in range(horizonte_dias + 1):
        d = agora.date() + timedelta(days=i)
        if not _dia_livre(calendario, d):
            continue
        inicio = datetime.combine(d, HORA_INICIO, tzinfo=agora.tzinfo)
        fim = datetime.combine(d, HORA_FIM, tzinfo=agora.tzinfo)
        if i == 0 and inicio <= agora < fim:
            return agora
        if inicio > agora:
            return inicio
    return None


def decidir(agora: datetime, calendario: Dict[str, dict]) -> Decisao:
    """Aplica as três regras a `agora` (datetime com fuso) e devolve a decisão."""
    motivos = []
    if agora.weekday() not in DIAS_UTEIS:
        motivos.append(f"fim de semana ({NOMES_DIA[agora.weekday()]})")
    if not (HORA_INICIO <= agora.time() < HORA_FIM):
        motivos.append(f"fora do horário ({agora.strftime('%H:%M')}, janela "
                       f"{HORA_INICIO:%H:%M} a {HORA_FIM:%H:%M})")
    abertos = carrinhos_abertos(calendario, agora.date())
    if abertos:
        motivos.append("carrinho aberto: " + ", ".join(abertos))
    if not motivos:
        return Decisao(True)
    return Decisao(False, motivos, proxima_abertura(agora, calendario))


def carregar_calendario() -> Dict[str, dict]:
    """Calendário de LFs pela fonte de produção (tabela, com fallback para o yaml).

    Vazio vira aviso, não trava: a regra de horário continua valendo e o operador vê
    no resumo que o carrinho não foi conferido.
    """
    v2 = Path(__file__).resolve().parents[1]
    if str(v2) not in sys.path:
        sys.path.insert(0, str(v2))
    os.environ.setdefault("LAUNCHES_SOURCE", "table")
    from src.core.launches import load_launches  # noqa: E402  (import tardio: driver de banco)
    cal = load_launches() or {}
    if not cal:
        print("[janela] AVISO: calendário de LFs vazio; carrinho não conferido.", file=sys.stderr)
    return cal


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agora", help="instante a julgar, ISO (default: agora, em America/Sao_Paulo)")
    ap.add_argument("--sem-calendario", action="store_true", help="ignora o carrinho (só dia e hora)")
    a = ap.parse_args()

    agora = datetime.fromisoformat(a.agora) if a.agora else datetime.now(FUSO)
    if agora.tzinfo is None:
        agora = agora.replace(tzinfo=FUSO)
    agora = agora.astimezone(FUSO)
    calendario = {} if a.sem_calendario else carregar_calendario()

    d = decidir(agora, calendario)
    linhas = [f"aberta={'true' if d.aberta else 'false'}", f"motivo={d.motivo}",
              f"proxima={d.proxima.isoformat() if d.proxima else ''}"]
    print("\n".join(linhas))
    saida = os.environ.get("GITHUB_OUTPUT")
    if saida:
        with open(saida, "a", encoding="utf-8") as f:
            f.write("\n".join(linhas) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

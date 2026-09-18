#!/usr/bin/env python3
"""Janela de deploy: decide se o tráfego real pode andar AGORA.

Substitui o clique humano nos environments do GitHub por um freio de calendário, que
é o que o padrão de entrega progressiva usa: o gate (progression_gate.py) responde
"pode?" pelos números; esta janela responde "é hora?".

Regras (fuso America/Sao_Paulo):
  1. dia útil, de segunda a sexta;
  2. das 09:00 às 18:00.

O carrinho aberto deixou de fechar a janela em 18/09/2026 (decisão do Ramon): o gate e o
vigia já seguram um degrau ruim, e um lançamento com sete dias de carrinho travava uma
correção urgente por uma semana inteira.

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
from datetime import datetime, time, timedelta
from typing import List, Optional
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


def proxima_abertura(agora: datetime, horizonte_dias: int = 90) -> Optional[datetime]:
    """Primeiro instante >= agora em que a janela está aberta (ou None dentro do horizonte)."""
    for i in range(horizonte_dias + 1):
        d = agora.date() + timedelta(days=i)
        if d.weekday() not in DIAS_UTEIS:
            continue
        inicio = datetime.combine(d, HORA_INICIO, tzinfo=agora.tzinfo)
        fim = datetime.combine(d, HORA_FIM, tzinfo=agora.tzinfo)
        if i == 0 and inicio <= agora < fim:
            return agora
        if inicio > agora:
            return inicio
    return None


def decidir(agora: datetime) -> Decisao:
    """Aplica as duas regras a `agora` (datetime com fuso) e devolve a decisão."""
    motivos = []
    if agora.weekday() not in DIAS_UTEIS:
        motivos.append(f"fim de semana ({NOMES_DIA[agora.weekday()]})")
    if not (HORA_INICIO <= agora.time() < HORA_FIM):
        motivos.append(f"fora do horário ({agora.strftime('%H:%M')}, janela "
                       f"{HORA_INICIO:%H:%M} a {HORA_FIM:%H:%M})")
    if not motivos:
        return Decisao(True)
    return Decisao(False, motivos, proxima_abertura(agora))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agora", help="instante a julgar, ISO (default: agora, em America/Sao_Paulo)")
    a = ap.parse_args()

    agora = datetime.fromisoformat(a.agora) if a.agora else datetime.now(FUSO)
    if agora.tzinfo is None:
        agora = agora.replace(tzinfo=FUSO)
    agora = agora.astimezone(FUSO)

    d = decidir(agora)
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

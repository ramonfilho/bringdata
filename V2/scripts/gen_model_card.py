#!/usr/bin/env python3
"""
CLI fino do gerador de model card. Monta a entrada do MODEL_CHANGELOG a partir
de um run do MLflow (fatos preenchidos sozinhos) e opcionalmente grava no topo.

Uso:
  python V2/scripts/gen_model_card.py <run_id>              # imprime o markdown
  python V2/scripts/gen_model_card.py <run_id> --append     # grava no changelog
  python V2/scripts/gen_model_card.py <run_id> --name "RF + feature selection" \
      --decision "CANDIDATO — aguardando canário."

A lógica vive em src/model/model_card.py; este arquivo é só a casca de linha de comando.
"""
import argparse
import sys
from pathlib import Path

# V2/ no path para importar src.model.model_card
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.model.model_card import generate_card, append_to_changelog  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Gera a entrada do MODEL_CHANGELOG a partir de um run MLflow.")
    ap.add_argument("run_id", help="run_id do MLflow (ex: 1f0f0a71061648368fc29cb58ab0cbd0)")
    ap.add_argument("--append", action="store_true", help="grava a entrada no topo do MODEL_CHANGELOG.md")
    ap.add_argument("--name", default=None, help="nome curto do modelo (default: derivado do split)")
    ap.add_argument("--decision", default=None, help="linha de decisão (default: derivada do status)")
    args = ap.parse_args()

    md = generate_card(args.run_id, decision=args.decision, name=args.name)
    print(md)
    if args.append:
        p = append_to_changelog(md)
        print(f"\n[gravado no topo de {p}]", file=sys.stderr)


if __name__ == "__main__":
    main()

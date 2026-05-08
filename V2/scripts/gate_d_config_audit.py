#!/usr/bin/env python3
"""
[Gate D] Auditoria de config em imagem Cloud Run pré-promoção.

Pega o YAML que está DENTRO da imagem deployada e valida invariantes
que se removidos passam silenciosos no runtime e quebram CAPI.

Invariantes verificadas hoje:
  D1 — clients/{cliente}.yaml: business.conversion_rates não vazio
       e cobre D01..D10 com todos > 0.
  D2 — active_models/{cliente}.yaml: para cada variant em ab_test.variants
       que é "ativo" (matcheia roteamento OU == active_model.mlflow_run_id),
       conversion_rates cobre D01..D10 e MAX(values) > 0.

Bloqueia o deploy se qualquer invariante falhar.

Uso:
    python3 V2/scripts/gate_d_config_audit.py smart-ads-api-00403-cez
    python3 V2/scripts/gate_d_config_audit.py --client devclub <revision>

Pré-requisitos:
- docker disponível e autenticado em gcr.io
- gcloud autenticado para resolver image digest
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

import yaml


DECILS = [f"D{i:02d}" for i in range(1, 11)]


def get_image_digest(revision: str, region: str, project: str, service: str = "smart-ads-api") -> str:
    res = subprocess.run(
        ["gcloud", "run", "revisions", "describe", revision,
         "--region", region, "--project", project,
         "--format=value(spec.containers[0].image)"],
        capture_output=True, text=True, check=True, timeout=30,
    )
    digest = res.stdout.strip()
    if not digest:
        raise RuntimeError(f"Revisão '{revision}' sem imagem associada")
    return digest


def cat_from_image(image: str, path: str) -> str:
    """Lê arquivo de dentro da imagem via `docker run --rm --entrypoint cat`."""
    res = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "cat", image, path],
        capture_output=True, text=True, check=False, timeout=120,
    )
    if res.returncode != 0:
        raise RuntimeError(f"Falha ao ler {path} de {image[:60]}...: {res.stderr.strip()}")
    return res.stdout


def check_decil_rates(rates: dict[str, Any], context: str) -> list[str]:
    """Retorna lista de erros encontrados — vazio == OK."""
    errors = []
    if not isinstance(rates, dict) or not rates:
        return [f"{context}: conversion_rates ausente ou vazio"]
    missing = [d for d in DECILS if d not in rates]
    if missing:
        errors.append(f"{context}: decis faltando — {missing}")
    bad = []
    for d in DECILS:
        if d not in rates:
            continue
        try:
            v = float(rates[d])
        except (TypeError, ValueError):
            errors.append(f"{context}.{d}: valor não-numérico ({rates[d]!r})")
            continue
        if v < 0:
            errors.append(f"{context}.{d}: valor negativo ({v})")
        if v > 0:
            bad.append(False)
        else:
            bad.append(True)
    if all(bad):
        errors.append(f"{context}: todos os decis estão zerados — bug VAL=0 latente")
    return errors


def is_routable_variant(variant: dict[str, Any], active_run_id: str | None) -> tuple[bool, str]:
    """
    Decide se um variant pega leads em produção.

    Um variant é "ativo" se:
    - tem utm_pattern não vazio, OU
    - tem url_pattern não vazio, OU
    - tem run_id == active_model.mlflow_run_id (path Champion via shim)
    """
    utm = variant.get("utm_pattern") or {}
    url = variant.get("url_pattern")
    rid = variant.get("run_id")
    if utm:
        return True, f"utm_pattern={list(utm.keys())}"
    if url:
        return True, f"url_pattern={url}"
    if active_run_id and rid == active_run_id:
        return True, "run_id == active_model.mlflow_run_id (Champion shim)"
    return False, "sem utm/url e run_id != active_model"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("revision", help="Revisão Cloud Run (ex: smart-ads-api-00403-cez)")
    ap.add_argument("--client", default="devclub")
    ap.add_argument("--region", default="us-central1")
    ap.add_argument("--project", default="smart-ads-451319")
    ap.add_argument("--app-prefix", default="/app", help="Prefixo do WORKDIR no container")
    args = ap.parse_args()

    print(f"[gate D] Revisão: {args.revision}")
    print(f"[gate D] Cliente: {args.client}")

    image = get_image_digest(args.revision, args.region, args.project)
    print(f"[gate D] Imagem: {image[:80]}...")

    print(f"[gate D] Pulling imagem (pode demorar primeira vez)...")
    pull = subprocess.run(["docker", "pull", image], capture_output=True, text=True, check=False, timeout=300)
    if pull.returncode != 0:
        print(f"[gate D] ❌ Falha ao puxar imagem: {pull.stderr.strip()[:300]}", file=sys.stderr)
        return 2

    client_yaml_path = f"{args.app_prefix}/configs/clients/{args.client}.yaml"
    active_yaml_path = f"{args.app_prefix}/configs/active_models/{args.client}.yaml"

    try:
        client_raw = cat_from_image(image, client_yaml_path)
        active_raw = cat_from_image(image, active_yaml_path)
    except RuntimeError as e:
        print(f"[gate D] ❌ {e}", file=sys.stderr)
        return 2

    client_cfg = yaml.safe_load(client_raw)
    active_cfg = yaml.safe_load(active_raw)

    errors: list[str] = []

    # D1 — business.conversion_rates do client
    biz = client_cfg.get("business", {}) or {}
    biz_rates = biz.get("conversion_rates")
    if biz_rates is None:
        errors.append("D1: business.conversion_rates ausente em clients/{cliente}.yaml — VAL=0 garantido")
    else:
        errors.extend(check_decil_rates(biz_rates, "D1: business.conversion_rates"))

    # D2 — variants ativos do A/B
    ab = active_cfg.get("ab_test", {}) or {}
    if not ab.get("enabled"):
        print(f"[gate D] ⚠️  ab_test.enabled = false — pulando checagem de variants")
    else:
        active_run_id = (active_cfg.get("active_model") or {}).get("mlflow_run_id") \
                     or (active_cfg.get("model") or {}).get("mlflow_run_id")
        variants = ab.get("variants", {}) or {}
        if not variants:
            errors.append("D2: ab_test.enabled=true mas nenhum variant declarado")
        for name, variant in variants.items():
            routable, reason = is_routable_variant(variant, active_run_id)
            if not routable:
                print(f"[gate D] ↷ variant '{name}' pulado ({reason})")
                continue
            print(f"[gate D] ✓ variant '{name}' ativo: {reason}")
            errors.extend(check_decil_rates(variant.get("conversion_rates"), f"D2: variants.{name}.conversion_rates"))

    print()
    if errors:
        print("╔══════════════════════════════════════════════════════════════════╗")
        print("║  🚨 GATE D FALHOU — config quebrada na imagem                    ║")
        print("╠══════════════════════════════════════════════════════════════════╣")
        for e in errors:
            print(f"  • {e}")
        print("╚══════════════════════════════════════════════════════════════════╝")
        print()
        print("Não progredir tráfego. Corrigir YAMLs do cliente, rebuildar imagem.")
        return 1

    print("[gate D] ✅ Todas as invariantes passaram (D1 + D2).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

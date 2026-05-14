"""
Gera baseline de "fração esperada de zero por coluna OHE" para cada modelo
ativo (Champion + Challenger). Usado pelo validador pós-encoding bloqueador
em `core/feature_validator.py` (item T1-16 do PLANO_SAFEGUARD).

Fonte: `distribuicoes_esperadas.json` do MLflow run de cada modelo. Para cada
feature categórica pré-OHE registrada no treino, calcula a fração esperada
de cada categoria. Aplica o mesmo regex de normalização do encoding pra
construir o nome final da coluna OHE.

Exemplo:
    feature pré-OHE = 'Source'
    categorical no treino = {'facebook-ads': 0.8989, 'google-ads': 0.0976, 'outros': 0.0035}

    → coluna 'Source_facebook_ads': expected_nonzero_rate = 0.8989
    → coluna 'Source_google_ads':   expected_nonzero_rate = 0.0976
    → coluna 'Source_outros':       expected_nonzero_rate = 0.0035

Em runtime, o validador compara (df[col] != 0).mean() vs expected_nonzero_rate;
se a fração observada for muito menor que a esperada, levanta antes de scorear
(impede que o modelo receba feature zerada em massa).

Output: configs/feature_zero_baselines/{run_id}.json — uma entrada por modelo
ativo, lida pelo validator em runtime via o `mlflow_run_id` da variante.

Uso:
    python -m V2.scripts.generate_feature_zero_baselines           # gera pra todas variantes em active_models/devclub.yaml
    python -m V2.scripts.generate_feature_zero_baselines --run-id <id>  # gera só pra esse run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MLRUNS_DIR = REPO_ROOT / 'mlruns'
CONFIGS_DIR = REPO_ROOT / 'configs'
OUTPUT_DIR = CONFIGS_DIR / 'feature_zero_baselines'

# Regex que o encoding aplica em `apply_encoding` (encoding.py:296-298).
# Mantemos sincronizado pra que o nome OHE construído aqui bate com o do runtime.
_REGEX_NORMALIZE = re.compile(r'[^A-Za-z0-9_]')
_REGEX_DOUBLE_UNDERSCORE = re.compile(r'_+')


def _normalize_col(name: str) -> str:
    s = _REGEX_NORMALIZE.sub('_', str(name))
    s = _REGEX_DOUBLE_UNDERSCORE.sub('_', s).strip('_')
    return s


def _load_distribuicoes(run_id: str) -> Optional[dict]:
    """Carrega distribuicoes_esperadas.json de um MLflow run.

    Tenta dois caminhos (raiz de artifacts + subdir model/) — espelha o
    fallback que `core/medium.py:_load_valid_categories` usa.
    """
    candidates = [
        MLRUNS_DIR / '1' / run_id / 'artifacts' / 'distribuicoes_esperadas.json',
        MLRUNS_DIR / '1' / run_id / 'artifacts' / 'model' / 'distribuicoes_esperadas.json',
    ]
    for path in candidates:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    return None


def build_baselines_for_run(run_id: str, model_label: str = '') -> dict:
    """Gera o dict de baselines para um modelo, lendo do MLflow run.

    Retorna estrutura no formato:
        {
            "generated_at": "YYYY-MM-DD",
            "mlflow_run_id": "...",
            "model_label": "champion_jan30",
            "source": "distribuicoes_esperadas.json[categorical]",
            "baselines": {
                "Source_facebook_ads": {
                    "feature": "Source",
                    "category": "facebook-ads",
                    "expected_nonzero_rate": 0.8989,
                    "expected_zero_rate": 0.1011,
                },
                ...
            }
        }
    """
    dist = _load_distribuicoes(run_id)
    if dist is None:
        raise FileNotFoundError(
            f"distribuicoes_esperadas.json não encontrado para run_id={run_id}"
        )

    categorical = dist.get('categorical', {})
    if not categorical:
        raise ValueError(
            f"Run {run_id}: distribuicoes_esperadas.json não tem chave 'categorical'."
        )

    baselines: Dict[str, dict] = {}
    for feature_raw, category_dist in categorical.items():
        if not isinstance(category_dist, dict):
            continue

        feature_normalized = _normalize_col(feature_raw)
        for category_raw, frac in category_dist.items():
            if not isinstance(frac, (int, float)):
                continue
            # Nome final da coluna OHE: pandas faz `<feature>_<category>` antes do regex.
            ohe_raw = f"{feature_raw}_{category_raw}"
            ohe_col = _normalize_col(ohe_raw)
            nonzero_rate = float(frac)
            baselines[ohe_col] = {
                'feature': feature_normalized,
                'category': str(category_raw),
                'expected_nonzero_rate': round(nonzero_rate, 6),
                'expected_zero_rate': round(1.0 - nonzero_rate, 6),
            }

    return {
        'generated_at': date.today().isoformat(),
        'mlflow_run_id': run_id,
        'model_label': model_label or '',
        'source': 'distribuicoes_esperadas.json[categorical]',
        'baselines': baselines,
    }


def _load_active_runs() -> List[tuple]:
    """Lê active_models/devclub.yaml e retorna [(run_id, label), ...]
    para active_model + cada variante A/B ativa."""
    active_yaml = CONFIGS_DIR / 'active_models' / 'devclub.yaml'
    with open(active_yaml) as f:
        cfg = yaml.safe_load(f)

    runs: List[tuple] = []
    active = cfg.get('active_model', {})
    if active.get('mlflow_run_id'):
        runs.append((active['mlflow_run_id'], 'active_model'))

    ab = cfg.get('ab_test') or {}
    if ab.get('enabled'):
        for name, variant in (ab.get('variants') or {}).items():
            if variant.get('run_id'):
                runs.append((variant['run_id'], name))

    # Dedup mantendo a primeira label encontrada
    seen = set()
    out = []
    for run_id, label in runs:
        if run_id not in seen:
            seen.add(run_id)
            out.append((run_id, label))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--run-id', help='Gerar baseline só desse run (default: todos os ativos em active_models)')
    parser.add_argument('--output-dir', default=str(OUTPUT_DIR),
                        help='Diretório de saída (default: configs/feature_zero_baselines/)')
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.run_id:
        targets = [(args.run_id, '')]
    else:
        targets = _load_active_runs()
        if not targets:
            print("Nenhum modelo ativo encontrado em active_models/devclub.yaml", file=sys.stderr)
            return 1

    print(f"Gerando baselines para {len(targets)} modelo(s):")
    for run_id, label in targets:
        try:
            payload = build_baselines_for_run(run_id, model_label=label)
        except FileNotFoundError as e:
            print(f"  [SKIP] {label or run_id[:8]}: {e}")
            continue
        except Exception as e:
            print(f"  [ERRO] {label or run_id[:8]}: {type(e).__name__}: {e}")
            continue

        out_path = output_dir / f"{run_id}.json"
        with open(out_path, 'w') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"  [OK]   {label or run_id[:8]}: {len(payload['baselines'])} colunas → {out_path.relative_to(REPO_ROOT)}")

    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""
validate_parity_snapshots.py

Valida paridade de comportamento do pipeline de treino antes e depois
de uma migração de componente.

Uso:
  # 1. Antes de migrar — gera baseline (commitar antes de tocar código):
  python scripts/validate_parity_snapshots.py --generate-golden

  # 2. Após migrar — valida contra baseline:
  python scripts/validate_parity_snapshots.py --validate

  # 3. Comparar dois diretórios diretamente:
  python scripts/validate_parity_snapshots.py --compare-dirs tests/fixtures/golden tests/fixtures/current
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
FIXTURES    = ROOT / 'tests' / 'fixtures'
GOLDEN_DIR  = FIXTURES / 'golden'
CURRENT_DIR = FIXTURES / 'current'

# ---------------------------------------------------------------------------
# Invariantes por snapshot
# critical=True → falha bloqueia o commit; False → aviso apenas
# ---------------------------------------------------------------------------
SNAPSHOTS = {
    'snapshot_utm_input': {
        'description': 'Saída Célula 8 — feature removal (entrada do UTM)',
        'check_rows': True,
        'check_cols': True,
        'distributions': [],
        'critical': True,   # mudança aqui = preprocessing tocou coluna errada
    },
    'snapshot_utm_output': {
        'description': 'Saída UTM unification',
        'check_rows': True,
        'check_cols': True,
        'distributions': ['Source', 'Term'],
        'critical': True,
    },
    'snapshot_medium_output': {
        'description': 'Saída Medium unification',
        'check_rows': True,
        'check_cols': True,
        'distributions': ['Medium'],
        'critical': True,
    },
    'snapshot_fe_input': {
        'description': 'Entrada Feature Engineering — pós-cutoff + matching',
        'check_rows': True,   # row count aqui = tamanho do dataset pós-cutoff ← CRÍTICO
        'check_cols': True,
        'distributions': ['target'],
        'critical': True,
    },
    'snapshot_fe_output': {
        'description': 'Saída Feature Engineering',
        'check_rows': True,
        'check_cols': True,
        'distributions': [],
        'critical': False,
    },
    'snapshot_encoding_output': {
        'description': 'Saída Encoding — features finais do modelo',
        'check_rows': True,
        'check_cols': True,   # feature count e nomes devem ser idênticos
        'distributions': [],
        'critical': True,
    },
}

ROW_TOLERANCE  = 0.005   # 0.5% de tolerância em número de linhas
DIST_TOLERANCE = 0.02    # 2pp de tolerância em distribuições de categorias


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_pipeline_with_snapshots(output_dir: Path) -> None:
    """Roda o pipeline com --capture-parity-snapshots e copia resultados."""
    print('  Rodando pipeline com --capture-parity-snapshots...')
    result = subprocess.run(
        [
            sys.executable, '-m', 'V2.src.train_pipeline',
            '--no-api-data', '--use-cached-data',
            '--capture-parity-snapshots',
        ],
        capture_output=True, text=True,
        cwd=ROOT.parent,
    )
    if result.returncode != 0:
        print('  ERRO no pipeline:')
        print(result.stderr[-3000:])
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for pkl in FIXTURES.glob('snapshot_*.pkl'):
        shutil.copy2(pkl, output_dir / pkl.name)
        saved += 1

    if saved == 0:
        print('  ERRO: nenhum snapshot encontrado em tests/fixtures/.')
        print('  Verifique se --capture-parity-snapshots está implementado no pipeline.')
        sys.exit(1)

    print(f'  {saved} snapshots salvos em {output_dir.relative_to(ROOT)}')


def compare_snapshots(golden_dir: Path, current_dir: Path) -> bool:
    """Compara golden vs current. Retorna True se tudo OK."""
    all_ok    = True
    failures  = []
    warnings  = []

    print(f'  Golden:  {golden_dir.relative_to(ROOT)}')
    print(f'  Atual:   {current_dir.relative_to(ROOT)}')
    print()

    for name, cfg in SNAPSHOTS.items():
        golden_path  = golden_dir  / f'{name}.pkl'
        current_path = current_dir / f'{name}.pkl'

        if not golden_path.exists():
            print(f'  ⚠️   {name}: golden ausente — pule ou gere o golden primeiro')
            continue
        if not current_path.exists():
            print(f'  ❌  {name}: snapshot atual ausente')
            failures.append(name)
            all_ok = False
            continue

        g = pd.read_pickle(golden_path)
        c = pd.read_pickle(current_path)
        issues = []

        # 1. Row count
        if cfg['check_rows']:
            diff_pct = abs(len(g) - len(c)) / max(len(g), 1)
            if diff_pct > ROW_TOLERANCE:
                issues.append(
                    f'linhas: golden={len(g):,}  atual={len(c):,}'
                    f'  (Δ={abs(len(g)-len(c)):,}, {diff_pct:.1%})'
                )

        # 2. Column set
        if cfg['check_cols']:
            g_cols = set(g.columns)
            c_cols = set(c.columns)
            only_g = g_cols - c_cols
            only_c = c_cols - g_cols
            if only_g:
                issues.append(f'colunas removidas vs golden: {sorted(only_g)}')
            if only_c:
                issues.append(f'colunas adicionadas vs golden: {sorted(only_c)}')

        # 3. Distribuições de categorias
        for col in cfg.get('distributions', []):
            if col not in g.columns or col not in c.columns:
                continue
            g_vc = g[col].value_counts(normalize=True)
            c_vc = c[col].value_counts(normalize=True)
            for val in set(g_vc.index) | set(c_vc.index):
                diff = abs(g_vc.get(val, 0) - c_vc.get(val, 0))
                if diff > DIST_TOLERANCE:
                    issues.append(
                        f'{col}={val!r}: golden={g_vc.get(val,0):.1%}'
                        f'  atual={c_vc.get(val,0):.1%}'
                    )

        # Resultado
        if issues:
            marker = '🔴 CRÍTICO' if cfg['critical'] else '🟡 AVISO  '
            print(f'  {marker}  {name}')
            print(f'            {cfg["description"]}')
            for issue in issues:
                print(f'            → {issue}')
            if cfg['critical']:
                all_ok = False
                failures.append(name)
            else:
                warnings.append(name)
        else:
            print(f'  ✅ OK       {name}')

    # Resumo
    print()
    print('─' * 65)
    if all_ok and not warnings:
        print('✅  PARIDADE CONFIRMADA — pode prosseguir com o commit.')
    elif all_ok and warnings:
        print(f'⚠️   PARIDADE COM AVISOS ({len(warnings)}) — investigar antes de commitar.')
        print(f'    Avisos: {warnings}')
    else:
        print(f'❌  REGRESSÃO DETECTADA — NÃO commitar esta migração.')
        print(f'    Falhas críticas: {failures}')
        if warnings:
            print(f'    Avisos: {warnings}')
    print('─' * 65)

    return all_ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Valida paridade de comportamento do pipeline de treino'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--generate-golden', action='store_true',
        help='Gera snapshots baseline. Rodar ANTES de iniciar a migração e commitar.',
    )
    group.add_argument(
        '--validate', action='store_true',
        help='Valida pipeline atual contra golden. Rodar APÓS implementar o componente.',
    )
    group.add_argument(
        '--compare-dirs', nargs=2, metavar=('GOLDEN', 'CURRENT'),
        help='Compara dois diretórios de snapshots diretamente (sem rodar o pipeline).',
    )
    args = parser.parse_args()

    if args.generate_golden:
        print('Gerando golden snapshots (baseline pré-migração)...')
        if GOLDEN_DIR.exists():
            shutil.rmtree(GOLDEN_DIR)
        run_pipeline_with_snapshots(GOLDEN_DIR)
        print()
        print('✅  Golden gerado.')
        print(f'   Próximo passo: commitar {GOLDEN_DIR.relative_to(ROOT)} antes de migrar.')

    elif args.validate:
        if not GOLDEN_DIR.exists() or not list(GOLDEN_DIR.glob('snapshot_*.pkl')):
            print('ERRO: golden não encontrado. Rode --generate-golden primeiro.')
            sys.exit(1)
        print('Gerando snapshots do pipeline atual...')
        if CURRENT_DIR.exists():
            shutil.rmtree(CURRENT_DIR)
        run_pipeline_with_snapshots(CURRENT_DIR)
        print()
        print('Comparando contra golden...')
        ok = compare_snapshots(GOLDEN_DIR, CURRENT_DIR)
        sys.exit(0 if ok else 1)

    elif args.compare_dirs:
        golden_dir  = Path(args.compare_dirs[0])
        current_dir = Path(args.compare_dirs[1])
        ok = compare_snapshots(golden_dir, current_dir)
        sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()

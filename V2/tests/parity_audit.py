"""
Audit de paridade treino × produção.

Carrega os snapshots gerados por train_pipeline.py --capture-parity-snapshots
e compara o output das implementações de treino e produção sobre o mesmo input.

Uso:
    cd bring_data/
    python V2/tests/parity_audit.py [--function utm|medium|fe|encoding|all]

Pré-requisito:
    python -m V2.src.train_pipeline --capture-parity-snapshots

Output:
    Para cada função: divergências coluna a coluna com exemplos de valores.
"""

import sys
import os
import argparse
import pandas as pd
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def _load(name: str) -> pd.DataFrame:
    path = os.path.join(FIXTURES, f'{name}.pkl')
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Snapshot '{name}.pkl' não encontrado.\n"
            "Execute: python -m V2.src.train_pipeline --capture-parity-snapshots"
        )
    return pd.read_pickle(path)


def _compare(df_treino: pd.DataFrame, df_prod: pd.DataFrame, label: str) -> bool:
    """Compara dois DataFrames coluna a coluna. Retorna True se idênticos."""
    print(f"\n{'='*65}")
    print(f"  {label}")
    print(f"{'='*65}")
    print(f"  Treino  : {df_treino.shape[0]:,} linhas × {df_treino.shape[1]} colunas")
    print(f"  Produção: {df_prod.shape[0]:,} linhas × {df_prod.shape[1]} colunas")

    cols_so_treino = set(df_treino.columns) - set(df_prod.columns)
    cols_so_prod   = set(df_prod.columns)   - set(df_treino.columns)

    if cols_so_treino:
        print(f"\n  [!] Colunas só no treino  ({len(cols_so_treino)}): {sorted(cols_so_treino)}")
    if cols_so_prod:
        print(f"\n  [!] Colunas só na produção ({len(cols_so_prod)}): {sorted(cols_so_prod)}")

    cols_comuns = sorted(set(df_treino.columns) & set(df_prod.columns))
    divergencias = []

    for col in cols_comuns:
        s_t = df_treino[col].reset_index(drop=True)
        s_p = df_prod[col].reset_index(drop=True)
        n = min(len(s_t), len(s_p))
        s_t, s_p = s_t.iloc[:n], s_p.iloc[:n]

        try:
            if s_t.dtype == object or s_p.dtype == object:
                diff_mask = s_t.astype(str) != s_p.astype(str)
            else:
                diff_mask = ~np.isclose(
                    pd.to_numeric(s_t, errors='coerce').fillna(0),
                    pd.to_numeric(s_p, errors='coerce').fillna(0),
                    equal_nan=True
                )
        except Exception:
            diff_mask = s_t.astype(str) != s_p.astype(str)

        n_diff = diff_mask.sum()
        if n_diff > 0:
            divergencias.append((col, n_diff, 100 * n_diff / n, diff_mask, s_t, s_p))

    if not divergencias and not cols_so_treino and not cols_so_prod:
        print("\n  OK — outputs idênticos\n")
        return True

    if divergencias:
        print(f"\n  DIVERGÊNCIAS em {len(divergencias)} colunas comuns:\n")
        print(f"  {'Coluna':<45} {'# linhas':>10} {'%':>7}")
        print(f"  {'-'*45} {'-'*10} {'-'*7}")
        for col, n_diff, pct, *_ in sorted(divergencias, key=lambda x: -x[1]):
            print(f"  {col:<45} {n_diff:>10,} {pct:>6.1f}%")

        print()
        for col, n_diff, pct, diff_mask, s_t, s_p in sorted(divergencias, key=lambda x: -x[1])[:3]:
            exemplos = pd.DataFrame({
                'treino':   s_t[diff_mask].values[:5],
                'producao': s_p[diff_mask].values[:5],
            })
            print(f"  Exemplos — {col}:")
            print(exemplos.to_string(index=False))
            print()

    return False


# ---------------------------------------------------------------------------
# Audit por função
# ---------------------------------------------------------------------------

def audit_utm():
    """
    Migração concluída — arquivos antigos deletados.
    Smoke test: core/utm.unify_utm roda e normaliza Source/Term corretamente.
    """
    from V2.src.core.utm import unify_utm
    from V2.src.core.client_config import ClientConfig

    config   = ClientConfig.from_yaml(os.path.join(ROOT, 'V2', 'configs', 'clients', 'devclub.yaml'))
    df_input = _load('snapshot_utm_input')
    df_out   = unify_utm(df_input.copy(), config.utm)

    print(f"\n{'='*65}")
    print("  UTM — core/utm smoke test (migração concluída)")
    print(f"{'='*65}")
    print(f"  Input : {df_input.shape[0]:,} linhas × {df_input.shape[1]} colunas")

    ok = True
    if 'Source' in df_out.columns:
        sources = df_out['Source'].unique().tolist()
        print(f"  Source categorias: {sorted(str(s) for s in sources if s is not None)}")
        if any(s in (config.utm.source_to_outros or []) for s in sources):
            print("  [!] Valores de source_to_outros ainda presentes no output")
            ok = False
    if ok:
        print("\n  OK — UTM normalizado\n")
    return ok


def audit_medium():
    from V2.src.data_processing.medium_training import extrair_publico_medium
    from V2.src.data_processing.medium_production_training import unificar_medium_para_producao
    from V2.src.data_processing.medium_unification import unify_medium_columns

    df_input = _load('snapshot_medium_input')
    n_bruto  = df_input['Medium'].nunique() if 'Medium' in df_input.columns else 0

    df_step1, _ = extrair_publico_medium(df_input.copy())
    df_treino   = unificar_medium_para_producao(df_step1, n_bruto=n_bruto)
    df_prod     = unify_medium_columns(df_input.copy())
    return _compare(df_treino, df_prod,
                    "Medium — treino (extrair + unificar_para_producao) vs produção (unify_medium_columns)")


def audit_fe():
    """
    Migração concluída — arquivo antigo deletado.
    Smoke test: core/feature_engineering.create_features roda e produz colunas esperadas.
    """
    from V2.src.core.feature_engineering import create_features
    from V2.src.core.client_config import ClientConfig

    config   = ClientConfig.from_yaml(os.path.join(ROOT, 'V2', 'configs', 'clients', 'devclub.yaml'))
    df_input = _load('snapshot_fe_input')
    df_out   = create_features(df_input.copy(), config.feature)

    expected = {'dia_semana', 'nome_comprimento', 'nome_tem_sobrenome', 'telefone_comprimento'}
    missing  = expected - set(df_out.columns)

    print(f"\n{'='*65}")
    print("  FE — core/feature_engineering smoke test (migração concluída)")
    print(f"{'='*65}")
    print(f"  Input : {df_input.shape[0]:,} linhas × {df_input.shape[1]} colunas")
    print(f"  Output: {df_out.shape[0]:,} linhas × {df_out.shape[1]} colunas")

    if missing:
        print(f"\n  [!] Features ausentes: {sorted(missing)}")
        return False

    print("\n  OK — todas as features esperadas presentes\n")
    return True


def audit_encoding():
    """
    [T1-7] Parity audit de encoding — comparação coluna-a-coluna contra snapshot.

    Snapshot regenerado em 21/04/2026 com os parâmetros exatos do modelo mar24
    em produção (67,457 registros, split temporal_leads, medium_strategy binary_top3).

    Smoke checks mantidos como segunda linha de defesa:
      - Ordinais encodadas como numéricas
      - Nenhum NaN no output
      - Nomes de coluna em snake_case
    """
    from V2.src.core.encoding import apply_encoding
    from V2.src.core.client_config import ClientConfig

    config     = ClientConfig.from_yaml(os.path.join(ROOT, 'V2', 'configs', 'clients', 'devclub.yaml'))
    df_input   = _load('snapshot_encoding_input')
    df_expect  = _load('snapshot_encoding_output')
    df_actual  = apply_encoding(df_input.copy(), config.encoding, artifacts={})

    ok_snap = _compare(df_expect, df_actual, "Encoding — snapshot (captura no treino) vs output atual")

    # Smoke checks adicionais
    ok_smoke = True

    ordinais_esperadas = {
        'Atualmente_qual_a_sua_faixa_salarial',
        'Qual_a_sua_idade',
        'dia_semana',
    }
    ordinais_presentes = [c for c in df_actual.columns if any(o in c for o in ordinais_esperadas)]
    for col in ordinais_presentes:
        if df_actual[col].dtype == object:
            print(f"  [!] Ordinal '{col}' não foi encodada — dtype={df_actual[col].dtype}")
            ok_smoke = False

    nan_count = df_actual.isna().sum().sum()
    if nan_count > 0:
        print(f"  [!] {nan_count} NaN remanescentes no output")
        ok_smoke = False

    bad_cols = [c for c in df_actual.columns if any(ch in c for ch in ['?', ' ', '-', '.'])]
    if bad_cols:
        print(f"  [!] Colunas com caracteres especiais ({len(bad_cols)}): {bad_cols[:5]}")
        ok_smoke = False

    return ok_snap and ok_smoke


def audit_encoding_ab_variants():
    """
    [T1-15] Parity audit por variante A/B — cobre encoding_overrides.

    Cobre o gap V.1.2 do registro_erros_ml.md: audit_encoding tradicional
    testa só config.encoding padrão (artifacts={}, sem overrides), portanto
    não cobre Champion shim com encoding_overrides ordinal nem Challenger
    no contexto A/B. O bug do Cluster 5 (Champion sem encoding_overrides
    em A/B reativado, 29/abr–05/mai/2026) passou exatamente por esse gap.

    Itera sobre cada variante ativa em configs/active_models/{client}.yaml,
    aplica merge_encoding(base, variant.encoding_overrides) e roda
    apply_encoding sobre o snapshot.

    Comparação por variante (em ordem de severidade):
      1. Coluna-a-coluna contra snapshot snapshot_encoding_output_{variant}.pkl
         (capturado por V2/tests/capture_encoding_snapshots_ab.py).
         Falha de schema ou de valor bloqueia. Smoke checks abaixo viram
         second line of defense.
      2. Smoke checks: ordinais numéricas, sem NaN, nomes válidos.
         Rodam mesmo quando o snapshot por-variante está ausente.

    Limitação restante (T1-19): este audit não valida o output contra o
    feature_registry real de cada variante (que vive no MLflow do treino
    dela). Pra isso seria preciso baixar/cachear o registry e passar como
    artifacts={'feature_registry': variant_registry}.
    """
    from V2.src.core.encoding import apply_encoding, merge_encoding
    from V2.src.core.client_config import ClientConfig, ABTestConfig

    config = ClientConfig.from_yaml(
        os.path.join(ROOT, 'V2', 'configs', 'clients', 'devclub.yaml')
    )
    ab_yaml = os.path.join(ROOT, 'V2', 'configs', 'active_models', 'devclub.yaml')

    if not os.path.exists(ab_yaml):
        print("  [SKIP] active_models/devclub.yaml ausente — sem A/B configurado")
        return None

    ab = ABTestConfig.from_active_model_yaml(ab_yaml)
    if not ab.enabled:
        print("  [SKIP] ab_test.enabled=false — sem variantes pra auditar")
        return None
    if not ab.variants:
        print("  [!] ab_test.enabled=true mas nenhum variant declarado em variants:")
        return False

    df_input = _load('snapshot_encoding_input')
    overall_ok = True
    print(f"  Auditando {len(ab.variants)} variante(s) A/B...")

    ordinais_esperadas = {
        'Atualmente_qual_a_sua_faixa_salarial',
        'Qual_a_sua_idade',
        'dia_semana',
    }

    for variant_name, variant in ab.variants.items():
        eff_encoding = merge_encoding(config.encoding, variant.encoding_overrides)

        try:
            df_actual = apply_encoding(df_input.copy(), eff_encoding, artifacts={})
        except Exception as e:
            print(f"  [!] '{variant_name}' QUEBROU em apply_encoding: "
                  f"{type(e).__name__}: {str(e)[:200]}")
            overall_ok = False
            continue

        ok_variant = True

        # 0. Comparação coluna-a-coluna contra snapshot por-variante.
        # Se ausente: bootstrap — salva o output atual como baseline e segue.
        # Comparação real fica disponível a partir do próximo deploy nesta máquina.
        # (Cross-machine: snapshots são gitignored; cada ambiente bootstrappa o seu.)
        snapshot_path = os.path.join(
            FIXTURES, f'snapshot_encoding_output_{variant_name}.pkl'
        )
        if os.path.exists(snapshot_path):
            df_expect = pd.read_pickle(snapshot_path)
            ok_snap = _compare(
                df_expect, df_actual,
                f"Encoding A/B — '{variant_name}': snapshot vs output atual",
            )
            if not ok_snap:
                ok_variant = False
        else:
            df_actual.to_pickle(snapshot_path)
            print(f"  [BOOTSTRAP] '{variant_name}': snapshot ausente — output atual "
                  f"({df_actual.shape[0]:,}×{df_actual.shape[1]}) salvo como baseline em "
                  f"{os.path.basename(snapshot_path)}. Comparação real fica disponível "
                  "a partir do próximo deploy.")

        # 1. Ordinais devem virar numéricas (não dtype=object)
        ordinais_presentes = [
            c for c in df_actual.columns
            if any(o in c for o in ordinais_esperadas)
        ]
        for col in ordinais_presentes:
            if df_actual[col].dtype == object:
                print(f"  [!] '{variant_name}': ordinal '{col}' não foi encodada "
                      f"— dtype={df_actual[col].dtype}")
                ok_variant = False

        # 2. Sem NaN
        nan_count = int(df_actual.isna().sum().sum())
        if nan_count > 0:
            print(f"  [!] '{variant_name}': {nan_count} NaN remanescentes")
            ok_variant = False

        # 3. Nomes válidos
        bad_cols = [
            c for c in df_actual.columns
            if any(ch in c for ch in ['?', ' ', '-', '.'])
        ]
        if bad_cols:
            print(f"  [!] '{variant_name}': {len(bad_cols)} coluna(s) "
                  f"com caracteres especiais: {bad_cols[:3]}")
            ok_variant = False

        if ok_variant:
            n_ord = len(eff_encoding.ordinal_variables or {})
            print(f"  [OK] '{variant_name}': {df_actual.shape[1]} colunas, "
                  f"{n_ord} ordinais configuradas, "
                  f"{len(ordinais_presentes)} colunas ordinais encodadas")
        else:
            overall_ok = False

    return overall_ok


def _build_production_encoding_input(client_config, n_leads: int = 200) -> 'pd.DataFrame':
    """
    Constrói um DataFrame de leads reais do Railway PASSANDO pelo mesmo caminho
    que produção usa em runtime (`railway_lead_to_sheets_row`), depois aplica
    os passos core até logo ANTES do encoding.

    Por que existe (T1-19): o caminho de treino e o caminho de produção
    produzem inputs diferentes para o encoder. Auditar contra snapshot de
    treino gera falsos positivos para colunas que só são criadas em produção
    pelo `railway_mapping` (ex.: `interesse_programacao` derivada da chave
    JSONB `atracaoProfissao`). Esta função reproduz o caminho de produção
    fielmente.

    Sequência aplicada (espelho de `production_pipeline.preprocess()`):
        1. Fetch N leads recentes do Railway (com env vars RAILWAY_DB_*)
        2. Para cada lead: `railway_lead_to_sheets_row(lead, client_config)`
        3. Empilha em DataFrame
        4. `core.preprocessing.preprocess(df, ingestion, feature)`
        5. `core.utm.unify_utm(df, utm)`
        6. `core.medium.unify_medium(df, medium, artifacts=None)`  ← sem artifact aqui (audit é por-variante depois)
        7. `core.category_unification.unify_categories(df, category)`
        8. `core.feature_engineering.create_features(df, feature)`

    Retorna o DataFrame pronto pra entrar em `apply_encoding`.

    Levanta `RuntimeError` se env vars do Railway não estiverem disponíveis ou
    se o fetch retornar zero leads — falha alto pra não disfarçar bug do gate
    com input vazio.
    """
    import pandas as pd
    import json as _json

    # Env vars obrigatórias
    required_env = ['RAILWAY_DB_HOST', 'RAILWAY_DB_PORT', 'RAILWAY_DB_NAME',
                    'RAILWAY_DB_USER', 'RAILWAY_DB_PASSWORD']
    missing_env = [k for k in required_env if not os.environ.get(k)]
    if missing_env:
        # Tentar carregar do V2/.env como fallback
        env_path = os.path.join(ROOT, 'V2', '.env')
        if os.path.exists(env_path):
            for line in open(env_path).read().splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, _, v = line.partition('=')
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
            missing_env = [k for k in required_env if not os.environ.get(k)]
        if missing_env:
            raise RuntimeError(
                f"[T1-19] Env vars Railway ausentes: {missing_env}. "
                "Configurar V2/.env ou exportar manualmente antes de rodar schema_mlflow."
            )

    # Importar dependências
    try:
        import psycopg2
    except ImportError:
        raise RuntimeError("[T1-19] psycopg2 não disponível — instalar com `pip install psycopg2-binary`")

    from V2.api.railway_mapping import railway_lead_to_sheets_row
    from V2.src.core.preprocessing import preprocess as _preprocess
    from V2.src.core.utm import unify_utm
    from V2.src.core.medium import unify_medium
    from V2.src.core.category_unification import unify_categories
    from V2.src.core.feature_engineering import create_features

    # 1. Fetch leads recentes do Railway
    conn = psycopg2.connect(
        host=os.environ['RAILWAY_DB_HOST'],
        port=int(os.environ['RAILWAY_DB_PORT']),
        user=os.environ['RAILWAY_DB_USER'],
        password=os.environ['RAILWAY_DB_PASSWORD'],
        dbname=os.environ['RAILWAY_DB_NAME'],
    )
    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT id, data, "nomeCompleto", email, telefone, pesquisa, '
            'source, medium, campaign, content, term, '
            '"remoteIp", "userAgent", fbc, fbp, "pageUrl" '
            'FROM "Lead" '
            'WHERE pesquisa IS NOT NULL '
            'ORDER BY "createdAt" DESC '
            f'LIMIT {n_leads}'
        )
        col_names = [
            'id', 'data', 'nomeCompleto', 'email', 'telefone', 'pesquisa',
            'source', 'medium', 'campaign', 'content', 'term',
            'remoteIp', 'userAgent', 'fbc', 'fbp', 'pageUrl',
        ]
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        raise RuntimeError(
            f"[T1-19] Railway retornou 0 leads (n_leads={n_leads}). "
            "Sem input → gate não pode validar; falhando alto em vez de passar com snapshot vazio."
        )

    # 2. Aplicar railway_lead_to_sheets_row em cada lead
    sheets_rows = []
    for r in rows:
        lead = dict(zip(col_names, r))
        if isinstance(lead.get('pesquisa'), str):
            try:
                lead['pesquisa'] = _json.loads(lead['pesquisa'])
            except Exception:
                lead['pesquisa'] = {}
        elif lead.get('pesquisa') is None:
            lead['pesquisa'] = {}
        try:
            sheets_rows.append(railway_lead_to_sheets_row(lead, client_config=client_config))
        except Exception as e:
            # Lead malformado — pular individualmente, não derrubar o batch inteiro.
            print(f"  [T1-19 fetch] warning: lead {lead.get('email', '?')} pulado: {e}")

    df_raw = pd.DataFrame(sheets_rows)
    print(f"  [T1-19 fetch] {len(df_raw)} leads carregados do Railway via railway_mapping")

    # 3-7. Pipeline core (sequência idêntica à de production_pipeline.preprocess)
    df = _preprocess(df_raw, client_config.ingestion, client_config.feature)
    df = unify_utm(df, client_config.utm)
    if 'Medium' in df.columns:
        df = unify_medium(df, client_config.medium, artifacts=None)  # whitelist via frequência (modo treino) — audit per-variant não passa artifact aqui
    df = unify_categories(df, client_config.category)
    df = create_features(df, client_config.feature)

    print(f"  [T1-19 fetch] DataFrame pré-encoding: {df.shape[0]} linhas × {df.shape[1]} colunas")
    return df


def audit_schema_against_mlflow():
    """
    [T1-19] Valida schema do output do encoding contra o feature_registry real
    do MLflow para cada variante A/B ativa.

    Caminho de input: leads reais do Railway via `railway_lead_to_sheets_row`
    (mesmo caminho que produção usa em runtime). Não usa snapshot de treino —
    snapshot de treino e produção têm caminhos diferentes (treino não passa
    pelo railway_mapping), o que gerava falsos positivos para colunas
    derivadas de chaves JSONB do front (ex.: `interesse_programacao` derivada
    de `atracaoProfissao`).

    Cobre o caso onde o snapshot por-variante (T1-15) passa OK, mas o conjunto
    de colunas geradas pelo pipeline não bate com o que o modelo da variante
    espera consumir. Sintomas reais que isso detecta:
      - Refactor de category_unification que muda nomes de coluna OHE
        (ex.: 'genero_Masculino' → 'genero_masculino') quebra modelos antigos
        que ainda têm os nomes não-normalizados no feature_registry.
      - Treino novo que adiciona/remove features sem atualizar o feature_registry
        do modelo legado.
      - Encoding produz dtype object onde o modelo espera int/float.

    Para cada variante ativa:
      1. Lê o feature_registry.json do mlflow_run_id (com fallback model/ subdir).
      2. Aplica encoding SEM alinhamento de registry (artifacts={}), pegando
         o output "cru" — não enche colunas faltantes com 0, não reordena.
      3. Compara contra registry['model_input_features']['ordered_list']:
         - Colunas no registry mas ausentes do output → ERRO (modelo espera mas pipeline não produz; bug deploy-bloqueador).
         - Colunas no output mas ausentes do registry → WARNING (modelo ignora; pode indicar drift de categorias mas não trava).
         - Dtypes divergentes contra registry['expected_dtypes'] → ERRO (modelo espera int mas recebe object, ou similar).
    """
    import json
    from V2.src.core.encoding import apply_encoding, merge_encoding
    from V2.src.core.client_config import ClientConfig, ABTestConfig

    config = ClientConfig.from_yaml(
        os.path.join(ROOT, 'V2', 'configs', 'clients', 'devclub.yaml')
    )
    ab_yaml = os.path.join(ROOT, 'V2', 'configs', 'active_models', 'devclub.yaml')

    if not os.path.exists(ab_yaml):
        print("  [SKIP] active_models/devclub.yaml ausente — sem A/B configurado")
        return None

    ab = ABTestConfig.from_active_model_yaml(ab_yaml)
    if not ab.enabled:
        print("  [SKIP] ab_test.enabled=false — sem variantes pra auditar")
        return None
    if not ab.variants:
        print("  [!] ab_test.enabled=true mas nenhum variant declarado")
        return False

    # Input do encoding: leads reais do Railway pelo mesmo caminho da produção.
    # Substituí o snapshot estático (treino) pra eliminar falso positivo
    # documentado na sessão de investigação 11/mai (T1-19).
    try:
        df_input = _build_production_encoding_input(config, n_leads=200)
    except RuntimeError as e:
        print(f"  [!] Não foi possível construir input de produção: {e}")
        return False

    # Colunas pré-OHE no batch (antes do encoding). Usado pra distinguir
    # missing crítico (feature inteira sumiu do pipeline) de missing amostral
    # (categoria específica não apareceu nesses N leads — ok, alinhamento
    # preenche com 0 em runtime). Normaliza nomes com o mesmo regex que o
    # encoding aplica (encoding.py:296-298) pra cruzar com nomes do registry.
    import re as _re
    def _normalize_col(name: str) -> str:
        s = _re.sub(r'[^A-Za-z0-9_]', '_', str(name))
        s = _re.sub(r'_+', '_', s).strip('_')
        return s
    pre_ohe_cols = {_normalize_col(c) for c in df_input.columns}
    overall_ok = True
    print(f"  Validando schema de {len(ab.variants)} variante(s) contra MLflow...")

    for variant_name, variant in ab.variants.items():
        run_id = variant.run_id
        # Localiza o feature_registry — tenta raiz de artifacts e model/ subdir
        # (mesmo padrão de core/medium.py:_load_valid_categories).
        candidates = [
            os.path.join(ROOT, 'V2', 'mlruns', '1', run_id, 'artifacts', 'feature_registry.json'),
            os.path.join(ROOT, 'V2', 'mlruns', '1', run_id, 'artifacts', 'model', 'feature_registry.json'),
        ]
        registry_path = next((p for p in candidates if os.path.exists(p)), None)
        if not registry_path:
            print(f"  [!] '{variant_name}' (run_id={run_id[:8]}): "
                  f"feature_registry.json não encontrado em mlruns/1/{run_id[:8]}/artifacts/")
            overall_ok = False
            continue

        with open(registry_path) as f:
            registry = json.load(f)

        expected_cols = registry.get('model_input_features', {}).get('ordered_list', [])
        expected_dtypes = registry.get('expected_dtypes', {})
        if not expected_cols:
            print(f"  [!] '{variant_name}': registry sem 'model_input_features.ordered_list'")
            overall_ok = False
            continue

        eff_encoding = merge_encoding(config.encoding, variant.encoding_overrides)

        # Encoding com artifacts={} = output cru, sem alinhamento ao registry.
        # É exatamente o que queremos comparar contra o registry esperado.
        try:
            df_actual = apply_encoding(df_input.copy(), eff_encoding, artifacts={})
        except Exception as e:
            print(f"  [!] '{variant_name}' QUEBROU em apply_encoding: "
                  f"{type(e).__name__}: {str(e)[:200]}")
            overall_ok = False
            continue

        actual_cols = set(df_actual.columns)
        expected_set = set(expected_cols)

        missing = sorted(expected_set - actual_cols)
        extras = sorted(actual_cols - expected_set)

        # Classificar missing em CRÍTICO vs AMOSTRAL:
        #   - CRÍTICO: feature pré-OHE inteira sumiu do pipeline (ex.: refactor renomeou,
        #              ou coluna foi removida). Bug deploy-bloqueador.
        #   - AMOSTRAL: feature pré-OHE existe no batch, mas essa categoria específica
        #              não apareceu nesses N leads. Não é bug — alinhamento ao registry
        #              em runtime preenche com 0 (passo 7 do apply_encoding).
        # Heurística: pra cada coluna do registry, tentar achar o prefixo (substring
        # antes do último valor) que existe como coluna pré-OHE no batch.
        def _classify_missing(reg_col: str) -> str:
            parts = reg_col.split('_')
            for i in range(len(parts), 0, -1):
                candidate = '_'.join(parts[:i])
                if candidate in pre_ohe_cols:
                    return 'amostral'
            return 'crítico'

        missing_critico = [c for c in missing if _classify_missing(c) == 'crítico']
        missing_amostral = [c for c in missing if _classify_missing(c) == 'amostral']

        ok_variant = True

        if missing_critico:
            print(f"\n  [ERRO] '{variant_name}' ({len(missing_critico)} colunas CRÍTICAS — feature pré-OHE inteira ausente do pipeline):")
            for col in missing_critico[:15]:
                print(f"    - {col}")
            if len(missing_critico) > 15:
                print(f"    ... +{len(missing_critico) - 15} colunas")
            ok_variant = False

        if missing_amostral:
            print(f"\n  [INFO] '{variant_name}' ({len(missing_amostral)} colunas AMOSTRAIS — categoria não apareceu nos {len(df_input)} leads do batch; runtime preenche com 0):")
            for col in missing_amostral[:8]:
                print(f"    - {col}")
            if len(missing_amostral) > 8:
                print(f"    ... +{len(missing_amostral) - 8} colunas")

        if extras:
            print(f"\n  [WARN] '{variant_name}' ({len(extras)} colunas no output mas IGNORADAS pelo modelo — possível drift de categoria nova):")
            for col in extras[:10]:
                print(f"    - {col}")
            if len(extras) > 10:
                print(f"    ... +{len(extras) - 10} colunas")

        # Dtype check — só para colunas que existem em ambos os lados.
        dtype_mismatches = []
        if expected_dtypes:
            cols_em_ambos = actual_cols & expected_set
            for col in cols_em_ambos:
                expected = expected_dtypes.get(col)
                actual = str(df_actual[col].dtype)
                if expected and not _dtypes_compatible(actual, expected):
                    dtype_mismatches.append((col, expected, actual))

        if dtype_mismatches:
            print(f"\n  [ERRO] '{variant_name}' ({len(dtype_mismatches)} colunas com dtype divergente):")
            for col, expected, actual in dtype_mismatches[:10]:
                print(f"    - {col}: registry esperava '{expected}', encoding produziu '{actual}'")
            if len(dtype_mismatches) > 10:
                print(f"    ... +{len(dtype_mismatches) - 10} colunas")
            ok_variant = False

        if ok_variant:
            print(f"  [OK] '{variant_name}' ({run_id[:8]}): {len(expected_cols)} colunas batem com registry, dtypes válidos")
        else:
            overall_ok = False

    return overall_ok


def _dtypes_compatible(actual: str, expected: str) -> bool:
    """
    Compatibilidade frouxa de dtypes — int8/int16/int32/int64 são equivalentes
    para fins de schema (pandas escolhe um conforme range dos dados), float32
    vs float64 idem. Object é o caso problemático: encoding deveria ter virado
    numérico mas ficou string.
    """
    a = actual.lower()
    e = expected.lower()
    if a == e:
        return True
    if 'int' in a and 'int' in e:
        return True
    if 'float' in a and 'float' in e:
        return True
    if a == 'bool' and 'int' in e:
        return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

AUDITS = {
    'utm':           audit_utm,
    'medium':        audit_medium,
    'fe':            audit_fe,
    'encoding':      audit_encoding,
    'encoding_ab':   audit_encoding_ab_variants,
    'schema_mlflow': audit_schema_against_mlflow,
}

def main():
    parser = argparse.ArgumentParser(description='Audit de paridade treino × produção')
    parser.add_argument(
        '--function',
        choices=[*AUDITS.keys(), 'all'],
        default='all',
        help='Função a auditar (default: all)'
    )
    args = parser.parse_args()
    targets = list(AUDITS.keys()) if args.function == 'all' else [args.function]

    resultados = {}
    for nome in targets:
        try:
            resultados[nome] = AUDITS[nome]()
        except FileNotFoundError as e:
            print(f"\n  [SKIP] {nome}: {e}")
            resultados[nome] = None

    print(f"\n{'='*65}")
    print("  RESUMO")
    print(f"{'='*65}")
    for nome, ok in resultados.items():
        status = {True: "OK", False: "DIVERGÊNCIA", None: "SKIP (snapshot ausente)"}.get(ok, "ERRO")
        print(f"  {nome:<12} {status}")
    print()


if __name__ == '__main__':
    main()

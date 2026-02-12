"""
Módulo para treino e registro do modelo - PIPELINE DE TREINO.

Reproduz a célula de modelagem do notebook DevClub.
Treina modelo RandomForest e salva artefatos.
"""

import pandas as pd
import numpy as np
import json
import joblib
import os
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
import sklearn
import logging
import mlflow
import mlflow.sklearn
from src.model.decil_thresholds import calcular_thresholds_decis, comparar_distribuicoes, atribuir_decis_batch

logger = logging.getLogger(__name__)

# Configurar MLflow
mlflow.set_tracking_uri("sqlite:///mlflow.db")
mlflow.set_experiment("devclub_lead_scoring")


def atualizar_business_config_com_recall(model_metadata: dict):
    """
    Atualiza api/business_config.py com taxas de conversão corrigidas pelo recall real.

    Lê as taxas observadas do model_metadata (decil_analysis), aplica o fator de correção
    calculado a partir do recall real, e atualiza o arquivo business_config.py.

    Args:
        model_metadata: Dict com metadata do modelo (deve conter recall_metrics e decil_analysis)
    """
    import re
    from pathlib import Path

    logger.info("\n ATUALIZANDO BUSINESS_CONFIG.PY COM RECALL REAL")

    # Extrair métricas de recall
    recall_metrics = model_metadata.get('recall_metrics', {})
    fator_correcao = recall_metrics.get('fator_correcao')
    recall = recall_metrics.get('recall')

    if not fator_correcao:
        logger.info("  Recall metrics não encontradas. Pulando atualização.")
        return

    logger.info(f" Recall real: {recall:.4f} ({recall*100:.2f}%)")
    logger.info(f" Fator de correção: {fator_correcao:.3f}x")

    # Calcular taxas corrigidas a partir do decil_analysis
    decil_analysis = model_metadata.get('decil_analysis', {})
    taxas_corrigidas = {}

    logger.info(f"\n Calculando taxas corrigidas:")
    logger.info(f"{'Decil':<6} | {'Observada':<10} | {'Corrigida':<10}")
    logger.info("-" * 35)

    for i in range(1, 11):
        decil_key = f"decil_{i}"
        decil_label = f"D{i}"

        if decil_key in decil_analysis:
            taxa_observada = decil_analysis[decil_key]['conversion_rate']
            taxa_corrigida = taxa_observada * fator_correcao
            taxas_corrigidas[decil_label] = taxa_corrigida

            logger.info(f"{decil_label:<6} | {taxa_observada*100:>8.2f}% | {taxa_corrigida*100:>8.2f}%")

    # Ler arquivo business_config.py
    config_path = Path(__file__).parent.parent.parent / "api" / "business_config.py"

    if not config_path.exists():
        logger.info(f" Arquivo não encontrado: {config_path}")
        return

    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Montar novo bloco CONVERSION_RATES
    novo_bloco = "CONVERSION_RATES = {\n"
    for i in range(1, 11):
        decil_label = f"D{i}"
        taxa = taxas_corrigidas.get(decil_label, 0.0)
        conversoes = decil_analysis[f"decil_{i}"]["conversions"]
        total_leads = decil_analysis[f"decil_{i}"]["total_leads"]
        taxa_obs = decil_analysis[f"decil_{i}"]["conversion_rate"]

        novo_bloco += f'    "{decil_label}": {taxa:.6f},   # {taxa*100:.2f}% | Corrigido de {taxa_obs*100:.2f}% (×{fator_correcao:.3f}) | {conversoes} conversões / {total_leads:,} leads\n'
    novo_bloco += "}"

    # Substituir bloco CONVERSION_RATES (não comentado)
    # Padrão: Linha que começa com CONVERSION_RATES (não com # CONVERSION_RATES)
    # Buscar de forma mais específica: início de linha + CONVERSION_RATES
    pattern = r'(?m)^CONVERSION_RATES\s*=\s*\{[^}]*\}'

    if re.search(pattern, content, re.DOTALL | re.MULTILINE):
        content_novo = re.sub(pattern, novo_bloco, content, count=1, flags=re.DOTALL | re.MULTILINE)

        # Salvar arquivo atualizado
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(content_novo)

        logger.info(f"\n business_config.py atualizado com sucesso!")
        logger.info(f"   Path: {config_path}")
        logger.info(f"   Taxas corrigidas automaticamente com recall real ({recall*100:.2f}%)")
    else:
        logger.info(f"  Padrão CONVERSION_RATES não encontrado no arquivo")


def registrar_features_e_modelo_devclub(
    dataset_devclub_encoded: pd.DataFrame,
    dataset_devclub_original: pd.DataFrame,
    save_files: bool = False,
    matching_method: str = 'email_only',
    custom_hyperparams: dict = None,
    split_method: str = 'temporal',
    set_active: bool = False,
    recall_metrics: dict = None,
    categorias_treino: dict = None,
    distribuicoes_treino: dict = None,
    missing_rates_baseline: dict = None
) -> dict:
    """
    Registra features e salva modelo DevClub para produção.

    Reproduz a lógica da célula de modelagem do notebook DevClub.

    Args:
        dataset_devclub_encoded: DataFrame V1 DevClub encodado
        dataset_devclub_original: DataFrame V1 DevClub original (com Data)
        save_files: Se True, salva arquivos locais em files/{timestamp}
        matching_method: Método de matching usado ('email_only', 'variantes', 'robusto')
        custom_hyperparams: Hiperparâmetros customizados do tuning (opcional)
        split_method: Método de split ('temporal' para 70% dos dias, 'stratified' para 70% dos registros)
        set_active: Se True, atualiza configs/active_model.yaml com este modelo (requer save_files=True)

    Returns:
        Dicionário com resultados do registro
    """
    # Iniciar MLflow run
    with mlflow.start_run():
        # Logar parâmetros do experimento
        mlflow.log_param("matching_method", matching_method)
        mlflow.log_param("save_files", save_files)

        # 1. PREPARAR DADOS E TREINAR MODELO FINAL
        logger.info("  Removendo a coluna Target")

        # Dataset encodado
        dataset_final = dataset_devclub_encoded.copy()

        # Dataset original para extrair datas
        dataset_original = dataset_devclub_original.copy()

        # Colunas a EXCLUIR do treinamento (não usar como features)
        colunas_excluir_treino = ['target']

        # Verificar quais colunas existem
        colunas_excluir_existentes = [col for col in colunas_excluir_treino if col in dataset_final.columns]

        # Preparar features e target
        X = dataset_final.drop(columns=colunas_excluir_existentes)
        y = dataset_final['target']

        # Limpar nomes das colunas
        X_clean = X.copy()
        X_clean.columns = X_clean.columns.str.replace('[^A-Za-z0-9_]', '_', regex=True)
        X_clean.columns = X_clean.columns.str.replace('__+', '_', regex=True)
        X_clean.columns = X_clean.columns.str.strip('_')

        # Reordenar features telefone_comprimento para ordem crescente DEPOIS da limpeza
        colunas_telefone = [col for col in X_clean.columns if col.startswith('telefone_comprimento_')]
        if colunas_telefone:
            colunas_telefone_ordenadas = sorted(colunas_telefone, key=lambda x: int(x.split('_')[-1]))
            outras_colunas = [col for col in X_clean.columns if not col.startswith('telefone_comprimento_')]

            # Encontrar posição das colunas telefone na ordem original
            primeira_pos_telefone = min(X_clean.columns.get_loc(col) for col in colunas_telefone)

            # Reconstruir ordem: colunas antes + telefone ordenado + colunas depois
            colunas_antes = [col for col in X_clean.columns[:primeira_pos_telefone] if col not in colunas_telefone]
            colunas_depois = [col for col in X_clean.columns[primeira_pos_telefone:] if col not in colunas_telefone]

            nova_ordem = colunas_antes + colunas_telefone_ordenadas + colunas_depois
            X_clean = X_clean[nova_ordem]

        logger.info("")
        logger.info(f"  Features para treinamento: {len(X_clean.columns)}")
        logger.info("")

        # Logar dados do dataset
        mlflow.log_param("total_records", len(dataset_final))
        mlflow.log_param("total_features", len(X_clean.columns))
        mlflow.log_param("total_positives", int(y.sum()))
        mlflow.log_param("positive_rate", float(y.mean()))

        # Split 70/30 (temporal ou stratified)
        data_dt = pd.to_datetime(dataset_original['Data'], errors='coerce')
        data_min = data_dt.min()
        data_max = data_dt.max()

        data_corte = None  # Inicializar para stratified

        if split_method == 'temporal':
            # Split temporal: 70% dos DIAS para treino
            dias_totais = (data_max - data_min).days
            dias_treino = int(dias_totais * 0.7)
            data_corte = data_min + pd.Timedelta(days=dias_treino)

            mask_treino = data_dt <= data_corte
            mask_teste = data_dt > data_corte

            X_train = X_clean[mask_treino]
            X_test = X_clean[mask_teste]
            y_train = y[mask_treino]
            y_test = y[mask_teste]

            logger.info("")
            logger.info(f"Split temporal (70% dos dias):")
            logger.info(f"  Período: {data_min.strftime('%Y-%m-%d')} a {data_max.strftime('%Y-%m-%d')}")
            logger.info(f"  Data corte: {data_corte.strftime('%Y-%m-%d')}")
            logger.info(f"  Treino: {len(X_train):,} registros ({len(X_train)/len(X_clean)*100:.1f}%)")
            logger.info(f"  Teste: {len(X_test):,} registros ({len(X_test)/len(X_clean)*100:.1f}%)")
            logger.info(f"  Taxa treino: {y_train.mean()*100:.2f}%")
            logger.info(f"  Taxa teste: {y_test.mean()*100:.2f}%")

            # Logar dados do split
            mlflow.log_param("split_method", "temporal")
            mlflow.log_param("cut_date", data_corte.strftime('%Y-%m-%d'))

            # === ANÁLISE TEMPORAL TEMPORÁRIA - MEDIUM TRAIN vs TEST ===
            if 'Medium' in dataset_original.columns:
                logger.debug(" ANÁLISE TEMPORAL TEMPORÁRIA: MEDIUM - DISTRIBUIÇÃO TRAIN vs TEST")

                train_medium = dataset_original[mask_treino]['Medium']
                test_medium = dataset_original[mask_teste]['Medium']

                # Top 20 categorias no dataset completo
                top_medium = dataset_original['Medium'].value_counts().head(20)

                logger.debug(f"\n{'MEDIUM':<68} {'TRAIN':>12} {'TEST':>12}")
                logger.debug("-"*92)

                for medium, total in top_medium.items():
                    train_count = (train_medium == medium).sum()
                    test_count = (test_medium == medium).sum()

                    train_pct = (train_count / len(train_medium) * 100) if len(train_medium) > 0 else 0
                    test_pct = (test_count / len(test_medium) * 100) if len(test_medium) > 0 else 0

                    medium_name = str(medium)[:66] if len(str(medium)) > 66 else str(medium)
                    logger.debug(f"{medium_name:<68} {train_count:>6,} ({train_pct:>4.1f}%) {test_count:>6,} ({test_pct:>4.1f}%)")

                # Categorias que só aparecem no test
                train_medium_set = set(train_medium.dropna().unique())
                test_medium_set = set(test_medium.dropna().unique())
                only_test = test_medium_set - train_medium_set

                if only_test:
                    logger.debug(f"\n  CATEGORIAS NOVAS NO TEST (modelo nunca viu): {len(only_test)}")
                    for i, medium in enumerate(sorted(only_test)[:10], 1):
                        count = (test_medium == medium).sum()
                        pct = (count / len(test_medium) * 100)
                        logger.debug(f"   {i:2d}. {str(medium)[:60]:<60} {count:>5,} ({pct:>4.1f}%)")
                    if len(only_test) > 10:
                        logger.debug(f"   ... e mais {len(only_test) - 10} categorias")

                # Categorias que desapareceram (só no train)
                only_train = train_medium_set - test_medium_set
                if only_train:
                    logger.debug(f"\n  CATEGORIAS DESCONTINUADAS (só no train, não aparecem no test): {len(only_train)}")
                    # Ordenar por volume no train
                    only_train_counts = [(m, (train_medium == m).sum()) for m in only_train]
                    only_train_counts.sort(key=lambda x: x[1], reverse=True)

                    for i, (medium, count) in enumerate(only_train_counts[:10], 1):
                        pct = (count / len(train_medium) * 100)
                        logger.debug(f"   {i:2d}. {str(medium)[:60]:<60} {count:>5,} ({pct:>4.1f}%)")
                    if len(only_train) > 10:
                        logger.debug(f"   ... e mais {len(only_train) - 10} categorias")


        elif split_method == 'temporal_leads':
            # Split temporal por LEADS: 70% dos LEADS (ordenados por data) para treino
            # Test set contém últimos 30% dos leads (mais representativo de produção)

            # Criar DataFrame auxiliar com índices e datas
            df_indices = pd.DataFrame({
                'index': range(len(dataset_original)),
                'Data': data_dt
            }).sort_values('Data').reset_index(drop=True)

            n_total = len(df_indices)
            n_train = int(n_total * 0.7)

            # Índices de treino e teste (após ordenação por data)
            train_indices = df_indices['index'].iloc[:n_train].values
            test_indices = df_indices['index'].iloc[n_train:].values

            # Extrair subsets
            X_train = X_clean.iloc[train_indices]
            X_test = X_clean.iloc[test_indices]
            y_train = y.iloc[train_indices]
            y_test = y.iloc[test_indices]

            # Data de corte (última data do treino)
            data_corte = df_indices['Data'].iloc[n_train - 1]
            data_inicio_teste = df_indices['Data'].iloc[n_train]

            # Calcular dias dos períodos
            dias_treino = (data_corte - data_min).days
            dias_teste = (data_max - data_inicio_teste).days

            logger.info(f"  Split temporal por LEADS (70% dos leads):")
            logger.info(f"  Período total: {data_min.strftime('%Y-%m-%d')} a {data_max.strftime('%Y-%m-%d')} ({(data_max - data_min).days} dias)")
            logger.info(f"  Treino: {len(X_train):,} leads ({len(X_train)/n_total*100:.1f}%) Período: {data_min.strftime('%Y-%m-%d')} a {data_corte.strftime('%Y-%m-%d')} ({dias_treino} dias)")
            logger.info(f"  Teste: {len(X_test):,} leads ({len(X_test)/n_total*100:.1f}%) Período: {data_inicio_teste.strftime('%Y-%m-%d')} a {data_max.strftime('%Y-%m-%d')} ({dias_teste} dias)")

            # Quantificar data leakage
            logger.debug(f"\n Análise de data leakage:")
            train_emails = set(dataset_original.iloc[train_indices]['E-mail'].dropna().str.lower().str.strip())
            test_emails = set(dataset_original.iloc[test_indices]['E-mail'].dropna().str.lower().str.strip())
            train_emails.discard('')
            test_emails.discard('')
            emails_leak = len(train_emails & test_emails)
            leak_pct = emails_leak / len(test_emails) * 100 if test_emails else 0
            logger.debug(f"  Emails em ambos train/test: {emails_leak} ({leak_pct:.2f}% do test)")

            # Logar dados do split
            mlflow.log_param("split_method", "temporal_leads")
            mlflow.log_param("cut_date", data_corte.strftime('%Y-%m-%d'))
            mlflow.log_param("train_days", dias_treino)
            mlflow.log_param("test_days", dias_teste)
            mlflow.log_metric("leakage_email_pct", leak_pct)

            # === ANÁLISE TEMPORAL TEMPORÁRIA - MEDIUM TRAIN vs TEST ===
            if 'Medium' in dataset_original.columns:
                logger.debug(" ANÁLISE TEMPORAL TEMPORÁRIA: MEDIUM - DISTRIBUIÇÃO TRAIN vs TEST")

                train_medium = dataset_original.iloc[train_indices]['Medium']
                test_medium = dataset_original.iloc[test_indices]['Medium']

                # Top 20 categorias no dataset completo
                top_medium = dataset_original['Medium'].value_counts().head(20)

                logger.debug(f"\n{'MEDIUM':<68} {'TRAIN':>12} {'TEST':>12}")
                logger.debug("-"*92)

                for medium, total in top_medium.items():
                    train_count = (train_medium == medium).sum()
                    test_count = (test_medium == medium).sum()

                    train_pct = (train_count / len(train_medium) * 100) if len(train_medium) > 0 else 0
                    test_pct = (test_count / len(test_medium) * 100) if len(test_medium) > 0 else 0

                    medium_name = str(medium)[:66] if len(str(medium)) > 66 else str(medium)
                    logger.debug(f"{medium_name:<68} {train_count:>6,} ({train_pct:>4.1f}%) {test_count:>6,} ({test_pct:>4.1f}%)")

                # Categorias que só aparecem no test
                train_medium_set = set(train_medium.dropna().unique())
                test_medium_set = set(test_medium.dropna().unique())
                only_test = test_medium_set - train_medium_set

                if only_test:
                    logger.debug(f"\n  CATEGORIAS NOVAS NO TEST (modelo nunca viu): {len(only_test)}")
                    for i, medium in enumerate(sorted(only_test)[:10], 1):
                        count = (test_medium == medium).sum()
                        pct = (count / len(test_medium) * 100)
                        logger.debug(f"   {i:2d}. {str(medium)[:60]:<60} {count:>5,} ({pct:>4.1f}%)")
                    if len(only_test) > 10:
                        logger.debug(f"   ... e mais {len(only_test) - 10} categorias")

                # Categorias que desapareceram (só no train)
                only_train = train_medium_set - test_medium_set
                if only_train:
                    logger.debug(f"\n  CATEGORIAS DESCONTINUADAS (só no train, não aparecem no test): {len(only_train)}")
                    # Ordenar por volume no train
                    only_train_counts = [(m, (train_medium == m).sum()) for m in only_train]
                    only_train_counts.sort(key=lambda x: x[1], reverse=True)

                    for i, (medium, count) in enumerate(only_train_counts[:10], 1):
                        pct = (count / len(train_medium) * 100)
                        logger.debug(f"   {i:2d}. {str(medium)[:60]:<60} {count:>5,} ({pct:>4.1f}%)")
                    if len(only_train) > 10:
                        logger.debug(f"   ... e mais {len(only_train) - 10} categorias")


        else:  # stratified
            # Split stratified POR PESSOA usando componentes conectados: garantir zero leakage
            logger.info(f"\n Split estratificado POR PESSOA (componentes conectados - zero leakage):")

            # 1. Extrair emails e telefones válidos
            email_serie = dataset_original['E-mail'].fillna('')
            telefone_serie = dataset_original['Telefone'].fillna('')

            # 2. Implementar Union-Find para agrupar registros conectados por email OU telefone
            class UnionFind:
                def __init__(self, n):
                    self.parent = list(range(n))
                    self.rank = [0] * n

                def find(self, x):
                    if self.parent[x] != x:
                        self.parent[x] = self.find(self.parent[x])
                    return self.parent[x]

                def union(self, x, y):
                    px, py = self.find(x), self.find(y)
                    if px == py:
                        return
                    if self.rank[px] < self.rank[py]:
                        px, py = py, px
                    self.parent[py] = px
                    if self.rank[px] == self.rank[py]:
                        self.rank[px] += 1

            # Inicializar Union-Find
            n_records = len(email_serie)
            uf = UnionFind(n_records)

            # Mapear email  índices e telefone  índices
            email_to_indices = {}
            phone_to_indices = {}

            for idx in range(n_records):
                email = email_serie.iloc[idx]
                phone = telefone_serie.iloc[idx]

                # Conectar por email
                if email and email != '':
                    if email in email_to_indices:
                        uf.union(idx, email_to_indices[email])
                    else:
                        email_to_indices[email] = idx

                # Conectar por telefone
                if phone and phone != '':
                    if phone in phone_to_indices:
                        uf.union(idx, phone_to_indices[phone])
                    else:
                        phone_to_indices[phone] = idx

            # 3. Agrupar registros por componente conectado
            grupos = {}
            for idx in range(n_records):
                grupo_id = uf.find(idx)
                if grupo_id not in grupos:
                    grupos[grupo_id] = []
                grupos[grupo_id].append(idx)

            # === ANÁLISE DETALHADA DOS GRUPOS ===
            logger.info(f"\n ANÁLISE DE GRUPOS CONECTADOS:")

            tamanhos_grupos = [len(indices) for indices in grupos.values()]
            grupos_tamanho_1 = sum(1 for t in tamanhos_grupos if t == 1)
            grupos_tamanho_2_plus = sum(1 for t in tamanhos_grupos if t > 1)
            registros_em_grupos_2_plus = sum(t for t in tamanhos_grupos if t > 1)

            logger.info(f"\nEstatísticas gerais:")
            logger.info(f"  Total de grupos: {len(grupos):,}")
            logger.info(f"  Total de registros: {sum(tamanhos_grupos):,}")
            logger.info(f"  Grupos com 1 registro: {grupos_tamanho_1:,} ({grupos_tamanho_1/len(grupos)*100:.1f}%)")
            logger.info(f"  Grupos com 2+ registros: {grupos_tamanho_2_plus:,} ({grupos_tamanho_2_plus/len(grupos)*100:.1f}%)")
            logger.info(f"  Registros agrupados: {registros_em_grupos_2_plus:,} ({registros_em_grupos_2_plus/sum(tamanhos_grupos)*100:.1f}%)")

            import numpy as np
            from collections import Counter
            logger.info(f"\nEstatísticas de tamanho:")
            logger.info(f"  Média: {np.mean(tamanhos_grupos):.2f} registros/grupo")
            logger.info(f"  Mediana: {np.median(tamanhos_grupos):.0f}")
            logger.info(f"  Máximo: {max(tamanhos_grupos)} registros")

            logger.info(f"\nDistribuição por tamanho:")
            distribuicao = Counter(tamanhos_grupos)
            for tamanho in sorted(distribuicao.keys())[:10]:
                count = distribuicao[tamanho]
                registros_total = tamanho * count
                logger.info(f"  {tamanho:2d} registro(s): {count:6,} grupos ({count/len(grupos)*100:5.1f}%) = {registros_total:6,} registros")

            if max(tamanhos_grupos) > 10:
                grandes = sum(1 for t in tamanhos_grupos if t > 10)
                registros_grandes = sum(t for t in tamanhos_grupos if t > 10)
                logger.info(f"  11+ registros:  {grandes:6,} grupos ({grandes/len(grupos)*100:5.1f}%) = {registros_grandes:6,} registros")

            logger.info(f"\nTop 5 maiores grupos (exemplos reais):")
            grupos_ordenados = sorted(grupos.items(), key=lambda x: len(x[1]), reverse=True)
            for i, (grupo_id, indices) in enumerate(grupos_ordenados[:5], 1):
                emails_grupo = set()
                telefones_grupo = set()
                for idx in indices:
                    email = email_serie.iloc[idx]
                    phone = telefone_serie.iloc[idx]
                    if email and email != '':
                        emails_grupo.add(email)
                    if phone and phone != '':
                        telefones_grupo.add(phone)

                logger.info(f"  {i}. Grupo com {len(indices)} registros:")
                logger.info(f"     Emails únicos: {len(emails_grupo)} - {', '.join(str(e) for e in list(emails_grupo)[:2])}{'...' if len(emails_grupo) > 2 else ''}")
                logger.info(f"     Telefones únicos: {len(telefones_grupo)} - {', '.join(str(t) for t in list(telefones_grupo)[:2])}{'...' if len(telefones_grupo) > 2 else ''}")

            logger.info()

            # 4. Criar DataFrame de grupos com target agregado
            grupos_data = []
            for grupo_id, indices in grupos.items():
                target_values = y.iloc[indices]
                grupos_data.append({
                    'grupo_id': grupo_id,
                    'target': target_values.max(),  # Se qualquer registro tem target=1, grupo é 1
                    'idx_original': indices
                })

            grupos_df = pd.DataFrame(grupos_data)

            # Informações
            pessoas_unicas = len(grupos_df)
            registros_totais = n_records
            pessoas_duplicadas = registros_totais - pessoas_unicas

            logger.info(f"  Total de registros: {registros_totais:,}")
            logger.info(f"  Grupos (pessoas únicas): {pessoas_unicas:,}")
            logger.info(f"  Registros agrupados: {pessoas_duplicadas:,} ({pessoas_duplicadas/registros_totais*100:.1f}%)")

            # 5. Split GRUPOS com estratificação
            pessoas_train, pessoas_test = train_test_split(
                grupos_df,
                test_size=0.3,
                stratify=grupos_df['target'],
                random_state=42
            )

            # 4. Expandir para registros originais
            idx_train = [idx for idxs in pessoas_train['idx_original'] for idx in idxs]
            idx_test = [idx for idxs in pessoas_test['idx_original'] for idx in idxs]

            X_train = X_clean.iloc[idx_train]
            X_test = X_clean.iloc[idx_test]
            y_train = y.iloc[idx_train]
            y_test = y.iloc[idx_test]

            # 5. Validar distribuições e leakage
            emails_train = set(dataset_original.iloc[idx_train]['E-mail'].dropna())
            emails_test = set(dataset_original.iloc[idx_test]['E-mail'].dropna())
            emails_leakage = emails_train & emails_test

            telefones_train = set(dataset_original.iloc[idx_train]['Telefone'].dropna())
            telefones_test = set(dataset_original.iloc[idx_test]['Telefone'].dropna())
            telefones_leakage = telefones_train & telefones_test

            logger.info(f"\n  Split por grupos conectados:")
            logger.info(f"  Grupos em TRAIN: {len(pessoas_train):,} ({len(pessoas_train)/len(grupos_df)*100:.1f}%)")
            logger.info(f"  Grupos em TEST: {len(pessoas_test):,} ({len(pessoas_test)/len(grupos_df)*100:.1f}%)")
            logger.info(f"\n  Registros resultantes:")
            logger.info(f"  Treino: {len(X_train):,} registros ({len(X_train)/len(X_clean)*100:.1f}%)")
            logger.info(f"  Teste: {len(X_test):,} registros ({len(X_test)/len(X_clean)*100:.1f}%)")
            logger.info(f"\n  Distribuição do target:")
            logger.info(f"  Taxa treino: {y_train.mean()*100:.4f}%")
            logger.info(f"  Taxa teste: {y_test.mean()*100:.4f}%")
            logger.info(f"  Diferença: {abs(y_train.mean() - y_test.mean())*100:.4f}pp")
            logger.info(f"\n  Validação de leakage (zero esperado):")
            logger.info(f"  {'' if len(emails_leakage) == 0 else ''} Emails em ambos: {len(emails_leakage)}")
            logger.info(f"  {'' if len(telefones_leakage) == 0 else ''} Telefones em ambos: {len(telefones_leakage)}")

            if len(emails_leakage) > 0 or len(telefones_leakage) > 0:
                logger.info(f"\n    AVISO: Leakage detectado! Verificar implementação de componentes conectados.")
            else:
                logger.info(f"\n   SUCESSO: Zero leakage! Split por pessoa implementado corretamente.")

            # Logar dados do split
            mlflow.log_param("split_method", "stratified_connected_components")
            mlflow.log_param("unique_groups", pessoas_unicas)
            mlflow.log_param("total_records", registros_totais)
            mlflow.log_param("grouped_records", pessoas_duplicadas)
            mlflow.log_param("leakage_emails", len(emails_leakage))
            mlflow.log_param("leakage_telefones", len(telefones_leakage))
            mlflow.log_param("cut_date", "N/A (stratified)")

        mlflow.log_param("train_records", len(X_train))
        mlflow.log_param("test_records", len(X_test))
        mlflow.log_param("period_start", data_min.strftime('%Y-%m-%d'))
        mlflow.log_param("period_end", data_max.strftime('%Y-%m-%d'))

        # Treinar modelo Random Forest
        # Hiperparâmetros padrão (MELHOR MODELO - AUC 0.6979, Mono 77.8%)
        hyperparams = {
            'n_estimators': 300,
            'max_depth': 8,
            'min_samples_split': 2,
            'min_samples_leaf': 1,
            'max_features': 'sqrt',
            'class_weight': 'balanced',
            'random_state': 42,
            'n_jobs': -1
        }

        # Hiperparâmetros MONO 100% testados (NÃO recomendado - AUC 0.6706, Mono 77.8%)
        # hyperparams = {
        #     'n_estimators': 300,
        #     'max_depth': None,
        #     'min_samples_split': 5,
        #     'min_samples_leaf': 3,
        #     'max_features': 'log2',
        #     'class_weight': 'balanced',
        #     'random_state': 42,
        #     'n_jobs': -1
        # }

        # Usar custom_hyperparams se fornecido (do tuning)
        if custom_hyperparams is not None:
            logger.info(f"\n Usando hiperparâmetros do tuning:")
            for key, value in custom_hyperparams.items():
                if key in hyperparams and custom_hyperparams[key] != hyperparams[key]:
                    logger.info(f"   {key}: {hyperparams[key]}  {value}")
                    hyperparams[key] = value

        modelo_final = RandomForestClassifier(**hyperparams)

        # Logar hiperparâmetros
        for param_name, param_value in hyperparams.items():
            mlflow.log_param(param_name, param_value)

        # Indicar se foi tunado
        mlflow.log_param("hyperparameter_tuning", custom_hyperparams is not None)

        # === DEBUG: PRINT COLUNAS EXATAS ANTES DO FIT ===
        logger.debug(" COLUNAS EXATAS PASSADAS PARA O MODELO (X_train.columns):")
        for i, col in enumerate(X_train.columns, 1):
            logger.debug(f"  {i:2d}. {col}")
        logger.debug(f"\nTotal: {len(X_train.columns)} features")
        logger.debug(f"Shape: {X_train.shape}")

        logger.info("")
        logger.info("  Treinando modelo...")
        modelo_final.fit(X_train, y_train)
        y_prob = modelo_final.predict_proba(X_test)[:, 1]
        auc_final = roc_auc_score(y_test, y_prob)
        logger.info("")

        # Feature importance
        feature_importance = pd.DataFrame({
            'feature_original': X.columns,
            'feature_clean': X_clean.columns,
            'importance': modelo_final.feature_importances_
        }).sort_values('importance', ascending=False)

        logger.debug(f"Feature importance calculada para {len(feature_importance)} features")

        # 2. CRIAR REGISTRY DE FEATURES
        logger.debug("\n2. CRIANDO FEATURE REGISTRY")
        logger.debug("-" * 50)

        # Categorizar features
        features_utm = []
        features_pesquisa = []
        features_derivadas = []
        features_outras = []

        for col in X.columns:
            if any(utm in col for utm in ['Source_', 'Medium_', 'Term_']):
                features_utm.append(col)
            elif any(pesq in col for pesq in ['gênero', 'idade', 'faz', 'faixa', 'cartão', 'estudou', 'faculdade', 'evento']):
                features_pesquisa.append(col)
            elif any(deriv in col for deriv in ['nome_', 'email_', 'telefone_', 'dia_semana']):
                features_derivadas.append(col)
            else:
                features_outras.append(col)

        # Mapeamento nome original -> nome limpo
        mapeamento_nomes = {}
        for orig, limpo in zip(X.columns, X_clean.columns):
            mapeamento_nomes[orig] = limpo

        # Criar registry completo
        feature_registry = {
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "model_name": f"v1_devclub_rf_{split_method}_single",
                "dataset_name": f"dataset_devclub_rf_{split_method}",
                "total_features": len(X.columns),
                "total_records": len(dataset_final),
                "target_column": "target",
                "model_type": "RandomForestClassifier",
                "split_type": split_method,
                "sklearn_version": sklearn.__version__
            },
            "data_split": {
                "method": split_method,
                "train_records": len(X_train),
                "test_records": len(X_test),
                "train_positive_rate": float(y_train.mean()),
                "test_positive_rate": float(y_test.mean()),
                "cut_date": data_corte.strftime('%Y-%m-%d') if data_corte else "N/A (stratified)"
            },
            "feature_categories": {
                "utm_features": {
                    "count": len(features_utm),
                    "description": "Features derived from UTM parameters (Source, Medium, Term)",
                    "features": features_utm
                },
                "survey_features": {
                    "count": len(features_pesquisa),
                    "description": "Features from lead survey responses",
                    "features": features_pesquisa
                },
                "derived_features": {
                    "count": len(features_derivadas),
                    "description": "Features engineered from raw data (name, email, phone, temporal)",
                    "features": features_derivadas
                },
                "other_features": {
                    "count": len(features_outras),
                    "description": "Additional features not in main categories",
                    "features": features_outras
                }
            },
            "feature_transformations": {
                "description": "Mapping from original feature names to model-ready names",
                "name_mapping": mapeamento_nomes,
                "encoding_applied": {
                    "categorical_encoding": "one-hot",
                    "ordinal_features": ["Qual a sua idade?", "Atualmente, qual a sua faixa salarial?"],
                    "binary_features": ["dia_semana"],
                    "removed_reference_categories": ["telefone_comprimento_8"]
                },
                "column_cleaning": {
                    "regex_pattern": "[^A-Za-z0-9_] -> _",
                    "multiple_underscores": "__ -> _",
                    "strip_underscores": "leading/trailing removed"
                }
            },
            "feature_importance": {
                "description": "Feature importance from trained RandomForestClassifier",
                "top_10_features": [
                    {
                        "rank": i+1,
                        "feature_original": row['feature_original'],
                        "feature_clean": row['feature_clean'],
                        "importance": float(row['importance'])
                    }
                    for i, (_, row) in enumerate(feature_importance.head(10).iterrows())
                ],
                "utm_total_importance": float(
                    feature_importance[
                        feature_importance['feature_original'].str.contains('Source_|Medium_|Term_', case=False, na=False)
                    ]['importance'].sum()
                )
            },
            "expected_dtypes": {
                feature: str(dataset_final[feature].dtype) if feature in dataset_final.columns else "float64"
                for feature in X.columns
            },
            "validation_rules": {
                "required_features": list(X.columns),
                "optional_features": [],
                "total_expected_features": len(X.columns),
                "target_required": True,
                "missing_value_strategy": "model_will_fail_if_missing_features"
            }
        }

        logger.debug(f"Feature registry criado:")
        logger.debug(f"  - Features UTM: {len(features_utm)}")
        logger.debug(f"  - Features Pesquisa: {len(features_pesquisa)}")
        logger.debug(f"  - Features Derivadas: {len(features_derivadas)}")
        logger.debug(f"  - Features Outras: {len(features_outras)}")

        # 3. CRIAR METADADOS DO MODELO
        logger.debug("\n3. CRIANDO METADADOS DO MODELO")
        logger.debug("-" * 50)

        # Calcular métricas detalhadas
        df_analise = pd.DataFrame({
            'probabilidade': y_prob,
            'target_real': y_test.reset_index(drop=True)
        })

        df_analise['decil'] = pd.qcut(
            df_analise['probabilidade'],
            q=10,
            labels=[f'D{i}' for i in range(1, 11)],
            duplicates='drop'
        )

        # ====================================================================
        # CALCULAR THRESHOLDS FIXOS DE DECIS (para uso em produção)
        # ====================================================================
        logger.debug("CALCULANDO THRESHOLDS FIXOS DE DECIS")

        decil_thresholds = calcular_thresholds_decis(y_prob, df_analise['decil'])

        # Validar thresholds: classificar test set usando thresholds e comparar
        logger.debug("\n Validando thresholds: classificando test set...")
        decis_via_threshold = atribuir_decis_batch(y_prob, decil_thresholds)
        comparacao = comparar_distribuicoes(
            df_analise['decil'],
            decis_via_threshold,
            verbose=False
        )

        analise_decis = df_analise.groupby('decil', observed=True).agg({
            'target_real': ['count', 'sum', 'mean']
        }).round(4)

        analise_decis.columns = ['total_leads', 'conversoes', 'taxa_conversao']
        analise_decis['pct_total_conversoes'] = (
            analise_decis['conversoes'] / analise_decis['conversoes'].sum() * 100
        ).round(2)

        taxa_base = y_test.mean()
        analise_decis['lift'] = (analise_decis['taxa_conversao'] / taxa_base).round(2)

        top3_conversoes = analise_decis.tail(3)['pct_total_conversoes'].sum()
        top5_conversoes = analise_decis.tail(5)['pct_total_conversoes'].sum()
        lift_maximo = analise_decis['lift'].max()

        # Monotonia
        taxas = analise_decis['taxa_conversao'].values
        crescimentos = sum(1 for i in range(1, len(taxas)) if taxas[i] >= taxas[i-1])
        monotonia = (crescimentos / (len(taxas) - 1)) * 100 if len(taxas) > 1 else 100.0

        # Logar métricas principais
        mlflow.log_metric("auc", auc_final)
        mlflow.log_metric("top3_decil_concentration", top3_conversoes)
        mlflow.log_metric("top5_decil_concentration", top5_conversoes)
        mlflow.log_metric("lift_maximum", lift_maximo)
        mlflow.log_metric("monotonia_percentage", monotonia)
        mlflow.log_metric("baseline_conversion_rate", taxa_base)
        mlflow.log_metric("train_positive_rate", y_train.mean())
        mlflow.log_metric("test_positive_rate", y_test.mean())

        # Metadados do modelo
        model_metadata = {
            "model_info": {
                "model_name": f"v1_devclub_rf_{split_method}_single",
                "model_type": "RandomForestClassifier",
                "split_type": split_method,
                "library": "scikit-learn",
                "library_version": sklearn.__version__,
                "trained_at": datetime.now().isoformat(),
                "training_duration_info": f"Trained with {split_method} split"
            },
            "hyperparameters": hyperparams,
            "training_data": {
                "dataset_name": f"dataset_devclub_rf_{split_method}",
                "total_records": len(dataset_final),
                "training_records": len(X_train),
                "test_records": len(X_test),
                "features_count": len(X_clean.columns),
                "target_distribution": {
                    "training_positive_rate": float(y_train.mean()),
                    "test_positive_rate": float(y_test.mean()),
                    "training_positive_count": int(y_train.sum()),
                    "test_positive_count": int(y_test.sum())
                },
                "temporal_split": {
                    "period_start": data_min.strftime('%Y-%m-%d'),
                    "period_end": data_max.strftime('%Y-%m-%d'),
                    "cut_date": data_corte.strftime('%Y-%m-%d') if data_corte else "N/A (stratified)",
                    "training_days": int((data_corte - data_min).days) if data_corte else 0,
                    "total_days": int((data_max - data_min).days)
                }
            },
            "recall_metrics": {
                "vendas_devclub_total": int(recall_metrics['vendas_devclub_total']) if recall_metrics else None,
                "vendas_matched": int(recall_metrics['vendas_matched']) if recall_metrics else None,
                "recall": float(recall_metrics['recall']) if recall_metrics else None,
                "fator_correcao": float(recall_metrics['fator_correcao']) if recall_metrics else None,
                "description": "Recall = vendas_matched / vendas_devclub_total. Used to auto-correct conversion rates in business_config.py"
            },
            "performance_metrics": {
                "auc": float(auc_final),
                "top3_decil_concentration": float(top3_conversoes),
                "top5_decil_concentration": float(top5_conversoes),
                "lift_maximum": float(lift_maximo),
                "monotonia_percentage": float(monotonia),
                "baseline_conversion_rate": float(taxa_base)
            },
            "decil_analysis": {
                f"decil_{i+1}": {
                    "total_leads": int(row['total_leads']),
                    "conversions": int(row['conversoes']),
                    "conversion_rate": float(row['taxa_conversao']),
                    "pct_total_conversions": float(row['pct_total_conversoes']),
                    "lift": float(row['lift'])
                }
                for i, (_, row) in enumerate(analise_decis.iterrows())
            },
            "decil_thresholds": {
                "method": "exact_from_test_set",
                "calculated_at": datetime.now().isoformat(),
                "validation_metrics": {
                    "max_diferenca_absoluta": int(comparacao['max_diferenca_absoluta']),
                    "media_diferenca_absoluta": float(comparacao['media_diferenca_absoluta']),
                    "max_diferenca_percentual": float(comparacao['max_diferenca_percentual'])
                },
                "thresholds": decil_thresholds,
                "usage_notes": {
                    "description": "Use these thresholds for consistent decil assignment in production",
                    "benefits": [
                        "Consistent scoring across different batch sizes",
                        "Enables high-frequency CAPI batching (every 2-3 hours)",
                        "Prevents value instability in Meta algorithm"
                    ],
                    "implementation": "Use atribuir_decil_por_threshold(score, thresholds) from src.model.decil_thresholds"
                }
            },
            "production_notes": {
                "use_case": "Lead scoring for DevClub products with budget allocation optimization",
                "prediction_interpretation": "Higher probability = higher priority for budget allocation",
                "calibration_status": "Not calibrated - use for ranking only",
                "recommended_deployment": "Batch scoring with validation on future launches",
                "monitoring_requirements": "Track performance degradation and feature drift",
                "model_limitations": f"Monotonia at {monotonia:.1f}% - investigate if < 80%"
            },
            "data_quality_baseline": {
                "description": "Missing rates das colunas críticas usadas no modelo - baseline para monitoramento",
                "captured_at": datetime.now().isoformat(),
                "total_records": len(dataset_devclub_original),
                "missing_rates": missing_rates_baseline if missing_rates_baseline else {},
                "usage": "Compare com novos treinos para detectar mudanças em qualidade de dados"
            }
        }

        # Logar modelo no MLflow
        mlflow.sklearn.log_model(modelo_final, "model")
        logger.debug(" Modelo registrado no MLflow")

        # 4. SALVAR ARQUIVOS LOCAIS (OPCIONAL)
        output_dir = None
        if save_files:
            logger.debug("\n4. SALVANDO ARQUIVOS LOCAIS")
            logger.debug("-" * 50)

            # Criar pasta com timestamp no diretório V2/files/
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            base_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'files')
            output_dir = os.path.join(base_dir, timestamp)
            os.makedirs(output_dir, exist_ok=True)

            # Salvar feature registry
            registry_filename = f'{output_dir}/feature_registry_v1_devclub_rf_{split_method}_single.json'
            with open(registry_filename, 'w', encoding='utf-8') as f:
                json.dump(feature_registry, f, indent=2, ensure_ascii=False)
            logger.debug(f" {registry_filename} salvo")

            # Salvar metadados do modelo
            metadata_filename = f'{output_dir}/model_metadata_v1_devclub_rf_{split_method}_single.json'
            with open(metadata_filename, 'w', encoding='utf-8') as f:
                json.dump(model_metadata, f, indent=2, ensure_ascii=False)
            logger.debug(f" {metadata_filename} salvo")

            # Salvar modelo
            model_filename = f'{output_dir}/modelo_lead_scoring_v1_devclub_rf_{split_method}_single.pkl'
            joblib.dump(modelo_final, model_filename)
            logger.debug(f" {model_filename} salvo")

            # Salvar features ordenadas
            features_filename = f'{output_dir}/features_ordenadas_v1_devclub_rf_{split_method}_single.json'
            features_ordenadas = {
                "feature_names": list(X_clean.columns),
                "feature_count": len(X_clean.columns),
                "created_at": datetime.now().isoformat(),
                "model_name": f"v1_devclub_rf_{split_method}_single"
            }
            with open(features_filename, 'w', encoding='utf-8') as f:
                json.dump(features_ordenadas, f, indent=2, ensure_ascii=False)
            logger.debug(f" {features_filename} salvo")

            # Salvar categorias esperadas (para drift detection)
            if categorias_treino:
                categorias_filename = f'{output_dir}/categorias_esperadas.json'
                with open(categorias_filename, 'w', encoding='utf-8') as f:
                    json.dump(categorias_treino, f, indent=2, ensure_ascii=False)
                logger.debug(f" {categorias_filename} salvo ({len(categorias_treino)} colunas rastreadas)")

            # Salvar distribuições esperadas (para distribution drift detection)
            if distribuicoes_treino:
                distribuicoes_filename = f'{output_dir}/distribuicoes_esperadas.json'
                with open(distribuicoes_filename, 'w', encoding='utf-8') as f:
                    json.dump(distribuicoes_treino, f, indent=2, ensure_ascii=False)
                cat_count = len(distribuicoes_treino.get('categorical', {}))
                num_count = len(distribuicoes_treino.get('numerical', {}))
                logger.debug(f" {distribuicoes_filename} salvo ({cat_count} categóricas, {num_count} numéricas)")

            # Salvar test set com predições
            test_set_filename = f'{output_dir}/test_set_predictions.csv'
            df_test_predictions = X_test.copy()
            df_test_predictions['target_real'] = y_test.values
            df_test_predictions['probabilidade'] = y_prob
            df_test_predictions.to_csv(test_set_filename, index=False)
            logger.debug(f" {test_set_filename} salvo")

            logger.info("")
            logger.info(f"Arquivos locais salvos em: {output_dir}")

            # Atualizar active_model.yaml se solicitado
            if set_active:
                logger.debug("\n5. ATUALIZANDO MODELO ATIVO")
                logger.debug("-" * 50)

                import yaml
                from pathlib import Path

                config_path = Path(__file__).parent.parent.parent / "configs" / "active_model.yaml"
                active_config = {
                    'active_model': {
                        'model_name': f"v1_devclub_rf_{split_method}_single",
                        'model_path': f"files/{timestamp}",
                        'trained_at': model_metadata['model_info']['trained_at'],
                        'split_method': split_method,
                        'performance': {
                            'auc': float(auc_final),
                            'monotonia_percentage': float(monotonia),
                            'lift_maximum': float(lift_maximo)
                        }
                    }
                }

                with open(config_path, 'w') as f:
                    yaml.dump(active_config, f, default_flow_style=False, sort_keys=False)
                    f.write("\n# Para mudar o modelo ativo:\n")
                    f.write("# 1. Treine um novo modelo: python src/train_pipeline.py --split-method temporal_leads --save-files --set-active\n")
                    f.write("# 2. Ou edite este arquivo manualmente apontando para outro model_path\n")

                logger.debug(f" {config_path} atualizado")
                logger.debug(f"  Modelo ativo: v1_devclub_rf_{split_method}_single")
                logger.debug(f"  Path: {output_dir}")

                # Atualizar business_config.py com recall real
                atualizar_business_config_com_recall(model_metadata)
        else:
            logger.debug("\n4. ARQUIVOS LOCAIS NÃO SALVOS (--save-files=False)")
            logger.debug("-" * 50)
            logger.debug("Use --save-files para salvar arquivos locais")

            if set_active:
                logger.debug("\n  AVISO: --set-active requer --save-files")
                logger.debug("   Modelo ativo não foi atualizado")

        # Sempre logar metadata como artifact no MLflow
        mlflow.log_dict(model_metadata, "model_metadata.json")
        mlflow.log_dict(feature_registry, "feature_registry.json")
        logger.debug(" Metadados adicionais registrados no MLflow")

        # 5. RESUMO FINAL
        logger.info(" MODELO DEVCLUB REGISTRADO COM SUCESSO")
        logger.info("")
        logger.info("  Informações do modelo:")
        logger.info(f"  Modelo: v1_devclub_rf_{split_method}_single")
        logger.info(f"  Algoritmo: RandomForestClassifier")
        logger.info(f"  Split: {split_method}")
        logger.info(f"  Matching: {matching_method}")
        logger.info(f"  Métricas de performance:")
        logger.info(f"    AUC: {auc_final:.3f}")
        logger.info(f"    Top 3 decis: {top3_conversoes:.1f}%")
        logger.info(f"    Lift máximo: {lift_maximo:.1f}x")
        logger.info(f"    Monotonia: {monotonia:.1f}%")
        logger.info(f"    Features: {len(X_clean.columns)}")
        logger.info(f"    MLflow Run ID: {mlflow.active_run().info.run_id}")
        if output_dir:
            logger.info(f"    Arquivos locais: {output_dir}")
        else:
            logger.info(f"    Arquivos locais: não salvos")

        # Retornar model_metadata completo para uso pelo orquestrador de retreino
        # Adicionar informações extras que não estão no metadata
        model_metadata['output_dir'] = output_dir
        model_metadata['mlflow_run_id'] = mlflow.active_run().info.run_id
        model_metadata['matching_method'] = matching_method

        resultado_final = model_metadata

        return resultado_final

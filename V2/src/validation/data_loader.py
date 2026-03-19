"""
Módulo para carregamento e normalização de dados de leads e vendas.

Este módulo fornece classes para carregar dados de:
- Google Sheets (CSV com leads e scores)
- Guru (Excel com vendas)
- TMB (Excel com vendas)

Todas as funções normalizam emails, telefones e datas para garantir
matching consistente.
"""

import pandas as pd
import numpy as np
from typing import List, Optional, Tuple, Dict
from pathlib import Path
import logging
import re
import os
import gspread
import yaml
from google.auth import default as gauth_default

# Importar funções de normalização existentes
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.matching.matching_email_telefone import normalizar_email, normalizar_telefone_robusto

logger = logging.getLogger(__name__)


def get_active_model_path() -> Path:
    """
    Carrega o caminho do modelo ativo do arquivo active_model.yaml.

    Returns:
        Path completo para o diretório do modelo ativo

    Raises:
        FileNotFoundError: Se active_model.yaml não existir
        KeyError: Se estrutura do YAML estiver incorreta
    """
    # TODO multi-client: derivar client_id do ClientConfig e usar active_models/{client_id}.yaml
    config_path = Path(__file__).parent.parent.parent / "configs" / "active_models" / "devclub.yaml"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Arquivo de configuração não encontrado: {config_path}\n"
            f"Execute o treinamento com --set-active ou configure manualmente."
        )

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    active_model = config['active_model']
    if 'mlflow_run_id' in active_model:
        model_path_str = str(Path('mlruns') / '1' / active_model['mlflow_run_id'] / 'artifacts')
    else:
        model_path_str = active_model['model_path']
    model_path = Path(__file__).parent.parent.parent / model_path_str

    if not model_path.exists():
        raise FileNotFoundError(
            f"Modelo configurado não encontrado: {model_path}\n"
            f"Configuração em: {config_path}"
        )

    return model_path

# URLs dos Google Sheets (pode ser sobrescrito via env var)
PRODUCAO_SHEETS_URL = 'https://docs.google.com/spreadsheets/d/1VYti8jX277VNMkvzrfnJSR_Ko8L1LQFDdMEeD6D8_Vo'  # [LF] Pesquisa - Produção
BACKUP_SHEETS_URL = 'https://docs.google.com/spreadsheets/d/1OqNYA5zU9ix1uf52ovRYIdLhcugzwgfKOheKxE_zgvE'    # [LF] Pesquisa - Backup


class LeadDataLoader:
    """
    Carrega e normaliza dados de leads do Google Sheets.

    CSV esperado contém:
    - Data: Timestamp da captura
    - E-mail: Email do lead
    - Nome Completo: Nome completo
    - Telefone: Telefone com DDD
    - Campaign: Nome da campanha UTM
    - lead_score: Score do modelo (0-1)
    - Source, Medium, Term, Content: UTMs
    """

    def __init__(self):
        self.required_columns = ['Data', 'E-mail', 'Campaign']
        self._thresholds_cache = None  # Cache dos thresholds do modelo

    def load_leads_from_sheets(self, sheets_url: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None, use_cache: bool = True, num_sheets: int = 2, include_secondary: bool = True, training_mode: bool = False) -> pd.DataFrame:
        """
        Carrega leads diretamente do Google Sheets (produção) com cache local.

        Args:
            sheets_url: URL do Google Sheets (default: usar variável de ambiente ou PRODUCAO_SHEETS_URL)
            start_date: Data início para filtro (YYYY-MM-DD) - opcional
            end_date: Data fim para filtro (YYYY-MM-DD) - opcional
            use_cache: Se True, usa cache local se disponível e válido (default: True)
            num_sheets: Número de abas para carregar (default: 2 para validação, 1 para retreino)
            include_secondary: Se True, também carrega da planilha secundária (aba 0 apenas)
            training_mode: Se True, colunas demográficas passam com nomes originais para a
                           Célula 5 normalizar (igual aos arquivos Excel). Se False (produção),
                           normaliza para snake_case para alimentar o modelo diretamente.

        Returns:
            DataFrame normalizado (mesmo formato que load_leads_csv)
        """
        # Determinar URLs
        urls_to_load = []

        if sheets_url is None:
            sheets_url = os.getenv('GOOGLE_SHEETS_URL', PRODUCAO_SHEETS_URL)

        urls_to_load.append(('Produção', sheets_url, num_sheets))

        # Adicionar planilha de backup se solicitado
        if include_secondary:
            secondary_url = os.getenv('SECONDARY_SHEETS_URL', BACKUP_SHEETS_URL)
            urls_to_load.append(('Backup', secondary_url, 1))  # Apenas aba 0

        # Carregar de todas as planilhas
        all_dfs = []

        for planilha_nome, current_url, n_sheets in urls_to_load:
            logger.debug(f" Carregando planilha {planilha_nome}")
            df_planilha = self._load_single_spreadsheet(current_url, start_date, end_date, use_cache, n_sheets, training_mode=training_mode)
            if df_planilha is not None and len(df_planilha) > 0:
                all_dfs.append(df_planilha)
                logger.info(f"    Planilha {planilha_nome}: {len(df_planilha)} leads carregados")

        # Combinar todas as planilhas
        if not all_dfs:
            logger.warning("    Nenhum lead carregado de nenhuma planilha")
            return pd.DataFrame()

        if len(all_dfs) == 1:
            return all_dfs[0]

        df_combined = pd.concat(all_dfs, ignore_index=True, sort=False)

        # Remover duplicatas por email (após normalização usa 'email' minúsculo)
        email_col = 'email' if 'email' in df_combined.columns else 'E-mail'

        if email_col not in df_combined.columns:
            logger.warning(f"    Coluna de email não encontrada. Colunas: {list(df_combined.columns[:10])}")
            logger.info(f"    Google Sheets [TOTAL]: {len(df_combined)} leads (sem remoção de duplicatas)")
            return df_combined

        original_len = len(df_combined)
        df_combined = df_combined.drop_duplicates(subset=[email_col], keep='first')
        duplicates = original_len - len(df_combined)
        if duplicates > 0:
            logger.info(f"    Removidas {duplicates} duplicatas entre planilhas")

        logger.info(f"    Google Sheets [TOTAL]: {len(df_combined)} leads únicos")

        return df_combined

    def _load_single_spreadsheet(self, sheets_url: str, start_date: Optional[str], end_date: Optional[str], use_cache: bool, num_sheets: int, training_mode: bool = False) -> pd.DataFrame:
        """
        Carrega leads de uma única planilha do Google Sheets.

        Returns:
            DataFrame normalizado ou None em caso de erro
        """
        # Extrair SHEET_ID da URL
        import re
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheets_url)
        if not match:
            logger.error(f"URL inválida do Google Sheets: {sheets_url}")
            return None
        sheet_id = match.group(1)

        logger.debug(f"   URL: {sheets_url[:50]}...")

        try:
            # HÍBRIDO: Usar gspread APENAS para listar abas/GIDs, curl para baixar dados
            import subprocess
            import tempfile
            import gspread

            # 1. Usar gspread para descobrir todas as abas e seus GIDs (operação rápida)
            logger.debug("    Descobrindo abas da planilha...")
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets.readonly',
                'https://www.googleapis.com/auth/drive.readonly'
            ]
            creds, _ = gauth_default(scopes=scopes)
            gc = gspread.authorize(creds)
            spreadsheet = gc.open_by_url(sheets_url)

            worksheets = spreadsheet.worksheets()
            logger.debug(f"    {len(worksheets)} abas encontradas")

            # Pegar apenas as N primeiras abas (índices 0, 1, ...)
            # Aba [0]: [LF] Pesquisa | Aba [1]: [LF] Pesquisa v2
            abas_pesquisa = worksheets[:num_sheets]
            logger.debug(f"    Usando {len(abas_pesquisa)} aba(s):")
            for idx, ws in enumerate(abas_pesquisa):
                logger.debug(f"      [{idx}] {ws.title} (gid={ws.id})")

            # 2. Baixar dados de cada aba via curl (workaround para gspread.get_all_values() travar)
            dfs_to_combine = []
            tab_names = []

            for idx, ws in enumerate(abas_pesquisa):
                logger.debug(f"    Carregando aba [{idx}]: {ws.title} (gid={ws.id})")
                tab_names.append(ws.title)

                url_aba = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={ws.id}"

                with tempfile.NamedTemporaryFile(mode='w+', suffix='.csv', delete=False) as tmp:
                    result = subprocess.run(
                        ['curl', '-sL', '--max-time', '30', url_aba, '-o', tmp.name],
                        capture_output=True,
                        timeout=35
                    )

                    if result.returncode != 0:
                        stderr_msg = result.stderr.decode().strip() if result.stderr else "(sem mensagem de erro)"
                        logger.error(f"       Curl falhou para aba {ws.title}:")
                        logger.error(f"         Exit code: {result.returncode}")
                        logger.error(f"         Stderr: {stderr_msg}")
                        logger.error(f"         URL: {url_aba}")
                        os.unlink(tmp.name)
                        continue

                    try:
                        # Verificar se arquivo foi baixado e tem conteúdo
                        import os as os_module
                        file_size = os_module.path.getsize(tmp.name)
                        if file_size == 0:
                            logger.error(f"       Arquivo baixado está vazio (0 bytes) para aba {ws.title}")
                            os.unlink(tmp.name)
                            continue

                        logger.debug(f"       Arquivo baixado: {file_size} bytes")
                        df_aba = pd.read_csv(tmp.name, low_memory=False)
                        os.unlink(tmp.name)

                        # Remover duplicatas de colunas
                        df_aba = df_aba.loc[:, ~df_aba.columns.duplicated(keep='first')]
                        logger.debug(f"       {len(df_aba)} linhas, {len(df_aba.columns)} colunas únicas")

                        # Normalizar coluna de data
                        if 'Data' in df_aba.columns:
                            df_aba['Data'] = pd.to_datetime(df_aba['Data'], errors='coerce')
                        elif 'Data do Envio' in df_aba.columns:
                            df_aba['Data'] = pd.to_datetime(df_aba['Data do Envio'], format='%d/%m/%Y %H:%M:%S', errors='coerce')
                            df_aba = df_aba.drop('Data do Envio', axis=1)

                        df_aba = df_aba.reset_index(drop=True)
                        dfs_to_combine.append(df_aba)

                    except Exception as e:
                        logger.warning(f"       Erro ao processar aba {ws.title}: {e}")
                        os.unlink(tmp.name)

            # Combinar ambas as abas
            # Como têm colunas diferentes, concat criará NaN onde não houver match
            # O normalizador (_normalize_leads_dataframe) só usa as colunas que precisa
            if not dfs_to_combine:
                raise ValueError(
                    f"Nenhuma aba pôde ser carregada do Google Sheets!\n"
                    f"Tentativas: {len(abas_pesquisa)} aba(s)\n"
                    f"Sucesso: 0 aba(s)\n"
                    f"Verifique os logs acima para detalhes dos erros de cada aba."
                )

            df = pd.concat(dfs_to_combine, ignore_index=True, sort=False)

            # Verificar e remover duplicatas de colunas no resultado final
            if df.columns.duplicated().any():
                logger.debug(f"    Resultado do concat tem colunas duplicadas, removendo...")
                df = df.loc[:, ~df.columns.duplicated(keep='first')]

            num_abas = len(dfs_to_combine)
            logger.debug(f"    {len(df)} linhas TOTAIS lidas do Google Sheets ({num_abas} aba{'s' if num_abas > 1 else ''} combinada{'s' if num_abas > 1 else ''})")

            # Garantir que coluna Data existe antes de filtrar
            if 'Data' not in df.columns:
                logger.error("    Coluna 'Data' não encontrada no DataFrame")
                return None

            # Filtrar por período se especificado
            if start_date or end_date:
                original_len = len(df)
                if start_date:
                    start_dt = pd.to_datetime(start_date)
                    df = df[df['Data'] >= start_dt]
                if end_date:
                    end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)  # Incluir fim do dia
                    df = df[df['Data'] < end_dt]

                logger.debug(f"    Filtrado por período: {original_len}  {len(df)} leads")

            # Normalizar usando mesma lógica do CSV
            df_normalized = self._normalize_leads_dataframe(df, show_summary=False, training_mode=training_mode)

            # Mostrar resumo final em INFO level
            tab_names_str = ', '.join(tab_names) if len(tab_names) > 1 else tab_names[0]
            logger.info(f"    Google Sheets [{tab_names_str}]: {len(df_normalized)} leads carregados")

            return df_normalized

        except Exception as e:
            logger.error(f" Erro ao carregar do Google Sheets: {e}")
            raise

    def _normalize_leads_dataframe(self, df: pd.DataFrame, show_summary: bool = False, source_info: str = None, training_mode: bool = False) -> pd.DataFrame:
        """
        Normaliza DataFrame de leads (interno - usado por CSV e Sheets).

        Args:
            df: DataFrame bruto com colunas originais
            show_summary: Se True, mostra resumo final em INFO level
            source_info: Informação da fonte para incluir no resumo (ex: "Google Sheets [[LF] Pesquisa]")
            training_mode: Se True, colunas demográficas passam com nomes originais do formulário
                           para a Célula 5 (column_unification) normalizar junto com os arquivos Excel.
                           Se False (produção), normaliza para snake_case.

        Returns:
            DataFrame normalizado
        """
        # Verificar colunas obrigatórias (aceitar 'Data' ou 'Data do Envio')
        missing = []
        for col in self.required_columns:
            if col == 'Data':
                if 'Data' not in df.columns and 'Data do Envio' not in df.columns:
                    missing.append(col)
            elif col not in df.columns:
                missing.append(col)

        if missing:
            raise ValueError(f"Colunas obrigatórias ausentes: {missing}")

        # Renomear 'Data do Envio' para 'Data' se necessário
        if 'Data do Envio' in df.columns and 'Data' not in df.columns:
            df = df.rename(columns={'Data do Envio': 'Data'})

        # Normalizar nomes de colunas
        df_norm = pd.DataFrame()

        # Email (normalizado)
        df_norm['email'] = df['E-mail'].apply(lambda x: normalizar_email(x) if pd.notna(x) else None)

        # Nome
        df_norm['nome'] = df.get('Nome Completo', np.nan)

        # Telefone (normalizado)
        if 'Telefone' in df.columns:
            df_norm['telefone'] = df['Telefone'].apply(
                lambda x: normalizar_telefone_robusto(str(x)) if pd.notna(x) else None
            )
        else:
            df_norm['telefone'] = None

        # Data de captura - inferir formato baseado no primeiro registro válido
        sample_date = df['Data'].dropna().iloc[0] if len(df['Data'].dropna()) > 0 else None

        if sample_date and isinstance(sample_date, str):
            # Detectar formato: se começa com 4 dígitos = YYYY-MM-DD, senão = DD/MM/YYYY
            if sample_date.strip()[0:4].isdigit():
                # Formato ISO: YYYY-MM-DD ou YYYY-MM-DD HH:MM:SS
                df_norm['data_captura'] = pd.to_datetime(df['Data'], errors='coerce')
            else:
                # Formato brasileiro: DD/MM/YYYY
                df_norm['data_captura'] = pd.to_datetime(df['Data'], format='%d/%m/%Y', errors='coerce')
        else:
            # Já é datetime ou fallback
            df_norm['data_captura'] = pd.to_datetime(df['Data'], errors='coerce')

        # Campanha e UTMs
        df_norm['campaign'] = df['Campaign']
        df_norm['source'] = df.get('Source', np.nan)
        df_norm['medium'] = df.get('Medium', np.nan)
        df_norm['term'] = df.get('Term', np.nan)
        df_norm['content'] = df.get('Content', np.nan)

        # Colunas demográficas (perguntas do formulário)
        if training_mode:
            # No treino, as colunas demográficas passam com seus nomes originais do formulário.
            # A Célula 5 (column_unification_refactored.py) é o único responsável por renomear,
            # igual ao que faz com os arquivos Excel. Assim o mapeamento existe em um só lugar.
            cols_ja_consumidas = {
                'E-mail', 'Nome Completo', 'Telefone', 'Data', 'Data do Envio',
                'Campaign', 'Source', 'Medium', 'Content', 'Term',
                'lead_score', 'Faixa', 'Faixa A', 'Faixa B', 'Faixa C', 'Faixa D',
                'Pontuação', 'Score',
            }
            for col in df.columns:
                if col not in cols_ja_consumidas and col not in df_norm.columns:
                    df_norm[col] = df[col]
        else:
            df_norm['genero'] = df.get('genero', np.nan)
            df_norm['idade'] = df.get('idade', np.nan)
            df_norm['ocupacao'] = df.get('o_que_faz_atualmente', np.nan)
            df_norm['faixa_salarial'] = df.get('faixa_salarial', np.nan)
            df_norm['cartao_credito'] = df.get('tem_cartao_credito', np.nan)
            df_norm['interesse_evento'] = df.get('o_que_quer_ver_evento', np.nan)
            df_norm['tem_computador'] = df.get('tem_computador', np.nan)
            df_norm['estudou_programacao'] = df.get('estudou_programacao', np.nan)
            df_norm['pretende_faculdade'] = df.get('fez_faculdade', np.nan)
            df_norm['investiu_curso_online'] = df.get('Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro?', np.nan)
            df_norm['interesse_programacao'] = df.get('O que mais te chama atenção na profissão de Programador?', np.nan)

        # LIMPEZA DE UTMs: Detectar e limpar casos problemáticos

        # 1. Limpar variáveis não substituídas ({{...}})
        template_vars_medium = df_norm['medium'].astype(str).str.contains(r'\{\{', na=False)
        template_vars_campaign = df_norm['campaign'].astype(str).str.contains(r'\{\{', na=False)

        if template_vars_medium.sum() > 0:
            logger.warning(f"    {template_vars_medium.sum()} leads com variáveis não substituídas em 'medium' (removidas)")
            df_norm.loc[template_vars_medium, 'medium'] = np.nan

        if template_vars_campaign.sum() > 0:
            logger.warning(f"    {template_vars_campaign.sum()} leads com variáveis não substituídas em 'campaign' (removidas)")
            df_norm.loc[template_vars_campaign, 'campaign'] = np.nan

        # 2. Identificar leads de outras fontes (não facebook-ads)
        non_facebook = df_norm['source'].notna() & (df_norm['source'] != 'facebook-ads')
        if non_facebook.sum() > 0:
            sources_count = df_norm[non_facebook]['source'].value_counts()
            logger.debug(f"   ℹ  {non_facebook.sum()} leads de outras fontes (não facebook-ads):")
            for source, count in sources_count.head(5).items():
                logger.debug(f"      - {source}: {count} leads")

        # Lead Score e Decil
        df_norm['lead_score'] = df.get('lead_score', np.nan)

        # Extrair decil: PRIORIZAR lead_score (ML) sobre Faixa (legacy)
        if 'lead_score' in df.columns:
            if df['lead_score'].notna().any():
                try:
                    # PRIORITY 1: ML model scores
                    df_norm['decile'] = df['lead_score'].apply(self._assign_decile_from_score)
                    logger.debug(f"    Decis atribuídos via lead_score: {df_norm['decile'].notna().sum()}/{len(df_norm)}")
                except (FileNotFoundError, KeyError) as e:
                    # Durante treino, modelo ativo pode não ter model_path (só mlflow_run_id)
                    # Nesse caso, pular cálculo de decis (não necessário para treino)
                    logger.debug(f"    Pulando cálculo de decis (contexto: treino): {e}")
                    df_norm['decile'] = None
            else:
                df_norm['decile'] = None
        elif 'Faixa' in df.columns:
            if df['Faixa'].notna().any():
                # FALLBACK: Legacy classification
                df_norm['decile'] = df['Faixa']
                logger.debug(f"    Decis atribuídos via Faixa (legacy): {df_norm['decile'].notna().sum()}/{len(df_norm)}")
            else:
                df_norm['decile'] = None
        else:
            df_norm['decile'] = None
            logger.debug(" Nenhuma coluna de score/decil encontrada")

        # Remover linhas com email inválido
        before = len(df_norm)
        df_norm = df_norm[df_norm['email'].notna()].copy()
        after = len(df_norm)

        if before != after:
            logger.debug(f" {before - after} leads removidos (email inválido)")

        # Mostrar resumo final apenas se solicitado
        if show_summary:
            if source_info:
                logger.info(f"    {source_info}: {len(df_norm)} leads carregados")
            else:
                logger.info(f"    {len(df_norm)} leads carregados e normalizados")

        return df_norm

    def load_leads_csv(self, csv_path: str) -> pd.DataFrame:
        """
        Carrega CSV de leads do Google Sheets e normaliza.

        Args:
            csv_path: Caminho para o CSV

        Returns:
            DataFrame normalizado com colunas:
            - email: Email normalizado
            - nome: Nome completo
            - telefone: Telefone normalizado
            - data_captura: Datetime da captura
            - campaign: Nome da campanha
            - lead_score: Score do modelo
            - decile: Decil (D1-D10)
            - source, medium, term, content: UTMs
        """
        logger.info(f" Carregando leads de {csv_path}")

        # Ler CSV
        df = pd.read_csv(csv_path)
        logger.info(f"   {len(df)} linhas lidas do CSV")

        # Normalizar usando método compartilhado
        return self._normalize_leads_dataframe(df)

    def _get_thresholds(self) -> dict:
        """
        Carrega thresholds do JSON do modelo (lazy loading com cache).

        Returns:
            Dict com thresholds por decil no formato:
            {'D1': {'threshold_min': ..., 'threshold_max': ...}, ...}
        """
        if self._thresholds_cache is None:
            import json

            # Carregar modelo ativo do active_model.yaml
            model_path = get_active_model_path()
            metadata_path = model_path / "model_metadata_v1_devclub_rf_temporal_leads_single.json"

            if not metadata_path.exists():
                raise FileNotFoundError(
                    f"Arquivo de metadata do modelo não encontrado: {metadata_path}\n"
                    f"Modelo ativo configurado em: {model_path}"
                )

            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            self._thresholds_cache = metadata['decil_thresholds']['thresholds']
            logger.debug(f" Thresholds carregados do modelo ativo: {model_path.name}")

        return self._thresholds_cache

    def _assign_decile_from_score(self, score) -> Optional[str]:
        """
        Atribui decil baseado no score usando módulo decil_thresholds.

        Usa thresholds do modelo ativo configurado em configs/active_model.yaml

        Args:
            score: Lead score (0-1), pode ser string com vírgula

        Returns:
            Label do decil (D1-D10) ou None se score inválido
        """
        if pd.isna(score):
            return None

        # Convert string to float (handle comma decimal separator)
        if isinstance(score, str):
            try:
                # Replace comma with dot: "0,1572"  "0.1572"
                score_float = float(score.replace(',', '.'))
            except (ValueError, AttributeError):
                logger.warning(f" Score inválido (não numérico): {score}")
                return None
        else:
            score_float = float(score)

        # Validate range
        if not (0 <= score_float <= 1):
            logger.warning(f" Score fora do range [0,1]: {score_float}")
            return None

        # Importar função do módulo existente
        from src.model.decil_thresholds import atribuir_decil_por_threshold

        # Carregar thresholds (com cache)
        thresholds = self._get_thresholds()

        # Atribuir decil usando função do módulo
        return atribuir_decil_por_threshold(score_float, thresholds)


class SalesDataLoader:
    """
    Carrega e normaliza dados de vendas da Guru e TMB.

    Combina dados de ambas as plataformas em formato padronizado.
    """

    def __init__(self):
        pass

    def load_guru_sales(self, guru_paths: List[str], include_canceled: bool = False) -> pd.DataFrame:
        """
        Carrega arquivos Excel de vendas da Guru.

        Colunas esperadas:
        - email contato: Email do comprador
        - nome contato: Nome
        - valor venda: Valor da transação
        - utm_campaign: Campanha de origem
        - data pedido / data aprovacao: Data da compra

        Args:
            guru_paths: Lista de caminhos para arquivos Excel da Guru
            include_canceled: Se True, inclui vendas canceladas (para relatório de fechamento)

        Returns:
            DataFrame normalizado com origem='guru'
        """
        if not guru_paths:
            logger.warning(" Nenhum arquivo Guru fornecido")
            return pd.DataFrame()

        logger.info(f" Carregando vendas Guru de {len(guru_paths)} arquivo(s)")

        all_sales = []

        for path in guru_paths:
            try:
                df = pd.read_excel(path)
                logger.info(f"   {len(df)} vendas de {Path(path).name}")
                all_sales.append(df)
            except Exception as e:
                logger.error(f" Erro ao ler {path}: {e}")
                continue

        if not all_sales:
            logger.warning(" Nenhuma venda Guru carregada")
            return pd.DataFrame()

        # Combinar todos os DataFrames
        df_combined = pd.concat(all_sales, ignore_index=True)

        # Filtrar vendas por status
        if 'status' in df_combined.columns:
            before = len(df_combined)
            if include_canceled:
                # Fechamento: incluir Aprovadas E Canceladas
                df_combined = df_combined[df_combined['status'].isin(['Aprovada', 'Cancelada'])].copy()
                after = len(df_combined)
                if before != after:
                    logger.info(f"   Filtradas {after} vendas (Aprovadas + Canceladas) | Excluídas {before - after} com outros status")
            else:
                # Pós-devoluções: apenas Aprovadas
                df_combined = df_combined[df_combined['status'] == 'Aprovada'].copy()
                after = len(df_combined)
                if before != after:
                    logger.info(f"   Filtradas {after} vendas aprovadas (excluídas {before - after} não aprovadas)")

        # Normalizar colunas
        df_norm = pd.DataFrame()

        # Email (normalizado)
        df_norm['email'] = df_combined['email contato'].apply(
            lambda x: normalizar_email(x) if pd.notna(x) else None
        )

        # Nome
        df_norm['nome'] = df_combined.get('nome contato', np.nan)

        # Telefone (se disponível)
        if 'telefone contato' in df_combined.columns:
            df_norm['telefone'] = df_combined['telefone contato'].apply(
                lambda x: normalizar_telefone_robusto(str(x)) if pd.notna(x) else None
            )
        else:
            df_norm['telefone'] = None

        # Valor da venda
        df_norm['sale_value'] = pd.to_numeric(df_combined.get('valor venda', 0), errors='coerce')

        # Data da venda (usar aprovacao com fallback para pedido)
        # Priorizar 'data aprovacao', mas se for NaN, usar 'data pedido'
        # IMPORTANTE: dayfirst=True para formato brasileiro (DD/MM/YYYY)
        date_aprovacao = pd.to_datetime(df_combined.get('data aprovacao', pd.Series([pd.NaT] * len(df_combined))), errors='coerce', dayfirst=True)
        date_pedido = pd.to_datetime(df_combined.get('data pedido', pd.Series([pd.NaT] * len(df_combined))), errors='coerce', dayfirst=True)

        # Usar data aprovacao, mas preencher NaN com data pedido
        df_norm['sale_date'] = date_aprovacao.fillna(date_pedido)

        # Log de quantas datas vieram de cada fonte
        from_aprovacao = (~date_aprovacao.isna()).sum()
        from_pedido = (date_aprovacao.isna() & ~date_pedido.isna()).sum()
        total_valid = (~df_norm['sale_date'].isna()).sum()
        logger.info(f"    Datas de venda: {total_valid} válidas ({from_aprovacao} de aprovacao, {from_pedido} de pedido)")

        # UTM Campaign
        df_norm['utm_campaign'] = df_combined.get('utm_campaign', np.nan)

        # Origem
        df_norm['origem'] = 'guru'

        # Status (para deduplicação)
        df_norm['status'] = df_combined.get('status', np.nan)

        # Remover vendas sem email ou data
        before = len(df_norm)
        df_norm = df_norm[
            (df_norm['email'].notna()) &
            (df_norm['sale_date'].notna())
        ].copy()
        after = len(df_norm)

        if before != after:
            logger.warning(f" {before - after} vendas Guru removidas (email/data inválido)")

        # Deduplicação: múltiplas transações por pessoa (tentativas de cartão, etc.)
        # Priorizar: Aprovada > Cancelada
        if include_canceled and len(df_norm) > 0:
            before_dedup = len(df_norm)

            # Ordenar por status (Aprovada primeiro) e manter primeira ocorrência de cada email
            df_norm['_status_priority'] = df_norm['status'].map({'Aprovada': 1, 'Cancelada': 2}).fillna(999)
            df_norm = df_norm.sort_values(['email', '_status_priority', 'sale_date'])
            df_norm = df_norm.drop_duplicates(subset=['email'], keep='first')
            df_norm = df_norm.drop(columns=['_status_priority'])

            after_dedup = len(df_norm)
            if before_dedup != after_dedup:
                removed = before_dedup - after_dedup
                logger.info(f"    Deduplicação: {removed} transações duplicadas removidas (1 venda por pessoa)")

        # Drop status column if not needed (manter apenas se include_canceled=True para debug)
        if not include_canceled and 'status' in df_norm.columns:
            df_norm = df_norm.drop(columns=['status'])

        logger.info(f"    {len(df_norm)} vendas Guru carregadas e normalizadas")

        return df_norm

    def _download_tmb_from_gcs(self, report_type: str) -> List[str]:
        """
        Baixa arquivo TMB do Google Cloud Storage baseado no report_type.

        Args:
            report_type: 'fechamento' ou 'pos-devolucoes'

        Returns:
            Lista com caminho local do arquivo baixado, ou lista vazia se falhar
        """
        try:
            from google.cloud import storage
            import tempfile
            import os

            bucket_name = os.environ.get('VALIDATION_REPORTS_BUCKET', 'smart-ads-validation-reports')
            blob_name = f'vendas/tmb_{report_type}.xlsx'

            logger.info(f"   Baixando gs://{bucket_name}/{blob_name}...")

            # Criar arquivo temporário
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
            temp_path = temp_file.name
            temp_file.close()

            # Baixar do bucket
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            if not blob.exists():
                logger.error(f" Arquivo não encontrado: gs://{bucket_name}/{blob_name}")
                return []

            blob.download_to_filename(temp_path)
            logger.info(f"    Arquivo baixado: {blob_name} ({blob.size / 1024:.1f} KB)")

            return [temp_path]

        except Exception as e:
            logger.error(f" Erro ao baixar TMB do Cloud Storage: {e}")
            logger.warning(f"   Certifique-se que o arquivo existe em gs://{bucket_name}/vendas/tmb_{report_type}.xlsx")
            return []

    def load_tmb_sales(self, tmb_paths: List[str] = None, report_type: str = 'fechamento', include_canceled: bool = False) -> pd.DataFrame:
        """
        Carrega arquivos Excel de vendas da TMB.

        Pode carregar de:
        1. Caminhos locais fornecidos em tmb_paths
        2. Google Cloud Storage (se tmb_paths vazio) baseado em report_type

        Colunas esperadas:
        - Cliente Email: Email do comprador
        - Cliente Nome: Nome
        - Ticket (R$): Valor da transação
        - utm_campaign: Campanha de origem
        - Status: Status do pedido (Efetivado ou Cancelado)

        Args:
            tmb_paths: Lista de caminhos para arquivos Excel da TMB (opcional)
            report_type: Tipo de relatório ('fechamento' ou 'pos-devolucoes')
            include_canceled: Se True, inclui vendas canceladas (para relatório de fechamento)

        Returns:
            DataFrame normalizado com origem='tmb'
        """
        # Se não forneceu paths, baixar do Cloud Storage
        if not tmb_paths:
            logger.info(f" Buscando vendas TMB no Cloud Storage (report_type={report_type})...")
            tmb_paths = self._download_tmb_from_gcs(report_type)

            if not tmb_paths:
                logger.warning(" Nenhum arquivo TMB encontrado no Cloud Storage")
                return pd.DataFrame()

        logger.info(f" Carregando vendas TMB de {len(tmb_paths)} arquivo(s)")

        all_sales = []

        for path in tmb_paths:
            try:
                df = pd.read_excel(path)
                logger.info(f"   {len(df)} vendas de {Path(path).name}")
                all_sales.append(df)
            except Exception as e:
                logger.error(f" Erro ao ler {path}: {e}")
                continue

        if not all_sales:
            logger.warning(" Nenhuma venda TMB carregada")
            return pd.DataFrame()

        # Combinar todos os DataFrames
        df_combined = pd.concat(all_sales, ignore_index=True)
        logger.info(f"   Total bruto: {len(df_combined)} linhas (com parcelas)")

        # Filtrar vendas por status
        # Suporta formato com parcelas ('Status Pedido') e formato simples ('Status')
        status_col = 'Status Pedido' if 'Status Pedido' in df_combined.columns else 'Status'
        if status_col in df_combined.columns:
            before = len(df_combined)
            if include_canceled:
                df_combined = df_combined[df_combined[status_col].isin(['Efetivado', 'Cancelado'])].copy()
            else:
                df_combined = df_combined[df_combined[status_col] == 'Efetivado'].copy()
            logger.info(f"   Após filtro de status: {len(df_combined)} linhas (de {before})")

        # Agregar parcelas: formato 'contas a receber' tem 1 linha por parcela
        # Agrupar por Pedido mantendo a primeira ocorrência (mesmo que pipeline de treino)
        if 'Pedido' in df_combined.columns:
            before = len(df_combined)
            df_combined = df_combined.groupby('Pedido', as_index=False).first()
            logger.info(f"   Após agrupamento por Pedido: {len(df_combined)} pedidos únicos (de {before} parcelas)")

        # Normalizar colunas
        df_norm = pd.DataFrame()

        # Email (normalizado)
        email_col = 'Cliente Email' if 'Cliente Email' in df_combined.columns else 'Cliente E-mail'
        df_norm['email'] = df_combined[email_col].apply(
            lambda x: normalizar_email(x) if pd.notna(x) else None
        )

        # Nome
        df_norm['nome'] = df_combined.get('Cliente Nome', np.nan)

        # Telefone (se disponível)
        if 'Telefone' in df_combined.columns or 'Cliente Telefone' in df_combined.columns:
            phone_col = 'Telefone' if 'Telefone' in df_combined.columns else 'Cliente Telefone'
            df_norm['telefone'] = df_combined[phone_col].apply(
                lambda x: normalizar_telefone_robusto(str(x)) if pd.notna(x) else None
            )
        else:
            df_norm['telefone'] = None

        # Valor da venda
        ticket_col = 'Ticket (R$)' if 'Ticket (R$)' in df_combined.columns else 'Ticket'
        df_norm['sale_value'] = pd.to_numeric(df_combined.get(ticket_col, 0), errors='coerce')

        # Data da venda (usar Data Efetivado com fallback para Criado Em)
        # IMPORTANTE: dayfirst=True para formato brasileiro (DD/MM/YYYY)
        date_efetivado = pd.to_datetime(df_combined.get('Data Efetivado', pd.Series([pd.NaT] * len(df_combined))), errors='coerce', dayfirst=True)
        date_criado = pd.to_datetime(df_combined.get('Criado Em', pd.Series([pd.NaT] * len(df_combined))), errors='coerce', dayfirst=True)

        # Usar Data Efetivado, mas preencher NaN com Criado Em
        df_norm['sale_date'] = date_efetivado.fillna(date_criado)

        # Log de quantas datas vieram de cada fonte
        from_efetivado = (~date_efetivado.isna()).sum()
        from_criado = (date_efetivado.isna() & ~date_criado.isna()).sum()
        total_valid = (~df_norm['sale_date'].isna()).sum()
        logger.info(f"    Datas de venda TMB: {total_valid} válidas ({from_efetivado} de efetivado, {from_criado} de criado em)")

        # UTM Campaign
        df_norm['utm_campaign'] = df_combined.get('utm_campaign', np.nan)

        # Grau de risco (específico TMB — formato com parcelas)
        if 'Grau de risco' in df_combined.columns:
            df_norm['Grau de risco'] = df_combined['Grau de risco'].values

        # Origem
        df_norm['origem'] = 'tmb'

        # Remover vendas sem email ou data
        before = len(df_norm)
        df_norm = df_norm[
            (df_norm['email'].notna()) &
            (df_norm['sale_date'].notna())
        ].copy()
        after = len(df_norm)

        if before != after:
            logger.warning(f" {before - after} vendas TMB removidas (email/data inválido)")

        logger.info(f"    {len(df_norm)} vendas TMB carregadas e normalizadas")

        return df_norm

    def load_hotpay_sales(self, hotpay_paths: List[str], include_canceled: bool = False) -> pd.DataFrame:
        """
        Carrega arquivos de vendas da plataforma HotPay.

        Colunas esperadas:
        - Email: Email do comprador
        - Nome: Nome completo
        - DDD + Telefone: Telefone com DDD separado
        - Preço Total: Valor da transação
        - Data de Venda: Data/hora da venda (DD/MM/YYYY HH:MM:SS)
        - Status: 'Aprovado' (ou 'Cancelado')

        Args:
            hotpay_paths: Lista de caminhos para arquivos HotPay (.xls ou .xlsx)
            include_canceled: Se True, inclui vendas canceladas

        Returns:
            DataFrame normalizado com origem='hotpay'
        """
        logger.info(f" Carregando vendas HotPay de {len(hotpay_paths)} arquivo(s)")

        all_sales = []
        for path in hotpay_paths:
            try:
                df = pd.read_excel(path)
                logger.info(f"   {len(df)} linhas de {Path(path).name}")
                all_sales.append(df)
            except Exception as e:
                logger.error(f" Erro ao ler {path}: {e}")
                continue

        if not all_sales:
            logger.warning(" Nenhuma venda HotPay carregada")
            return pd.DataFrame()

        df_combined = pd.concat(all_sales, ignore_index=True)

        # Filtrar por status
        if 'Status' in df_combined.columns:
            before = len(df_combined)
            if include_canceled:
                df_combined = df_combined[df_combined['Status'].isin(['Aprovado', 'Cancelado'])].copy()
            else:
                df_combined = df_combined[df_combined['Status'] == 'Aprovado'].copy()
            logger.info(f"   Após filtro de status: {len(df_combined)} linhas (de {before})")

        if df_combined.empty:
            return pd.DataFrame()

        df_norm = pd.DataFrame()

        # Email
        df_norm['email'] = df_combined['Email'].apply(
            lambda x: normalizar_email(x) if pd.notna(x) else None
        )

        # Nome
        df_norm['nome'] = df_combined.get('Nome', np.nan)

        # Telefone: concatenar DDD + Telefone
        if 'DDD' in df_combined.columns and 'Telefone' in df_combined.columns:
            def _montar_fone(row):
                ddd = str(int(row['DDD'])) if pd.notna(row['DDD']) else ''
                tel = str(int(row['Telefone'])) if pd.notna(row['Telefone']) else ''
                return normalizar_telefone_robusto(ddd + tel) if ddd and tel else None
            df_norm['telefone'] = df_combined.apply(_montar_fone, axis=1)
        else:
            df_norm['telefone'] = None

        # Valor da venda
        df_norm['sale_value'] = pd.to_numeric(df_combined.get('Preço Total', 0), errors='coerce')

        # Data da venda
        df_norm['sale_date'] = pd.to_datetime(
            df_combined.get('Data de Venda', pd.Series([pd.NaT] * len(df_combined))),
            errors='coerce',
            dayfirst=True
        )

        # Origem
        df_norm['origem'] = 'hotpay'

        # Remover sem email ou data
        before = len(df_norm)
        df_norm = df_norm[df_norm['email'].notna() & df_norm['sale_date'].notna()].copy()
        if before != len(df_norm):
            logger.warning(f" {before - len(df_norm)} vendas HotPay removidas (email/data inválido)")

        # Deduplicar por email (manter primeira ocorrência por data)
        before = len(df_norm)
        df_norm = df_norm.sort_values('sale_date').drop_duplicates(subset=['email'], keep='first')
        if before != len(df_norm):
            logger.info(f"   Deduplicação HotPay: {before - len(df_norm)} removidas ({len(df_norm)} únicas)")

        logger.info(f"    {len(df_norm)} vendas HotPay carregadas e normalizadas")
        return df_norm

    def load_guru_sales_from_api(self, start_date: str, end_date: str, save_excel: bool = False, output_path: str = None, include_canceled: bool = False) -> pd.DataFrame:
        """
        Carrega vendas da Guru via API (alternativa aos arquivos Excel).

        Args:
            start_date: Data inicial (YYYY-MM-DD)
            end_date: Data final (YYYY-MM-DD)
            save_excel: Se True, salva cópia em Excel
            output_path: Caminho para salvar Excel (se save_excel=True)
            include_canceled: Se True, inclui vendas canceladas (para relatório de fechamento)

        Returns:
            DataFrame normalizado com origem='guru'
        """
        logger.info(f" Buscando vendas Guru via API ({start_date} a {end_date})")

        # Importar função do extrator
        from src.validation.guru_sales_extractor import fetch_guru_sales_from_api

        # Buscar via API
        df_raw = fetch_guru_sales_from_api(
            start_date=start_date,
            end_date=end_date,
            save_excel=save_excel,
            output_path=output_path
        )

        if df_raw.empty:
            logger.warning(" Nenhuma venda retornada da API Guru")
            return pd.DataFrame()

        # O DataFrame da API já vem com as colunas normalizadas
        # Mas precisamos normalizar para o formato esperado pelo pipeline

        # Filtrar vendas por status
        if 'status' in df_raw.columns:
            before = len(df_raw)
            if include_canceled:
                # Fechamento: incluir Aprovadas E Canceladas
                df_raw = df_raw[df_raw['status'].isin(['Aprovada', 'Cancelada'])].copy()
                after = len(df_raw)
                if before != after:
                    logger.info(f"   Filtradas {after} vendas (Aprovadas + Canceladas) | Excluídas {before - after} com outros status")
            else:
                # Pós-devoluções: apenas Aprovadas
                df_raw = df_raw[df_raw['status'] == 'Aprovada'].copy()
                after = len(df_raw)
                if before != after:
                    logger.info(f"   Filtradas {after} vendas aprovadas (excluídas {before - after} não aprovadas)")

        # Normalizar colunas para o formato do pipeline
        df_norm = pd.DataFrame()

        # Email (normalizado)
        df_norm['email'] = df_raw['email contato'].apply(
            lambda x: normalizar_email(x) if pd.notna(x) else None
        )

        # Nome
        df_norm['nome'] = df_raw.get('nome contato', np.nan)

        # Telefone
        if 'telefone contato' in df_raw.columns:
            df_norm['telefone'] = df_raw['telefone contato'].apply(
                lambda x: normalizar_telefone_robusto(str(x)) if pd.notna(x) else None
            )
        else:
            df_norm['telefone'] = None

        # Valor da venda
        df_norm['sale_value'] = pd.to_numeric(df_raw.get('valor venda', 0), errors='coerce')

        # Data da venda (já vem formatada como string dd/mm/yyyy HH:MM:SS)
        # Converter para datetime com dayfirst=True
        df_norm['sale_date'] = pd.to_datetime(
            df_raw['data aprovacao'].fillna(df_raw['data pedido']),
            format='%d/%m/%Y %H:%M:%S',
            errors='coerce'
        )

        # UTM Campaign
        df_norm['utm_campaign'] = df_raw.get('utm_campaign', np.nan)

        # Origem
        df_norm['origem'] = 'guru'

        # Status (para deduplicação)
        df_norm['status'] = df_raw.get('status', np.nan)

        # Remover vendas sem email ou data
        before = len(df_norm)
        df_norm = df_norm[
            (df_norm['email'].notna()) &
            (df_norm['sale_date'].notna())
        ].copy()
        after = len(df_norm)

        if before != after:
            logger.warning(f" {before - after} vendas Guru API removidas (email/data inválido)")

        # Deduplicação: múltiplas transações por pessoa (tentativas de cartão, etc.)
        # Priorizar: Aprovada > Cancelada
        if include_canceled and len(df_norm) > 0:
            before_dedup = len(df_norm)

            # Ordenar por status (Aprovada primeiro) e manter primeira ocorrência de cada email
            df_norm['_status_priority'] = df_norm['status'].map({'Aprovada': 1, 'Cancelada': 2}).fillna(999)
            df_norm = df_norm.sort_values(['email', '_status_priority', 'sale_date'])
            df_norm = df_norm.drop_duplicates(subset=['email'], keep='first')
            df_norm = df_norm.drop(columns=['_status_priority'])

            after_dedup = len(df_norm)
            if before_dedup != after_dedup:
                removed = before_dedup - after_dedup
                logger.info(f"    Deduplicação: {removed} transações duplicadas removidas (1 venda por pessoa)")

        # Drop status column if not needed (manter apenas se include_canceled=True para debug)
        if not include_canceled and 'status' in df_norm.columns:
            df_norm = df_norm.drop(columns=['status'])

        return df_norm

    def combine_sales(self, guru_df: pd.DataFrame = None, tmb_df: pd.DataFrame = None,
                     hotpay_df: pd.DataFrame = None,
                     guru_paths: List[str] = None, tmb_paths: List[str] = None,
                     hotpay_paths: List[str] = None,
                     report_type: str = 'fechamento', include_canceled: bool = False) -> pd.DataFrame:
        """
        Combina vendas da Guru, TMB e HotPay em um único DataFrame.

        Args:
            guru_df: DataFrame já carregado da Guru (opcional)
            tmb_df: DataFrame já carregado da TMB (opcional)
            hotpay_df: DataFrame já carregado da HotPay (opcional)
            guru_paths: Caminhos para arquivos Guru (se guru_df não fornecido)
            tmb_paths: Caminhos para arquivos TMB (se tmb_df não fornecido)
            hotpay_paths: Caminhos para arquivos HotPay (se hotpay_df não fornecido)
            report_type: Tipo de relatório ('fechamento' ou 'pos-devolucoes') para buscar TMB no GCS
            include_canceled: Se True, inclui vendas canceladas da Guru (para relatório de fechamento)

        Returns:
            DataFrame combinado e deduplicado (prioriza Guru em caso de conflito)
        """
        logger.info(" Combinando vendas Guru + TMB + HotPay")

        # Carregar se necessário
        if guru_df is None and guru_paths:
            guru_df = self.load_guru_sales(guru_paths, include_canceled=include_canceled)
        if tmb_df is None and tmb_paths is not None:
            # Se tmb_paths fornecido (pode ser lista vazia ou com arquivos)
            tmb_df = self.load_tmb_sales(tmb_paths, report_type=report_type, include_canceled=include_canceled)
        elif tmb_df is None and tmb_paths is None:
            # Se tmb_paths é None, tentar buscar do GCS
            tmb_df = self.load_tmb_sales(tmb_paths=None, report_type=report_type, include_canceled=include_canceled)
        if hotpay_df is None and hotpay_paths:
            hotpay_df = self.load_hotpay_sales(hotpay_paths, include_canceled=include_canceled)

        # Combinar DataFrames
        dfs = []
        if guru_df is not None and len(guru_df) > 0:
            dfs.append(guru_df)
        if tmb_df is not None and len(tmb_df) > 0:
            dfs.append(tmb_df)
        if hotpay_df is not None and len(hotpay_df) > 0:
            dfs.append(hotpay_df)

        if not dfs:
            logger.warning(" Nenhuma venda para combinar")
            return pd.DataFrame()

        combined = pd.concat(dfs, ignore_index=True)

        # Deduplicar (priorizar Guru se mesmo email+data)
        # Ordenar por origem (guru primeiro) e remover duplicatas
        combined['_priority'] = combined['origem'].apply(lambda x: 0 if x == 'guru' else 1)
        combined = combined.sort_values('_priority')

        before = len(combined)
        before_guru = len(combined[combined['origem'] == 'guru'])
        before_tmb = len(combined[combined['origem'] == 'tmb'])

        # Identificar duplicatas antes de remover
        duplicates = combined[combined.duplicated(subset=['email', 'sale_date'], keep=False)]

        combined = combined.drop_duplicates(subset=['email', 'sale_date'], keep='first')
        combined = combined.drop(columns=['_priority'])
        after = len(combined)

        if before != after:
            logger.info(f"    Deduplicação de vendas:")
            logger.info(f"      Antes: {before} vendas (Guru: {before_guru}, TMB: {before_tmb})")
            logger.info(f"      Duplicatas encontradas: {before - after} vendas com mesmo email+data")
            logger.info(f"      Depois: {after} vendas únicas")

            # Mostrar alguns exemplos de duplicatas (primeiras 3)
            if len(duplicates) > 0:
                logger.info(f"       Exemplos de duplicatas (primeiras {min(3, len(duplicates)//2)}):")
                dup_emails = duplicates['email'].unique()[:3]
                for email in dup_emails:
                    dup_rows = duplicates[duplicates['email'] == email]
                    if len(dup_rows) > 1:
                        origins = ', '.join(dup_rows['origem'].tolist())
                        date = dup_rows['sale_date'].iloc[0].strftime('%Y-%m-%d') if pd.notna(dup_rows['sale_date'].iloc[0]) else 'sem data'
                        logger.info(f"          {email[:20]}... ({date})  {origins}")

        logger.info(f"    {len(combined)} vendas únicas combinadas")
        logger.info(f"      Guru: {len(combined[combined['origem'] == 'guru'])}")
        logger.info(f"      TMB: {len(combined[combined['origem'] == 'tmb'])}")
        logger.info(f"      HotPay: {len(combined[combined['origem'] == 'hotpay'])}")

        return combined


class CAPILeadDataLoader:
    """
    Carrega leads do banco CAPI (PostgreSQL) via API.

    Combina leads do banco CAPI com leads da pesquisa do Google Sheets,
    priorizando a pesquisa (que tem lead_score) mas adicionando leads
    extras do CAPI que não responderam a pesquisa.
    """

    def __init__(self, api_url: str = "https://smart-ads-api-12955519745.us-central1.run.app"):
        self.api_url = api_url
        self._thresholds_cache = None

    def load_capi_leads(
        self,
        start_date: str,
        end_date: str,
        emails_filter: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Carrega leads do banco CAPI via API.

        Args:
            start_date: Data início (YYYY-MM-DD)
            end_date: Data fim (YYYY-MM-DD)
            emails_filter: Lista de emails específicos (opcional)

        Returns:
            DataFrame com leads do CAPI normalizados
        """
        import requests

        logger.info(f" Carregando leads do banco CAPI ({start_date} a {end_date})")

        if emails_filter:
            # Buscar emails específicos
            url = f"{self.api_url}/webhook/lead_capture/by_emails"
            payload = {
                "emails": emails_filter,
                "start_date": start_date,
                "end_date": end_date
            }
            response = requests.post(url, json=payload, timeout=60)
        else:
            # Buscar todos do período (precisaria criar endpoint para isso)
            # Por enquanto, vamos usar a abordagem de buscar emails específicos
            raise NotImplementedError("Busca de todos os leads do período ainda não implementada")

        if response.status_code != 200:
            logger.error(f" Erro ao buscar leads CAPI: {response.status_code}")
            return pd.DataFrame()

        result = response.json()
        leads_data = result.get('leads', [])

        if not leads_data:
            logger.info("    Nenhum lead encontrado no CAPI")
            return pd.DataFrame()

        # Converter para DataFrame
        df = pd.DataFrame(leads_data)

        # Normalizar para formato padrão
        df_norm = pd.DataFrame()
        df_norm['email'] = df['email'].apply(lambda x: normalizar_email(x) if pd.notna(x) else None)
        df_norm['nome'] = df.get('name', np.nan)
        df_norm['telefone'] = df.get('phone', np.nan).apply(
            lambda x: normalizar_telefone_robusto(str(x)) if pd.notna(x) else None
        )
        df_norm['data_captura'] = pd.to_datetime(df['created_at'], errors='coerce')
        df_norm['campaign'] = df.get('utm_campaign', np.nan)
        df_norm['source'] = df.get('utm_source', np.nan)
        df_norm['medium'] = df.get('utm_medium', np.nan)
        df_norm['term'] = df.get('utm_term', np.nan)
        df_norm['content'] = df.get('utm_content', np.nan)
        df_norm['lead_score'] = np.nan  # CAPI não tem score
        df_norm['decile'] = None  # CAPI não tem decil
        df_norm['source_type'] = 'capi'  # Marcar origem

        # Remover leads sem email
        before = len(df_norm)
        df_norm = df_norm[df_norm['email'].notna()].copy()
        after = len(df_norm)

        if before != after:
            logger.info(f"    {before - after} leads removidos (email inválido)")

        logger.info(f"    {len(df_norm)} leads CAPI carregados")
        logger.info(f"   UTM válida: {df_norm['campaign'].notna().sum()}/{len(df_norm)} ({df_norm['campaign'].notna().sum()/len(df_norm)*100:.1f}%)")

        return df_norm

    def load_combined_leads(
        self,
        csv_path: str,
        start_date: str,
        end_date: str
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Carrega leads combinando Pesquisa (Google Sheets) + CAPI (PostgreSQL).

        Estratégia:
        1. Carrega leads da pesquisa (tem lead_score e decil)
        2. Carrega leads do CAPI que NÃO estão na pesquisa
        3. Combina priorizando pesquisa para emails duplicados

        Args:
            csv_path: Caminho do CSV da pesquisa
            start_date: Data início do período (YYYY-MM-DD)
            end_date: Data fim do período (YYYY-MM-DD)

        Returns:
            Tuple (DataFrame combinado, Dict com estatísticas das fontes)

            Estatísticas retornadas:
            - survey_leads: int - Total de leads da pesquisa no período
            - capi_leads_total: int - Total de leads no banco CAPI no período
            - capi_leads_extras: int - Leads do CAPI que não estão na pesquisa
        """
        logger.info(" Combinando leads Pesquisa + CAPI")

        # 1. Carregar leads de TODOS os arquivos de pesquisa
        from glob import glob

        # Buscar todos os arquivos Pesquisa*.csv no diretório
        leads_dir = Path(csv_path).parent
        pesquisa_pattern = str(leads_dir / '*Pesquisa*.csv')
        pesquisa_files = sorted(glob(pesquisa_pattern))

        logger.info(f"    Encontrados {len(pesquisa_files)} arquivos de pesquisa:")
        for f in pesquisa_files:
            logger.info(f"      - {Path(f).name}")

        survey_loader = LeadDataLoader()
        survey_dfs = []

        for pesquisa_file in pesquisa_files:
            try:
                df = survey_loader.load_leads_csv(pesquisa_file)
                df['source_type'] = 'survey'
                df['survey_file'] = Path(pesquisa_file).name
                survey_dfs.append(df)
                logger.info(f"    {Path(pesquisa_file).name}: {len(df)} leads")
            except Exception as e:
                logger.warning(f"    Erro ao carregar {Path(pesquisa_file).name}: {e}")

        if not survey_dfs:
            raise ValueError("Nenhum arquivo de pesquisa foi carregado com sucesso")

        # Combinar todos os DataFrames de pesquisa
        survey_df = pd.concat(survey_dfs, ignore_index=True)

        # Remover duplicatas (mesmo email + data_captura)
        before_dedup = len(survey_df)
        survey_df = survey_df.drop_duplicates(subset=['email', 'data_captura'], keep='first')
        after_dedup = len(survey_df)

        if before_dedup != after_dedup:
            logger.info(f"    Removidas {before_dedup - after_dedup} duplicatas entre arquivos")

        logger.info(f"    Total Pesquisa combinada: {len(survey_df)} leads únicos")

        # 2. Filtrar por período
        from src.validation.matching import filter_by_period
        from datetime import datetime

        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')

        survey_period = filter_by_period(survey_df, start_dt, end_dt, date_col='data_captura')
        survey_emails = set(survey_period[survey_period['email'].notna()]['email'].unique())

        logger.info(f"    Pesquisa (período): {len(survey_period)} leads, {len(survey_emails)} emails únicos")

        # 3. Buscar TODOS os leads do CAPI no período (Railway PostgreSQL)
        logger.info("    Buscando leads no CAPI (Railway)...")

        try:
            import pg8000.native

            railway_conn = pg8000.native.Connection(
                host=os.environ.get('RAILWAY_DB_HOST', 'shortline.proxy.rlwy.net'),
                port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
                database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
                user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
                password=os.environ['RAILWAY_DB_PASSWORD'],
            )

            rows = railway_conn.run(
                """
                SELECT email, "nomeCompleto", telefone,
                       campaign, medium, source, content, term,
                       "leadScore", decil, fbc, fbp, "createdAt"
                FROM "Lead"
                WHERE "createdAt" >= :start_date
                  AND "createdAt" <  :end_date_excl
                ORDER BY "createdAt" DESC
                LIMIT 10000
                """,
                start_date=start_date,
                end_date_excl=(
                    pd.to_datetime(end_date) + pd.Timedelta(days=1)
                ).strftime('%Y-%m-%d'),
            )
            railway_conn.close()

            capi_leads_data = [
                {
                    'email':        r[0],
                    'name':         r[1],
                    'phone':        r[2],
                    'utm_campaign': r[3],
                    'utm_medium':   r[4],
                    'utm_source':   r[5],
                    'utm_content':  r[6],
                    'utm_term':     r[7],
                    'lead_score':   float(r[8]) if r[8] is not None else None,
                    'decil':        f"D{r[9]}" if r[9] is not None else None,
                    'fbc':          r[10],
                    'fbp':          r[11],
                    'created_at':   r[12],
                }
                for r in rows
            ]
            logger.info(f"    CAPI: {len(capi_leads_data)} leads encontrados")

            if capi_leads_data:
                    # Converter para DataFrame
                    capi_df = pd.DataFrame(capi_leads_data)

                    # Normalizar
                    capi_norm = pd.DataFrame()
                    capi_norm['email'] = capi_df['email'].apply(lambda x: normalizar_email(x) if pd.notna(x) else None)
                    capi_norm['nome'] = capi_df.get('name', np.nan)
                    capi_norm['telefone'] = capi_df.get('phone', np.nan).apply(
                        lambda x: normalizar_telefone_robusto(str(x)) if pd.notna(x) else None
                    )
                    capi_norm['data_captura'] = pd.to_datetime(capi_df['created_at'], errors='coerce')
                    capi_norm['campaign'] = capi_df.get('utm_campaign', np.nan)
                    capi_norm['source'] = capi_df.get('utm_source', np.nan)
                    capi_norm['medium'] = capi_df.get('utm_medium', np.nan)
                    capi_norm['term'] = capi_df.get('utm_term', np.nan)
                    capi_norm['content'] = capi_df.get('utm_content', np.nan)
                    capi_norm['lead_score'] = capi_df.get('lead_score', np.nan)
                    capi_norm['decile'] = capi_df.get('decil', None)
                    capi_norm['source_type'] = 'capi'

                    # Remover leads sem email
                    capi_norm = capi_norm[capi_norm['email'].notna()].copy()

                    # FILTRO: Manter apenas leads com campaign_id válido da Meta
                    # Extrai ID de campanha do utm_campaign (padrão: "...|120234062599950390")
                    def extract_campaign_id_meta(utm_campaign):
                        """Extrai campaign_id Meta do utm_campaign (últimos 15+ dígitos após |)"""
                        if pd.isna(utm_campaign):
                            return None
                        match = re.search(r'\|(\d{15,})$', str(utm_campaign))
                        return match.group(1)[:15] if match else None

                    total_antes_filtro = len(capi_norm)
                    emails_antes_filtro = len(capi_norm['email'].unique())

                    capi_norm['campaign_id_meta'] = capi_norm['campaign'].apply(extract_campaign_id_meta)
                    capi_norm = capi_norm[capi_norm['campaign_id_meta'].notna()].copy()

                    total_depois_filtro = len(capi_norm)
                    emails_depois_filtro = len(capi_norm['email'].unique())
                    removidos = total_antes_filtro - total_depois_filtro
                    emails_removidos = emails_antes_filtro - emails_depois_filtro

                    if removidos > 0:
                        logger.info(f"    Filtrado: {removidos} registros sem campaign_id Meta ({emails_removidos} emails únicos removidos)")
                        logger.info(f"      Restaram: {total_depois_filtro} registros com campaign_id Meta ({emails_depois_filtro} emails únicos)")

                    # ENRIQUECER leads da pesquisa que não têm UTM com dados do CAPI
                    ENABLE_CAPI_ENRICHMENT = True

                    if ENABLE_CAPI_ENRICHMENT:
                        survey_without_utm = survey_period[
                            survey_period['source'].isna() |
                            (survey_period['source'] != 'facebook-ads')
                        ].copy()

                        if len(survey_without_utm) > 0 and len(capi_norm) > 0:
                            logger.info(f"    Tentando enriquecer {len(survey_without_utm)} leads da pesquisa sem UTM usando dados do CAPI...")

                            # Criar mapeamento email  dados CAPI (pegar primeiro registro de cada email)
                            capi_by_email = capi_norm[capi_norm['campaign'].notna()].groupby('email').first()

                            enriched_count = 0
                            matched_emails = []

                            for idx in survey_without_utm.index:
                                email = survey_period.at[idx, 'email']
                                if email in capi_by_email.index:
                                    # Enriquecer com dados do CAPI
                                    capi_data = capi_by_email.loc[email]
                                    survey_period.at[idx, 'campaign'] = capi_data['campaign']
                                    survey_period.at[idx, 'source'] = capi_data['source']
                                    survey_period.at[idx, 'medium'] = capi_data['medium']
                                    if 'campaign_id_meta' in capi_data.index and pd.notna(capi_data['campaign_id_meta']):
                                        survey_period.at[idx, 'campaign_id_meta'] = capi_data['campaign_id_meta']
                                    enriched_count += 1
                                    matched_emails.append(email)

                            logger.info(f"    Enriquecidos {enriched_count} leads da pesquisa com UTMs do CAPI ({enriched_count/len(survey_without_utm)*100:.1f}%)")

                            if enriched_count > 0:
                                # Mostrar alguns exemplos
                                logger.info(f"    Exemplos de leads enriquecidos (primeiros 3):")
                                for email in matched_emails[:3]:
                                    idx = survey_period[survey_period['email'] == email].index[0]
                                    campaign = survey_period.at[idx, 'campaign']
                                    campaign_display = campaign[:60] if pd.notna(campaign) and len(str(campaign)) > 60 else campaign
                                    logger.info(f"       {email[:30]}...  {campaign_display}")
                        else:
                            if len(survey_without_utm) == 0:
                                logger.info(f"    Todos os leads da pesquisa já possuem UTM válida")
                    else:
                        logger.info(f"     CAPI enrichment DESABILITADO para teste")

                    # Filtrar APENAS leads do CAPI que NÃO estão na pesquisa
                    capi_emails = set(capi_norm['email'].unique())
                    capi_extras = capi_emails - survey_emails
                    capi_extra_leads = capi_norm[capi_norm['email'].isin(capi_extras)].copy()

                    logger.info(f"    Leads extras do CAPI (não estão na pesquisa): {len(capi_extra_leads)}")
                    logger.info(f"   UTM válida: {capi_extra_leads['campaign'].notna().sum()}/{len(capi_extra_leads)} ({capi_extra_leads['campaign'].notna().sum()/len(capi_extra_leads)*100:.1f}%)" if len(capi_extra_leads) > 0 else "")

                    # 4. Combinar pesquisa + extras do CAPI
                    # IMPORTANTE: Contar pessoas únicas (emails únicos) no CAPI, não total de eventos
                    # NOTA: Agora conta apenas emails com campaign_id Meta válido
                    capi_unique_emails = len(capi_norm['email'].unique())
                    stats = {
                        'survey_leads': len(survey_period),
                        'capi_leads_total': capi_unique_emails,  # Pessoas únicas no CAPI
                        'capi_leads_extras': len(capi_extra_leads)
                    }

                    if len(capi_extra_leads) > 0:
                        combined = pd.concat([survey_period, capi_extra_leads], ignore_index=True)
                        logger.info(f"    Total combinado: {len(combined)} leads ({len(survey_period)} pesquisa + {len(capi_extra_leads)} CAPI)")
                        return combined, stats
                    else:
                        logger.info(f"    Total: {len(survey_period)} leads (apenas pesquisa)")
                        return survey_period, stats
            else:
                logger.info("    Nenhum lead encontrado no CAPI")
                stats = {
                    'survey_leads': len(survey_period),
                    'capi_leads_total': 0,
                    'capi_leads_extras': 0
                }
                return survey_period, stats
        except Exception as e:
            logger.warning(f"    Erro ao conectar com Railway: {str(e)}")
            logger.info(f"    Usando apenas pesquisa: {len(survey_period)} leads")
            stats = {
                'survey_leads': len(survey_period),
                'capi_leads_total': 0,
                'capi_leads_extras': 0
            }
            return survey_period, stats

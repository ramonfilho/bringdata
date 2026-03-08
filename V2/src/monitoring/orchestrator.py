"""
Orquestrador central de monitoramento.

Coordena execução de todos os monitors e consolida alertas.
"""

import logging
import pandas as pd
from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
import sys
import os
from datetime import datetime

from .data_quality import DataQualityMonitor
from .operational_monitor import OperationalMonitor
from .capi_monitor import CAPIQualityMonitor
from .models import Alert

# Importar unificação de Medium (mesmo processamento que treino e produção)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_processing.medium_unification import unify_medium_columns

logger = logging.getLogger(__name__)


class Tee:
    """Duplica output para console e arquivo (como comando tee do Unix)."""
    def __init__(self, file_path):
        self.terminal = sys.stdout
        self.log = open(file_path, 'w', encoding='utf-8')

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()  # Força escrita imediata

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def close(self):
        self.log.close()


def setup_monitoring_logging():
    """Configura redirecionamento automático de output para arquivo timestampado."""
    # Garantir que diretório outputs/monitoring existe
    outputs_dir = os.path.join(os.path.dirname(__file__), '../../outputs/monitoring')
    outputs_dir = os.path.abspath(outputs_dir)  # Normalizar path
    os.makedirs(outputs_dir, exist_ok=True)

    # Gerar timestamp no formato YYYYMMDD_HHMMSS
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = os.path.join(outputs_dir, f'monitoring_{timestamp}.log')

    # Redirecionar stdout e stderr para Tee
    tee = Tee(log_path)
    sys.stdout = tee
    sys.stderr = tee

    # Configurar logging para usar o Tee também
    # Remover handlers existentes para evitar conflito
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Adicionar handler que escreve em stdout (que agora é o Tee)
    # Isso evita ter 2 file handles no mesmo arquivo
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    print(f" Output do monitoramento será salvo em: {log_path}\n")
    return log_path


class MonitoringOrchestrator:
    """
    Orquestrador central que executa todos os monitors e consolida alertas.
    """

    def __init__(self, model_path: str, db: Session):
        """
        Args:
            model_path: Caminho para pasta do modelo ativo
            db: Sessão SQLAlchemy do PostgreSQL
        """
        self.model_path = model_path
        self.db = db

        # Inicializar monitors
        self.monitors = {
            'data_quality': DataQualityMonitor(model_path),
            'operational': OperationalMonitor(db),
            'capi_quality': CAPIQualityMonitor(db)
        }

    def run_daily_check(self, leads_data: List[Dict]) -> Dict:
        """
        Executa check diário completo.

        Args:
            leads_data: Lista de dicts com dados do Sheets (últimas 24h)

        Returns:
            {
                'total_alerts': int,
                'alerts_by_severity': {'HIGH': 2, 'MEDIUM': 1, 'LOW': 2},
                'alerts_by_category': {'data_quality': 3, 'operational': 1, 'capi_quality': 1},
                'alerts': [Alert.to_dict(), ...]
            }
        """
        # Configurar logging automático para arquivo
        log_path = setup_monitoring_logging()

        all_alerts_dict = []

        # 1. Data Quality (usa JSON do Sheets)
        if leads_data:
            df = pd.DataFrame(leads_data)

            # Logar range de leads analisados (para facilitar debug com arquivo local)
            primeiro_email = df.iloc[0].get('E-mail', 'N/A') if len(df) > 0 else 'N/A'
            primeiro_data = df.iloc[0].get('Data', 'N/A') if len(df) > 0 else 'N/A'
            ultimo_email = df.iloc[-1].get('E-mail', 'N/A') if len(df) > 0 else 'N/A'
            ultimo_data = df.iloc[-1].get('Data', 'N/A') if len(df) > 0 else 'N/A'

            logger.info(f" Primeiro lead: {primeiro_email} (Data: {primeiro_data})")
            logger.info(f" Último lead: {ultimo_email} (Data: {ultimo_data})")

            # Aplicar unificação de UTM Source/Term (mesmo processamento que produção)
            # Isso garante que 'fb', 'youtube', etc sejam normalizados para 'outros'
            if 'Source' in df.columns or 'Term' in df.columns:
                from data_processing.utm_unification import unify_utm_columns
                utm_antes = df['Source'].nunique() if 'Source' in df.columns else 0
                df = unify_utm_columns(df)
                utm_depois = df['Source'].nunique() if 'Source' in df.columns else 0
                logger.info(f" UTM unificado: Source {utm_antes}  {utm_depois} categorias únicas")

            # Aplicar unificação de Medium (mesmo processamento que treino e produção)
            # Isso garante que 'ABERTO | AD0022' seja normalizado para 'Aberto'
            if 'Medium' in df.columns:
                medium_antes = df['Medium'].nunique()
                df = unify_medium_columns(df)
                medium_depois = df['Medium'].nunique()
                logger.info(f" Medium unificado: {medium_antes}  {medium_depois} categorias únicas")

            # Renomear colunas longas (investiu_curso_online, interesse_programacao)
            from data_processing.preprocessing import rename_long_column_names
            df = rename_long_column_names(df)

            # Aplicar unificação de categorias (mesmo processamento que produção)
            # Limpa e normaliza valores das categorias
            from data_processing.category_unification import unificar_categorias_completo
            df = unificar_categorias_completo(df)
            logger.info(f" Categorias unificadas")

            # Preservar colunas de score/decil ANTES de remover (necessário para monitoramento)
            # Essas colunas vêm do Google Sheets (pipeline de produção já atribuiu)
            decil_col = df['decil'].copy() if 'decil' in df.columns else None
            lead_score_col = df['lead_score'].copy() if 'lead_score' in df.columns else None

            # Remover colunas de score/faixa (mesmo processamento que produção)
            # Remove: Pontuação, Score, Faixa, Faixa A-D, lead_score, decil
            from data_processing.preprocessing import clean_columns
            colunas_antes_score = len(df.columns)
            df = clean_columns(df)
            colunas_depois_score = len(df.columns)
            score_removidos = colunas_antes_score - colunas_depois_score
            logger.info(f" Colunas de score/faixa removidas: {score_removidos} (total: {colunas_depois_score})")

            # Restaurar colunas de score/decil APÓS limpeza (para monitoramento de distribuição)
            if decil_col is not None:
                df['decil'] = decil_col
                logger.info(f" Coluna 'decil' preservada para monitoramento (distribuição: {df['decil'].value_counts().sort_index().to_dict()})")
            if lead_score_col is not None:
                # Converter lead_score para float (pode vir como string com vírgula do Google Sheets)
                if lead_score_col.dtype == 'object':
                    # Substituir vírgula por ponto e tratar strings vazias
                    lead_score_col = lead_score_col.str.replace(',', '.').replace('', None)
                    lead_score_col = pd.to_numeric(lead_score_col, errors='coerce')
                df['lead_score'] = lead_score_col
                valid_scores = df['lead_score'].notna().sum()
                logger.info(f" Coluna 'lead_score' preservada para monitoramento ({valid_scores}/{len(df)} válidos, média: {df['lead_score'].mean():.4f})")

            # Remover features de campanha (mesmo processamento que produção)
            # Remove: Campaign, Content, e colunas vazias/problemáticas
            from data_processing.preprocessing import remove_campaign_features
            colunas_antes_campaign = len(df.columns)
            df = remove_campaign_features(df)
            colunas_depois_campaign = len(df.columns)
            campaign_removidos = colunas_antes_campaign - colunas_depois_campaign
            logger.info(f" Features de campanha removidas: {campaign_removidos} (total: {colunas_depois_campaign})")

            # Remover campos técnicos (mesmo processamento que produção)
            # Remove: Remote IP, User Agent, fbc, fbp, cidade, estado, pais, cep, externalid, Page URL, etc
            from data_processing.preprocessing import remove_technical_fields
            colunas_antes_tech = len(df.columns)
            df = remove_technical_fields(df)
            colunas_depois_tech = len(df.columns)
            campos_removidos = colunas_antes_tech - colunas_depois_tech
            logger.info(f" Campos técnicos removidos: {campos_removidos} (total: {colunas_depois_tech})")

            # Aplicar feature engineering (mesmo processamento que produção)
            # Cria: nome_valido, email_valido, telefone_valido, telefone_comprimento, nome_tem_sobrenome
            from features.engineering import create_derived_features
            colunas_antes_fe = len(df.columns)
            df = create_derived_features(df)
            colunas_depois_fe = len(df.columns)
            saldo_fe = colunas_depois_fe - colunas_antes_fe
            logger.info(f" Features derivadas criadas: {saldo_fe:+d} colunas (total: {colunas_depois_fe})")

            all_alerts_dict.extend(self.monitors['data_quality'].check(df))

        # 2. Operational (usa PostgreSQL)
        all_alerts_dict.extend(self.monitors['operational'].check())

        # 3. CAPI Quality (usa PostgreSQL)
        all_alerts_dict.extend(self.monitors['capi_quality'].check())

        # Converter para objetos Alert
        alerts = [Alert.from_dict(alert_dict) for alert_dict in all_alerts_dict]

        # Gerar sumário
        summary = self._generate_summary(alerts)

        # NOVO: Gerar métricas do funil completo
        funnel_metrics = self._generate_funnel_metrics(leads_data, df if leads_data else None)

        # NOVO: Calcular métricas de qualidade dos leads por período
        lead_quality_metrics = self._calculate_lead_quality_metrics()

        # NOVO: Gerar sumário crítico consolidado
        critical_summary = self._generate_critical_summary(alerts, funnel_metrics)

        # Mensagem de conclusão
        logger.info(f"\n Monitoramento concluído!")
        logger.info(f" Log completo salvo em: {log_path}\n")

        return {
            'total_alerts': len(alerts),
            'alerts_by_severity': summary['by_severity'],
            'alerts_by_category': summary['by_category'],
            'alerts': [alert.to_dict() for alert in alerts],
            'funnel_metrics': funnel_metrics,
            'lead_quality_metrics': lead_quality_metrics,
            'critical_summary': critical_summary
        }

    def _count_sheet_tab2_responses(self, lookback_time) -> int:
        """
        Conta número de respostas na segunda aba da planilha (últimas 24h).

        Args:
            lookback_time: Datetime UTC para filtrar últimas 24h

        Returns:
            Número de linhas na segunda aba (últimas 24h)
        """
        import gspread
        from google.auth import default as gauth_default
        from datetime import timezone, timedelta

        try:
            # Importar URL da planilha do app.py
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../api'))
            from app import GOOGLE_SHEETS_URL

            if not GOOGLE_SHEETS_URL:
                logger.warning("  GOOGLE_SHEETS_URL não configurado, pulando contagem aba 2")
                return 0

            # Autenticar
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets.readonly',
                'https://www.googleapis.com/auth/drive.readonly'
            ]
            creds, _ = gauth_default(scopes=scopes)
            gc = gspread.authorize(creds)

            # Abrir segunda aba (índice 1)
            spreadsheet = gc.open_by_url(GOOGLE_SHEETS_URL)
            worksheet = spreadsheet.get_worksheet(1)  # Segunda aba

            if not worksheet:
                logger.warning("  Segunda aba não encontrada na planilha")
                return 0

            # Buscar todos os dados
            valores = worksheet.get_all_values()
            if len(valores) <= 1:  # Só header ou vazio
                return 0

            headers = valores[0]
            dados = valores[1:]

            # Tentar filtrar por data (últimas 24h)
            date_columns = [i for i, col in enumerate(headers) if any(
                term in col.lower() for term in ['data', 'timestamp', 'hora', 'date', 'time', 'envio']
            )]

            if date_columns and dados:
                date_col_idx = date_columns[0]
                count = 0

                for row in dados:
                    if date_col_idx < len(row) and row[date_col_idx]:
                        try:
                            # Parse com formato brasileiro (DD/MM/YYYY HH:MM:SS)
                            row_date = pd.to_datetime(row[date_col_idx], format='%d/%m/%Y %H:%M:%S', errors='coerce')
                            if pd.notna(row_date):
                                # Aba 2 usa formato brasileiro (DD/MM/YYYY) → datas em BRT.
                                # Atribuir BRT (não UTC) para comparar corretamente com lookback_time.
                                if row_date.tzinfo is None:
                                    brt = timezone(timedelta(hours=-3))
                                    row_date = row_date.replace(tzinfo=brt)

                                if row_date >= lookback_time:
                                    count += 1
                        except:
                            continue

                return count
            else:
                # Sem coluna de data, avisar
                logger.warning(f"     Sem coluna de data na aba 2, retornando 0")
                return 0

        except Exception as e:
            logger.warning(f"  Erro ao contar aba 2: {e}")
            return 0

    def _calculate_lead_quality_metrics(self) -> Dict:
        """
        Calcula métricas de qualidade dos leads em diferentes períodos.

        Acessa Google Sheets e calcula:
        - Score Médio (Histórico, Último mês, Última semana, Últimas 24h)
        - % em D9 (4 períodos)
        - % em D10 (4 períodos)

        Returns:
            Dict com métricas por período
        """
        import gspread
        from google.auth import default as gauth_default
        from datetime import datetime, timedelta, timezone

        try:
            # Importar URL da planilha
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../api'))
            from app import GOOGLE_SHEETS_URL

            if not GOOGLE_SHEETS_URL:
                logger.warning(" GOOGLE_SHEETS_URL não configurado")
                return {}

            # Autenticar
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets.readonly',
                'https://www.googleapis.com/auth/drive.readonly'
            ]
            creds, _ = gauth_default(scopes=scopes)
            gc = gspread.authorize(creds)

            # Abrir primeira aba
            spreadsheet = gc.open_by_url(GOOGLE_SHEETS_URL)
            worksheet = spreadsheet.get_worksheet(0)

            # Pegar todos os dados
            valores = worksheet.get_all_values()
            if len(valores) <= 1:
                return {}

            headers = valores[0]
            dados = valores[1:]
            df = pd.DataFrame(dados, columns=headers)

            # Filtrar leads válidos (com decil e score)
            df_valid = df[
                (df['decil'].notna()) &
                (df['decil'] != '') &
                (df['decil'] != 'MODELO 6 ML') &
                (df['lead_score'].notna()) &
                (df['lead_score'] != '')
            ].copy()

            if len(df_valid) == 0:
                return {}

            # Converter score para float
            df_valid['lead_score_float'] = df_valid['lead_score'].str.replace(',', '.').astype(float)

            # Parsear data
            df_valid['data_parsed'] = pd.to_datetime(df_valid['Data'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
            df_with_date = df_valid[df_valid['data_parsed'].notna()].copy()

            if len(df_with_date) == 0:
                return {}

            # Definir períodos
            now = datetime.now()
            last_24h = now - timedelta(days=1)
            last_week = now - timedelta(days=7)
            last_month = now - timedelta(days=30)

            # Filtrar por período
            df_24h = df_with_date[df_with_date['data_parsed'] >= last_24h]
            df_week = df_with_date[df_with_date['data_parsed'] >= last_week]
            df_month = df_with_date[df_with_date['data_parsed'] >= last_month]
            df_all = df_with_date

            # Calcular métricas
            def calc_metrics(df_period):
                if len(df_period) == 0:
                    return {'score': 0, 'd9': 0, 'd10': 0, 'count': 0}

                score_mean = df_period['lead_score_float'].mean()
                d9_pct = (df_period['decil'] == 'D9').sum() / len(df_period) * 100
                d10_pct = (df_period['decil'] == 'D10').sum() / len(df_period) * 100

                return {
                    'score': score_mean,
                    'd9': d9_pct,
                    'd10': d10_pct,
                    'count': len(df_period)
                }

            return {
                'historico': calc_metrics(df_all),
                'ultimo_mes': calc_metrics(df_month),
                'ultima_semana': calc_metrics(df_week),
                'ultimas_24h': calc_metrics(df_24h)
            }

        except Exception as e:
            logger.warning(f" Erro ao calcular métricas de qualidade: {e}")
            return {}

    def _generate_critical_summary(self, alerts: List[Alert], funnel_metrics: Dict) -> str:
        """
        Gera sumário crítico consolidado do sistema.

        Args:
            alerts: Lista de alertas gerados pelos checks
            funnel_metrics: Métricas do funil de conversão

        Returns:
            String com o sumário crítico formatado
        """
        lines = []
        lines.append("\n" + "="*72)
        lines.append(" SUMÁRIO CRÍTICO DO SISTEMA")
        lines.append("="*72)

        # Período de análise
        window = funnel_metrics.get('window', {})
        if window:
            lines.append(f"\n Período analisado (BRT): {window['start_brt']} → {window['end_brt']}")

        # 1. Categorias não vistas no treino
        new_categories = [a for a in alerts if 'nova categoria' in a.message.lower() or 'não vista no treino' in a.message.lower()]
        if new_categories:
            lines.append("\n1. Categorias não vistas no treino: Sim")
            for alert in new_categories:
                # Extrair coluna e categoria da mensagem
                parts = alert.message.split("'")
                if len(parts) >= 2:
                    lines.append(f"   - {parts[1]}: {parts[3] if len(parts) >= 4 else 'categoria desconhecida'}")
        else:
            lines.append("\n1. Categorias não vistas no treino: Não")

        # 2. Mudanças drásticas nas proporções de colunas
        drastic_changes = [a for a in alerts if 'mudança(s) significativa(s)' in a.message.lower() or 'mudanças significativas' in a.message.lower()]
        if drastic_changes:
            lines.append("\n2. Mudanças drásticas nas proporções: Sim")
            for alert in drastic_changes:
                details = alert.details
                column = details.get('column', 'desconhecida')

                # Se for drift categórico, tem 'changes' com as mudanças
                if 'changes' in details:
                    changes = details['changes']
                    if changes:
                        # Pegar a maior mudança
                        biggest_change = max(changes, key=lambda x: abs(x.get('diff', 0)))
                        categoria = biggest_change.get('categoria', '?')
                        treino = biggest_change.get('treino', 0) * 100
                        producao = biggest_change.get('producao', 0) * 100
                        diff = abs(biggest_change.get('diff', 0)) * 100
                        lines.append(f"   - {column} '{categoria}': Variação de {diff:.1f}pp (treino: {treino:.1f}%, produção: {producao:.1f}%)")
                # Se for drift numérico, tem sigma_diff
                elif 'sigma_diff' in details:
                    sigma = details.get('sigma_diff', 0)
                    mean_treino = details.get('mean_treino', 0)
                    mean_prod = details.get('mean_producao', 0)
                    lines.append(f"   - {column}: Mudança de {sigma:.1f}σ (média treino: {mean_treino:.2f}, produção: {mean_prod:.2f})")
        else:
            lines.append("\n2. Mudanças drásticas nas proporções: Não")

        # 3. Colunas com dados faltantes
        missing_data = [a for a in alerts if 'faltante' in a.message.lower() and 'feature' not in a.message.lower()]
        if missing_data:
            lines.append("\n3. Colunas com dados faltantes: Sim")
            for alert in missing_data:
                lines.append(f"   - {alert.message}")
        else:
            lines.append("\n3. Colunas com dados faltantes: Não")

        # 4. Features faltantes
        missing_features_alerts = [a for a in alerts if 'feature' in a.message.lower() and ('esperada' in a.message.lower() or 'faltando' in a.message.lower() or 'não encontrada' in a.message.lower() or 'ausente' in a.message.lower())]
        if missing_features_alerts:
            lines.append("\n4. Features faltantes: Sim")
            for alert in missing_features_alerts:
                details = alert.details

                # Se o alerta tem lista de missing_features no details
                if 'missing_features' in details:
                    missing_list = details['missing_features']
                    missing_count = len(missing_list)
                    lines.append(f"   Total: {missing_count} feature(s)")

                    # Mostrar até 10 features (para não poluir)
                    for feat in missing_list[:10]:
                        lines.append(f"   - {feat}")
                    if len(missing_list) > 10:
                        lines.append(f"   ... e mais {len(missing_list) - 10} features")
                # Senão, tentar extrair da mensagem (fallback)
                else:
                    parts = alert.message.split("'")
                    if len(parts) >= 2:
                        feature_name = parts[1]
                        lines.append(f"   - {feature_name}")
        else:
            lines.append("\n4. Features faltantes: Não")

        # 5. Mudança significativa em score/decil
        score_changes = [a for a in alerts if 'distribuição de decis mudou' in a.message.lower()]
        if score_changes:
            lines.append("\n5. Mudança significativa em score/decil: Sim")
            for alert in score_changes:
                details = alert.details
                changes = details.get('changes', [])

                if changes:
                    # Mostrar todos os decis com mudanças
                    for change in changes:
                        decil = change.get('decil', '?')
                        esperado = change.get('esperado', 0) * 100
                        atual = change.get('atual', 0) * 100
                        diff = abs(change.get('diff', 0)) * 100
                        lines.append(f"   - {decil}: Variação de {diff:.1f}pp (esperado: {esperado:.1f}%, atual: {atual:.1f}%)")
        else:
            lines.append("\n5. Mudança significativa em score/decil: Não")

        # 6. Envio CAPI para Meta
        capture = funnel_metrics.get('capture', {})
        total_db = capture.get('total_database', 0)
        capi_sent = funnel_metrics.get('capi_sent', {})
        leads_sent = capi_sent.get('leads_sent', 0)
        estimated_events = capi_sent.get('estimated_events', 0)
        lines.append(f"\n6. Envio CAPI para Meta: {'Sim' if leads_sent > 0 else 'Não'}")
        lines.append(f"   ({leads_sent:,} leads enviados, ~{estimated_events:,} eventos)")

        # 7. Cookies FBP/FBC preenchidos
        data_quality = funnel_metrics.get('data_quality', {})
        fbp_rate = data_quality.get('fbp_percentage', 0)
        fbc_rate = data_quality.get('fbc_percentage', 0)
        lines.append(f"\n7. Cookies FBP/FBC preenchidos: {'Sim' if fbp_rate > 90 and fbc_rate > 90 else 'Parcial' if fbp_rate > 50 or fbc_rate > 50 else 'Não'}")
        lines.append(f"   - FBP: {fbp_rate:.1f}%")
        lines.append(f"   - FBC: {fbc_rate:.1f}%")

        # 8. Eventos recebidos pela Meta
        meta_response = funnel_metrics.get('meta_response', {})
        success_count = meta_response.get('success_count', 0)
        leads_with_response = meta_response.get('leads_with_response', 0)
        acceptance_rate = meta_response.get('acceptance_rate', 0)
        lines.append(f"\n8. Eventos recebidos pela Meta: {'Sim' if success_count > 0 else 'Não'}")
        if success_count > 0:
            lines.append(f"   ({acceptance_rate:.1f}% de aceitação, {success_count} leads aceitos)")

        # 9. Funil de Conversão
        total_sheets = capture.get('total_sheets_combined', 0)
        lines.append(f"\n9. Funil de Conversão:")
        lines.append(f"    Capturados: {total_db:,}  Respostas: {total_sheets:,}  Enviados CAPI: {leads_sent:,}  Aceitos Meta: {success_count:,}")

        # 10. Taxa de Resposta
        response_rate = capture.get('response_rate', 0)
        lines.append(f"\n10. Taxa de Resposta:")
        lines.append(f"    - Resposta pesquisa: {response_rate:.1f}%")

        # 11. Qualidade dos Leads
        quality_metrics = self._calculate_lead_quality_metrics()
        if quality_metrics:
            lines.append(f"\n11. Qualidade dos Leads:")
            lines.append(f"    ")
            lines.append(f"     Score Médio:")

            hist = quality_metrics.get('historico', {})
            mes = quality_metrics.get('ultimo_mes', {})
            semana = quality_metrics.get('ultima_semana', {})
            dia = quality_metrics.get('ultimas_24h', {})

            if hist.get('count', 0) > 0:
                lines.append(f"       Histórico:      {hist['score']:.4f}")
            if mes.get('count', 0) > 0:
                lines.append(f"       Último mês:     {mes['score']:.4f}")
            if semana.get('count', 0) > 0:
                lines.append(f"       Última semana:  {semana['score']:.4f}")
            if dia.get('count', 0) > 0:
                lines.append(f"       Últimas 24h:    {dia['score']:.4f}")

            lines.append(f"    ")
            lines.append(f"     % em D9:")
            if hist.get('count', 0) > 0:
                lines.append(f"       Histórico:      {hist['d9']:.2f}%")
            if mes.get('count', 0) > 0:
                lines.append(f"       Último mês:     {mes['d9']:.2f}%")
            if semana.get('count', 0) > 0:
                lines.append(f"       Última semana:  {semana['d9']:.2f}%")
            if dia.get('count', 0) > 0:
                lines.append(f"       Últimas 24h:    {dia['d9']:.2f}%")

            lines.append(f"    ")
            lines.append(f"     % em D10:")
            if hist.get('count', 0) > 0:
                lines.append(f"       Histórico:      {hist['d10']:.2f}%")
            if mes.get('count', 0) > 0:
                lines.append(f"       Último mês:     {mes['d10']:.2f}%")
            if semana.get('count', 0) > 0:
                lines.append(f"       Última semana:  {semana['d10']:.2f}%")
            if dia.get('count', 0) > 0:
                lines.append(f"       Últimas 24h:    {dia['d10']:.2f}%")

        lines.append("\n" + "="*72)

        # Juntar todas as linhas e printar + retornar
        summary = '\n'.join(lines)
        logger.info(summary)
        return summary

    def _generate_summary(self, alerts: List[Alert]) -> Dict:
        """Gera sumário de alertas por severidade e categoria"""
        by_severity = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
        by_category = {'data_quality': 0, 'operational': 0, 'capi_quality': 0}

        for alert in alerts:
            by_severity[alert.severity.value] += 1
            by_category[alert.category.value] += 1

        return {
            'by_severity': by_severity,
            'by_category': by_category
        }

    def _generate_funnel_metrics(self, leads_data: List[Dict], df: pd.DataFrame = None) -> Dict:
        """
        Gera métricas completas do funil de leads.

        Analisa toda a jornada do lead:
        1. Captura (landing page + Google Sheets)
        2. Qualidade dos dados CAPI (FBP/FBC)
        3. Scoring/Classificação (decis)
        4. Envio para Meta CAPI
        5. Resposta da Meta (aceite/rejeição)
        6. Conversão final (resposta à pesquisa)
        """
        from datetime import datetime, timedelta, timezone
        from api.database import LeadCAPI

        if self.db is None:
            return {}

        metrics = {}
        now = datetime.now(timezone.utc)
        lookback_time = now - timedelta(hours=12)

        # Guardar janela de análise para exibir no sumário
        brt = timezone(timedelta(hours=-3))
        metrics['window'] = {
            'start_utc': lookback_time.isoformat(),
            'end_utc': now.isoformat(),
            'start_brt': lookback_time.astimezone(brt).strftime('%d/%m/%Y %H:%M'),
            'end_brt': now.astimezone(brt).strftime('%d/%m/%Y %H:%M'),
        }

        # ETAPA 1: CAPTURA DE LEADS
        total_sheets_tab1 = len(leads_data) if leads_data else 0
        total_sheets_tab2 = self._count_sheet_tab2_responses(lookback_time)
        total_sheets = total_sheets_tab1 + total_sheets_tab2

        total_db = self.db.query(
            func.count(distinct(LeadCAPI.email))
        ).filter(
            LeadCAPI.created_at >= lookback_time
        ).scalar()

        metrics['capture'] = {
            'total_sheets_tab1': total_sheets_tab1,
            'total_sheets_tab2': total_sheets_tab2,
            'total_sheets_combined': total_sheets,
            'total_database': total_db,
            'response_rate': (total_sheets / total_db * 100) if total_db > 0 else 0
        }

        # ETAPA 2: QUALIDADE DOS DADOS CAPI
        recent_leads = self.db.query(LeadCAPI).filter(
            LeadCAPI.created_at >= lookback_time
        ).all()

        if recent_leads:
            with_fbp = sum(1 for lead in recent_leads if lead.fbp and lead.fbp.strip())
            with_fbc = sum(1 for lead in recent_leads if lead.fbc and lead.fbc.strip())
            with_first_name = sum(1 for lead in recent_leads if lead.first_name and lead.first_name.strip())
            with_phone = sum(1 for lead in recent_leads if lead.phone and lead.phone.strip())

            pct_fbp = with_fbp / len(recent_leads) * 100
            pct_fbc = with_fbc / len(recent_leads) * 100
            pct_first_name = with_first_name / len(recent_leads) * 100
            pct_phone = with_phone / len(recent_leads) * 100

            metrics['data_quality'] = {
                'total_leads': len(recent_leads),
                'fbp_present': with_fbp,
                'fbp_percentage': pct_fbp,
                'fbc_present': with_fbc,
                'fbc_percentage': pct_fbc,
                'first_name_present': with_first_name,
                'first_name_percentage': pct_first_name,
                'phone_present': with_phone,
                'phone_percentage': pct_phone
            }

        # ETAPA 3: SCORING/CLASSIFICAÇÃO
        if df is not None and 'decil' in df.columns:
            decil_dist = df['decil'].value_counts().sort_index()

            metrics['scoring'] = {
                'total_scored': len(df),
                'decil_distribution': decil_dist.to_dict(),
                'avg_score': df['lead_score'].mean() if 'lead_score' in df.columns else None
            }

        # ETAPA 4: ENVIO PARA META CAPI
        # Filtra por created_at para contar apenas leads da janela atual,
        # evitando inflacionar com backlog histórico processado pelo polling de 5min
        sent_to_capi = self.db.query(LeadCAPI).filter(
            LeadCAPI.created_at >= lookback_time,
            LeadCAPI.capi_sent_at.isnot(None)
        ).count()

        estimated_events = int(sent_to_capi * 1.3)  # Aproximação

        metrics['capi_sent'] = {
            'leads_sent': sent_to_capi,
            'send_rate': (sent_to_capi / total_db * 100) if total_db > 0 else 0,
            'estimated_events': estimated_events
        }

        # ETAPA 5: RESPOSTA DA META
        with_response = self.db.query(LeadCAPI).filter(
            LeadCAPI.created_at >= lookback_time,
            LeadCAPI.capi_response_status.isnot(None)
        ).all()

        if with_response:
            status_counts = {}
            total_received = 0
            total_rejected = 0

            for lead in with_response:
                status = lead.capi_response_status or 'unknown'
                status_counts[status] = status_counts.get(status, 0) + 1

                if lead.capi_events_received:
                    total_received += lead.capi_events_received
                if lead.capi_events_rejected:
                    total_rejected += lead.capi_events_rejected

            success_count = status_counts.get('success', 0)
            error_count = status_counts.get('error', 0)
            partial_count = status_counts.get('partial', 0)

            acceptance_rate = (success_count / len(with_response) * 100) if len(with_response) > 0 else 0

            metrics['meta_response'] = {
                'leads_with_response': len(with_response),
                'success_count': success_count,
                'error_count': error_count,
                'partial_count': partial_count,
                'acceptance_rate': acceptance_rate,
                'events_received': total_received,
                'events_rejected': total_rejected
            }
        else:
            metrics['meta_response'] = {
                'leads_with_response': 0,
                'success_count': 0,
                'error_count': 0,
                'partial_count': 0,
                'acceptance_rate': 0,
                'events_received': 0,
                'events_rejected': 0
            }

        # ETAPA 6: CONVERSÃO FINAL
        response_rate = (total_sheets / total_db * 100) if total_db > 0 else 0

        metrics['conversion'] = {
            'responded_to_survey': total_sheets,
            'response_rate': response_rate
        }

        return metrics

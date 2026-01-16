"""
Orquestrador central de monitoramento.

Coordena execução de todos os monitors e consolida alertas.
"""

import logging
import pandas as pd
from typing import List, Dict
from sqlalchemy.orm import Session
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

    print(f"✅ Output do monitoramento será salvo em: {log_path}\n")
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

            logger.info(f"📧 Primeiro lead: {primeiro_email} (Data: {primeiro_data})")
            logger.info(f"📧 Último lead: {ultimo_email} (Data: {ultimo_data})")

            # Aplicar unificação de UTM Source/Term (mesmo processamento que produção)
            # Isso garante que 'fb', 'youtube', etc sejam normalizados para 'outros'
            if 'Source' in df.columns or 'Term' in df.columns:
                from data_processing.utm_unification import unify_utm_columns
                utm_antes = df['Source'].nunique() if 'Source' in df.columns else 0
                df = unify_utm_columns(df)
                utm_depois = df['Source'].nunique() if 'Source' in df.columns else 0
                logger.info(f"📊 UTM unificado: Source {utm_antes} → {utm_depois} categorias únicas")

            # Aplicar unificação de Medium (mesmo processamento que treino e produção)
            # Isso garante que 'ABERTO | AD0022' seja normalizado para 'Aberto'
            if 'Medium' in df.columns:
                medium_antes = df['Medium'].nunique()
                df = unify_medium_columns(df)
                medium_depois = df['Medium'].nunique()
                logger.info(f"📊 Medium unificado: {medium_antes} → {medium_depois} categorias únicas")

            # Aplicar rename de colunas longas (mesmo processamento que produção)
            # Cria: 'interesse_programacao' e 'investiu_curso_online'
            from data_processing.preprocessing import rename_long_column_names
            df = rename_long_column_names(df)
            logger.info(f"📊 Colunas renomeadas")

            # Aplicar unificação de categorias (mesmo processamento que produção)
            # Limpa e normaliza valores das categorias
            from data_processing.category_unification import unificar_categorias_completo
            df = unificar_categorias_completo(df)
            logger.info(f"📊 Categorias unificadas")

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
            logger.info(f"📊 Colunas de score/faixa removidas: {score_removidos} (total: {colunas_depois_score})")

            # Restaurar colunas de score/decil APÓS limpeza (para monitoramento de distribuição)
            if decil_col is not None:
                df['decil'] = decil_col
                logger.info(f"📊 Coluna 'decil' preservada para monitoramento (distribuição: {df['decil'].value_counts().sort_index().to_dict()})")
            if lead_score_col is not None:
                # Converter lead_score para float (pode vir como string com vírgula do Google Sheets)
                if lead_score_col.dtype == 'object':
                    # Substituir vírgula por ponto e tratar strings vazias
                    lead_score_col = lead_score_col.str.replace(',', '.').replace('', None)
                    lead_score_col = pd.to_numeric(lead_score_col, errors='coerce')
                df['lead_score'] = lead_score_col
                valid_scores = df['lead_score'].notna().sum()
                logger.info(f"📊 Coluna 'lead_score' preservada para monitoramento ({valid_scores}/{len(df)} válidos, média: {df['lead_score'].mean():.4f})")

            # Remover features de campanha (mesmo processamento que produção)
            # Remove: Campaign, Content, e colunas vazias/problemáticas
            from data_processing.preprocessing import remove_campaign_features
            colunas_antes_campaign = len(df.columns)
            df = remove_campaign_features(df)
            colunas_depois_campaign = len(df.columns)
            campaign_removidos = colunas_antes_campaign - colunas_depois_campaign
            logger.info(f"📊 Features de campanha removidas: {campaign_removidos} (total: {colunas_depois_campaign})")

            # Remover campos técnicos (mesmo processamento que produção)
            # Remove: Remote IP, User Agent, fbc, fbp, cidade, estado, pais, cep, externalid, Page URL, etc
            from data_processing.preprocessing import remove_technical_fields
            colunas_antes_tech = len(df.columns)
            df = remove_technical_fields(df)
            colunas_depois_tech = len(df.columns)
            campos_removidos = colunas_antes_tech - colunas_depois_tech
            logger.info(f"📊 Campos técnicos removidos: {campos_removidos} (total: {colunas_depois_tech})")

            # Aplicar feature engineering (mesmo processamento que produção)
            # Cria: nome_valido, email_valido, telefone_valido, telefone_comprimento, nome_tem_sobrenome
            from features.engineering import create_derived_features
            colunas_antes_fe = len(df.columns)
            df = create_derived_features(df)
            colunas_depois_fe = len(df.columns)
            saldo_fe = colunas_depois_fe - colunas_antes_fe
            logger.info(f"📊 Features derivadas criadas: {saldo_fe:+d} colunas (total: {colunas_depois_fe})")

            all_alerts_dict.extend(self.monitors['data_quality'].check(df))

        # 2. Operational (usa PostgreSQL)
        all_alerts_dict.extend(self.monitors['operational'].check())

        # 3. CAPI Quality (usa PostgreSQL)
        all_alerts_dict.extend(self.monitors['capi_quality'].check())

        # Converter para objetos Alert
        alerts = [Alert.from_dict(alert_dict) for alert_dict in all_alerts_dict]

        # Gerar sumário
        summary = self._generate_summary(alerts)

        # Mensagem de conclusão
        print(f"\n✅ Monitoramento concluído!")
        print(f"✅ Log completo salvo em: {log_path}\n")

        return {
            'total_alerts': len(alerts),
            'alerts_by_severity': summary['by_severity'],
            'alerts_by_category': summary['by_category'],
            'alerts': [alert.to_dict() for alert in alerts]
        }

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

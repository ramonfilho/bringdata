"""
Orquestrador central de monitoramento.

Coordena execução de todos os monitors e consolida alertas.
"""

import logging
import pandas as pd
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct, text
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .data_quality import DataQualityMonitor
from .operational_monitor import OperationalMonitor
from .capi_monitor import CAPIQualityMonitor
from .models import Alert
from core.client_config import ClientConfig
from core.utm import unify_utm
from core.medium import unify_medium
from core.category_unification import unify_categories as _unify_categories
from core.preprocessing import preprocess_for_monitoring
from core.feature_engineering import create_features as _fe_create

_DEFAULT_CONFIG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'configs', 'clients', 'devclub.yaml')
)

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
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
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

    def __init__(self, model_path: str, db: Session, client_config: Optional[ClientConfig] = None,
                 expected_decil_dist: Optional[Dict[str, float]] = None):
        """
        Args:
            model_path:    Caminho para pasta do modelo ativo
            db:            Sessão SQLAlchemy do PostgreSQL
            client_config: Configuração do cliente; se None, carrega devclub.yaml
            expected_decil_dist: Distribuição esperada de decis pré-computada (E6).
                                 Caller (app.py:daily-check/railway) computa rolling 30d
                                 via Railway e passa aqui — `db` legacy não tem a tabela Lead.
                                 Quando None, DataQualityMonitor cai em E5/hardcoded.
        """
        self.model_path = model_path
        self.db = db
        self._client_config = client_config or ClientConfig.from_yaml(_DEFAULT_CONFIG_PATH)

        # Verificar suporte a filtro multi-cliente (depende do schema do banco)
        if db is not None:
            from api.database import has_client_id_column
            self._filter_by_client = has_client_id_column(db)
        else:
            self._filter_by_client = False

        # Inicializar monitors
        self.monitors = {
            'data_quality': DataQualityMonitor(model_path, client_config=self._client_config, db=db,
                                               expected_decil_dist=expected_decil_dist),
            'operational': OperationalMonitor(db, client_config=self._client_config),
            'capi_quality': CAPIQualityMonitor(db, client_config=self._client_config)
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
                utm_antes = df['Source'].nunique() if 'Source' in df.columns else 0
                df = unify_utm(df, self._client_config.utm)
                utm_depois = df['Source'].nunique() if 'Source' in df.columns else 0
                logger.info(f" UTM unificado: Source {utm_antes}  {utm_depois} categorias únicas")

            # Aplicar unificação de Medium (mesmo processamento que treino e produção)
            # Isso garante que 'ABERTO | AD0022' seja normalizado para 'Aberto'
            if 'Medium' in df.columns:
                medium_antes = df['Medium'].nunique()
                df = unify_medium(df, self._client_config.medium)
                medium_depois = df['Medium'].nunique()
                logger.info(f" Medium unificado: {medium_antes}  {medium_depois} categorias únicas")

            # Converter lead_score para float antes do preprocessing
            # (pode vir como string com vírgula do Google Sheets)
            if 'lead_score' in df.columns and df['lead_score'].dtype == 'object':
                df['lead_score'] = (
                    pd.to_numeric(
                        df['lead_score'].str.replace(',', '.').replace('', None),
                        errors='coerce'
                    )
                )

            # Aplicar unificação de categorias (mesmo processamento que produção)
            df = _unify_categories(df, self._client_config.category)
            logger.info(f" Categorias unificadas")

            # Sequência canônica de preprocessing com preservação de decil/lead_score
            colunas_antes_pre = len(df.columns)
            df = preprocess_for_monitoring(df, self._client_config.ingestion, self._client_config.feature)
            colunas_depois_pre = len(df.columns)
            logger.info(f" Preprocessing: {colunas_antes_pre} → {colunas_depois_pre} colunas")

            if 'decil' in df.columns:
                logger.info(f" Coluna 'decil' preservada (distribuição: {df['decil'].value_counts().sort_index().to_dict()})")
            if 'lead_score' in df.columns:
                valid_scores = df['lead_score'].notna().sum()
                logger.info(f" Coluna 'lead_score' preservada ({valid_scores}/{len(df)} válidos, média: {df['lead_score'].mean():.4f})")

            # Aplicar feature engineering (mesmo processamento que produção)
            colunas_antes_fe = len(df.columns)
            df = _fe_create(df, self._client_config.feature)
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

        # Garantir que a sessão está limpa antes de queries de funil
        # (monitors podem deixar transação abortada em caso de erro interno)
        if self.db is not None:
            try:
                self.db.rollback()
            except Exception as e:
                # T2-6: rollback que falha indica estado inconsistente — log + segue (queries
                # downstream provavelmente vão falhar também, mas pelo menos fica rastro).
                logger.error(
                    f"[T2-6] db.rollback() falhou — sessão pode estar em estado inconsistente: {e}",
                    exc_info=True,
                )

        # NOVO: Gerar métricas do funil completo
        funnel_metrics = self._generate_funnel_metrics(leads_data, df if leads_data else None)

        # NOVO: Calcular métricas de qualidade dos leads por período
        lead_quality_metrics = self._calculate_lead_quality_metrics()

        # NOVO: Gerar sumário crítico consolidado
        critical_summary = self._generate_critical_summary(alerts, funnel_metrics, lead_quality_metrics)

        # T3-5: rotinas operacionais consolidadas no mesmo log
        operational_routines = self._generate_operational_routines_summary()

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
            'critical_summary': critical_summary,
            'operational_routines': operational_routines,
        }

    def _generate_operational_routines_summary(self) -> Dict:
        """T3-5: consolida status das rotinas operacionais no log de monitoramento.

        Reporta: run_id do modelo ativo, Cloud Run revision, último scoring (proxy
        do polling Railway), e contadores 24h de leads recebidos/scoreados/CAPI enviados.
        Tudo num bloco único — evita ter que abrir log por log para checar saúde.
        """
        import os as _os
        import yaml as _yaml
        from sqlalchemy import func as _sa_func

        result: Dict = {}
        # 1. Modelo ativo (run_id do YAML)
        # [O1] Tenta múltiplos paths — em produção (Cloud Run) o WORKDIR é /app
        # e o repo fica em /app/V2; em dev local fica em $REPO_ROOT/V2/...
        client_id = getattr(self._client_config, 'client_id', 'devclub') if self._client_config else 'devclub'
        _candidate_yamls = [
            _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..', '..', 'configs', 'active_models', f'{client_id}.yaml')),
            f'/app/V2/configs/active_models/{client_id}.yaml',
            f'/app/configs/active_models/{client_id}.yaml',
            _os.path.abspath(_os.path.join(_os.getcwd(), 'configs', 'active_models', f'{client_id}.yaml')),
        ]
        _yaml_loaded = False
        for _path in _candidate_yamls:
            if _os.path.exists(_path):
                try:
                    with open(_path) as _f:
                        _am = _yaml.safe_load(_f) or {}
                    result['active_run_id'] = (_am.get('active_model') or {}).get('mlflow_run_id')
                    result['ab_test_enabled'] = bool((_am.get('ab_test') or {}).get('enabled'))
                    result['active_model_yaml_path'] = _path
                    _yaml_loaded = True
                    break
                except Exception as _e:
                    logger.warning(f"  [T3-5] erro ao parsear {_path}: {_e}")
        if not _yaml_loaded:
            logger.warning(f"  [T3-5] active_model.yaml não encontrado — paths tentados: {_candidate_yamls}")
            result['active_run_id'] = None
            result['ab_test_enabled'] = None

        # 2. Cloud Run revision (definida pelo Cloud Run em runtime)
        result['cloud_run_revision'] = _os.environ.get('K_REVISION')
        result['cloud_run_service'] = _os.environ.get('K_SERVICE')
        if not result['cloud_run_revision']:
            # K_REVISION/K_SERVICE são injetadas pelo Cloud Run em runtime. Ausentes = rodando
            # local OU env não foi propagada. Logar pra debug.
            logger.debug(f"  [T3-5] K_REVISION ausente; ambiente={['K_' + k for k in _os.environ if k.startswith('K_')]}")

        # 3. Contadores 24h — query direta em Railway (Lead, fonte autoritativa pós-30/04).
        # Antes usava self.db.query(LeadCAPI) que é Cloud SQL legado e parou de receber
        # scoring em 30/04. Agora abrimos uma conexão Railway temporária pra pegar dados reais.
        try:
            import pg8000.native as _pg
            _railway_host = _os.environ.get('RAILWAY_DB_HOST')
            if _railway_host:
                _conn = _pg.Connection(
                    host=_railway_host,
                    port=int(_os.environ.get('RAILWAY_DB_PORT', '11594')),
                    database=_os.environ.get('RAILWAY_DB_NAME', 'railway'),
                    user=_os.environ.get('RAILWAY_DB_USER', 'postgres'),
                    password=_os.environ['RAILWAY_DB_PASSWORD'],
                    timeout=15,
                )
                _now = datetime.now(timezone.utc)
                _row = _conn.run(
                    'SELECT '
                    '  COUNT(*) FILTER (WHERE "createdAt" >= NOW() - INTERVAL \'24 hours\'),'
                    '  COUNT(*) FILTER (WHERE "leadScore" IS NOT NULL AND "updatedAt" >= NOW() - INTERVAL \'24 hours\'),'
                    '  COUNT(*) FILTER (WHERE "capiSentAt" >= NOW() - INTERVAL \'24 hours\'),'
                    '  MAX("updatedAt") FILTER (WHERE "leadScore" IS NOT NULL) '
                    'FROM "Lead"'
                )
                _conn.close()
                if _row:
                    _leads_24h, _scored_24h, _capi_24h, _last_scored = _row[0]
                    result['leads_received_24h'] = int(_leads_24h or 0)
                    result['leads_scored_24h'] = int(_scored_24h or 0)
                    result['capi_sent_24h'] = int(_capi_24h or 0)
                    if _last_scored is not None:
                        if _last_scored.tzinfo is None:
                            _last_scored = _last_scored.replace(tzinfo=timezone.utc)
                        result['last_scored_at'] = _last_scored.isoformat()
                        result['minutes_since_last_score'] = round((_now - _last_scored).total_seconds() / 60, 1)
            else:
                logger.warning("  [T3-5] RAILWAY_DB_HOST não setada — contadores 24h não disponíveis")
        except Exception as _e:
            logger.warning(f"  [T3-5] falha ao coletar contadores 24h via Railway: {_e}")

        # Log estruturado consolidado
        logger.info("")
        logger.info("=" * 60)
        logger.info(" Rotinas operacionais (T3-5)")
        logger.info("=" * 60)
        logger.info(f"  Modelo ativo (run_id): {result.get('active_run_id') or '(não lido)'}")
        logger.info(f"  A/B test: {'enabled' if result.get('ab_test_enabled') else 'disabled'}")
        if result.get('cloud_run_revision'):
            logger.info(f"  Cloud Run: {result.get('cloud_run_service')} / {result.get('cloud_run_revision')}")
        if 'last_scored_at' in result:
            logger.info(f"  Último scoring: {result['last_scored_at']} ({result.get('minutes_since_last_score', '?')} min atrás)")
            logger.info(f"  Leads (24h)  recebidos: {result.get('leads_received_24h', 0):>6,}")
            logger.info(f"  Leads (24h)  scoreados: {result.get('leads_scored_24h', 0):>6,}")
            logger.info(f"  Eventos CAPI (24h):     {result.get('capi_sent_24h', 0):>6,}")
        logger.info("=" * 60)
        return result

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
                parse_errors = 0  # T2-6: contar linhas malformadas

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
                        except Exception:
                            # T2-6: linha malformada — contar e seguir; log agregado no fim
                            parse_errors += 1
                            continue

                if parse_errors > 0:
                    logger.warning(
                        f"  [T2-6] {parse_errors} linha(s) da aba 2 com data ilegível "
                        f"foram puladas no count de leads"
                    )
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
            df_valid['data_parsed'] = pd.to_datetime(df_valid['Data'], format='%Y-%m-%d %H:%M:%S', errors='coerce', utc=True)
            df_with_date = df_valid[df_valid['data_parsed'].notna()].copy()

            if len(df_with_date) == 0:
                return {}

            # Definir períodos
            now = datetime.now(timezone.utc)
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

    def _generate_critical_summary(self, alerts: List[Alert], funnel_metrics: Dict, lead_quality_metrics: Dict = None, meta_metrics: Dict = None) -> str:
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
        quality_metrics = lead_quality_metrics if lead_quality_metrics is not None else self._calculate_lead_quality_metrics()
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

        # 12. Métricas Meta Ads (campanhas CAP, hoje)
        if meta_metrics:
            date_ref = meta_metrics.get('date', 'hoje')
            spend    = meta_metrics.get('spend', 0)
            clicks   = meta_metrics.get('clicks', 0)
            cpl      = meta_metrics.get('cpl')
            taxa     = meta_metrics.get('taxa_clique_lead')

            lines.append(f"\n12. Meta Ads — CAP ({date_ref}):")
            lines.append(f"    - Investimento:      R$ {spend:,.2f}")
            lines.append(f"    - Cliques:           {clicks:,}")
            if cpl is not None:
                lines.append(f"    - Custo por Lead:    R$ {cpl:.2f}")
            if taxa is not None:
                lines.append(f"    - Taxa Clique→Lead:  {taxa:.1f}%")

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

    def _generate_revenue_forecast(
        self,
        total_meta_leads: int,
        funnel_metrics: Dict,
        lead_quality_metrics: Dict,
        decil_distribution: Dict = None,
    ) -> Dict:
        """
        Gera previsão de faturamento — metodologia flat-rate (espelho do backtest).

        Metodologia validada em backtest leave-one-out LF42–LF47, MAE 7.5%:
            buyers = total_leads_meta × (conv_rastr_mediana / tracking_rate)

        total_meta_leads: total de leads vindos da Meta (via Meta Ads API), inclui
            respondentes e não-respondentes à pesquisa. Evita subestimativa por
            leads que não chegam ao DB.
        conv_rastr_mediana: mediana histórica de vendas_matched/total_leads_meta.
        tracking_rate: mediana histórica de vendas_matched/vendas_reais.
        taxa_real = conv_rastr_mediana / tracking_rate = vendas_reais/total_leads_meta.
        """
        biz             = self._client_config.business
        ticket          = biz.ticket_contracted
        guru_ticket     = biz.guru_ticket_price or ticket
        guru_realizacao = biz.guru_realizacao_factor
        pct_cartao      = biz.pct_cartao_historico
        pct_boleto      = 1.0 - pct_cartao
        n_parcelas      = biz.n_parcelas_boleto or 12
        parcela_tmb     = ticket / n_parcelas
        conv_rastr      = biz.conv_rastr_mediana   # mediana histórica LF42–LF47
        tracking_rate   = biz.tracking_rate         # mediana histórica LF42–LF47

        if ticket <= 0 or total_meta_leads <= 0 or tracking_rate <= 0:
            return {}

        # taxa_real = vendas_reais / total_leads_meta
        # = (conv_rastr / tracking_rate)
        # onde conv_rastr = vendas_matched/total_leads_meta
        #       tracking_rate = vendas_matched/vendas_reais
        taxa_real = conv_rastr / tracking_rate

        def _calc(factor: float) -> Dict:
            buyers = total_meta_leads * taxa_real * factor

            vendas_guru = round(buyers * pct_cartao, 1)
            vendas_tmb  = round(buyers * pct_boleto, 1)

            # faturamento_recebido = cartão Guru líquido (ticket real × realizacao) + 1ª parcela boleto TMB
            fat_recebido = round(vendas_guru * guru_ticket * guru_realizacao + vendas_tmb * parcela_tmb)

            return {
                'faturamento':          round(buyers * ticket),
                'faturamento_recebido': fat_recebido,
                'vendas_total':         round(buyers, 1),
                'vendas_guru':          vendas_guru,
                'vendas_tmb':           vendas_tmb,
            }

        base       = _calc(1.0)
        pessimista = _calc(biz.scenario_pessimistic_factor)
        otimista   = _calc(biz.scenario_optimistic_factor)

        # ------------------------------------------------------------------
        # expected_conversion — bottom-up por faixa de decil (diagnóstico)
        # Usa leads DB do lançamento × taxas históricas por faixa (DEV19–LF48).
        # Denominador diferente do flat-rate (DB leads, não Meta leads) —
        # não comparar diretamente com cenario_base.
        # ------------------------------------------------------------------
        expected_conversion = None
        bench = biz.conversion_rate_benchmark or {}
        if bench and decil_distribution:
            rate_d1_d5 = bench.get('D1_D5', 0.0)
            rate_d6_d9 = bench.get('D6_D9', 0.0)
            rate_d10   = bench.get('D10',   0.0)

            leads_d1_d5 = sum(decil_distribution.get(f'D{i:02d}', 0) for i in range(1, 6))
            leads_d6_d9 = sum(decil_distribution.get(f'D{i:02d}', 0) for i in range(6, 10))
            leads_d10   = decil_distribution.get('D10', 0)
            total_db    = leads_d1_d5 + leads_d6_d9 + leads_d10

            if total_db > 0 and tracking_rate > 0:
                # Os rates do yaml são vendas_matched/leads_DB.
                # Dividir por tracking_rate converte para vendas_reais/leads_DB —
                # mesma base de "vendas reais" do flat-rate.
                rate_d1_d5_corr = rate_d1_d5 / tracking_rate
                rate_d6_d9_corr = rate_d6_d9 / tracking_rate
                rate_d10_corr   = rate_d10   / tracking_rate

                buyers_d1_d5 = leads_d1_d5 * rate_d1_d5_corr
                buyers_d6_d9 = leads_d6_d9 * rate_d6_d9_corr
                buyers_d10   = leads_d10   * rate_d10_corr
                total_buyers = buyers_d1_d5 + buyers_d6_d9 + buyers_d10

                # taxa_implicita_meta = total_buyers / total_meta_leads
                # → mesmo denominador do flat-rate, comparação direta com taxa_real_implicita
                taxa_impl_meta = (total_buyers / total_meta_leads * 100) if total_meta_leads > 0 else None
                response_rate  = round(total_db / total_meta_leads * 100, 1) if total_meta_leads > 0 else None

                expected_conversion = {
                    'fonte': bench.get('periodo_referencia', 'DEV19–LF48'),
                    'distribuicao_leads': {
                        'D1_D5': {'leads': leads_d1_d5, 'pct': round(leads_d1_d5 / total_db * 100, 1)},
                        'D6_D9': {'leads': leads_d6_d9, 'pct': round(leads_d6_d9 / total_db * 100, 1)},
                        'D10':   {'leads': leads_d10,   'pct': round(leads_d10   / total_db * 100, 1)},
                        'total_db': total_db,
                        'response_rate_pct': response_rate,
                    },
                    'compradores_esperados': {
                        'D1_D5': round(buyers_d1_d5, 1),
                        'D6_D9': round(buyers_d6_d9, 1),
                        'D10':   round(buyers_d10,   1),
                        'total': round(total_buyers,  1),
                        'taxa_media_corrigida': round(total_buyers / total_db * 100, 3),
                    },
                    # Taxas já corrigidas pelo tracking_rate (vendas_reais/leads_DB)
                    'taxas_corrigidas': {
                        'D1_D5': round(rate_d1_d5_corr * 100, 3),
                        'D6_D9': round(rate_d6_d9_corr * 100, 3),
                        'D10':   round(rate_d10_corr   * 100, 3),
                        'tracking_rate_aplicado': round(tracking_rate * 100, 1),
                    },
                    # Mesma base do flat-rate → comparação direta com taxa_real_implicita
                    'taxa_implicita_por_meta_lead': round(taxa_impl_meta, 3) if taxa_impl_meta else None,
                }

        result = {
            'cenario_pessimista': pessimista,
            'cenario_base':       base,
            'cenario_otimista':   otimista,
            'inputs': {
                'total_leads_meta':     total_meta_leads,
                'conv_rastr_mediana':   conv_rastr,
                'tracking_rate_usado':  tracking_rate,
                'taxa_real_implicita':  round(taxa_real * 100, 3),
                'ticket_contracted':    ticket,
                'pct_cartao_historico': pct_cartao,
                'metodologia':          'flat-rate LOO LF42-LF47 MAE=7.5%',
            },
        }
        if expected_conversion:
            result['expected_conversion'] = expected_conversion
        return result

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

        _client_id = self._client_config.client_id if self._client_config else 'devclub'

        _q_total = self.db.query(func.count(distinct(LeadCAPI.email))).filter(
            LeadCAPI.created_at >= lookback_time
        )
        if self._filter_by_client:
            _q_total = _q_total.filter(text("leads_capi.client_id = :cid").bindparams(cid=_client_id))
        total_db = _q_total.scalar()

        metrics['capture'] = {
            'total_sheets_tab1': total_sheets_tab1,
            'total_sheets_tab2': total_sheets_tab2,
            'total_sheets_combined': total_sheets,
            'total_database': total_db,
            'response_rate': (total_sheets / total_db * 100) if total_db > 0 else 0
        }

        # ETAPA 2: QUALIDADE DOS DADOS CAPI
        _q_recent = self.db.query(LeadCAPI).filter(LeadCAPI.created_at >= lookback_time)
        if self._filter_by_client:
            _q_recent = _q_recent.filter(text("leads_capi.client_id = :cid").bindparams(cid=_client_id))
        recent_leads = _q_recent.all()

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
        _q_sent = self.db.query(LeadCAPI).filter(
            LeadCAPI.created_at >= lookback_time,
            LeadCAPI.capi_sent_at.isnot(None)
        )
        if self._filter_by_client:
            _q_sent = _q_sent.filter(text("leads_capi.client_id = :cid").bindparams(cid=_client_id))
        sent_to_capi = _q_sent.count()

        estimated_events = int(sent_to_capi * 1.3)  # Aproximação

        metrics['capi_sent'] = {
            'leads_sent': sent_to_capi,
            'send_rate': (sent_to_capi / total_db * 100) if total_db > 0 else 0,
            'estimated_events': estimated_events
        }

        # ETAPA 5: RESPOSTA DA META
        _q_response = self.db.query(LeadCAPI).filter(
            LeadCAPI.created_at >= lookback_time,
            LeadCAPI.capi_response_status.isnot(None)
        )
        if self._filter_by_client:
            _q_response = _q_response.filter(text("leads_capi.client_id = :cid").bindparams(cid=_client_id))
        with_response = _q_response.all()

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

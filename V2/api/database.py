"""
Configuração do banco de dados PostgreSQL
Gerencia conexão com Cloud SQL e operações CRUD
"""

import os
from sqlalchemy import create_engine, Column, Integer, String, Text, TIMESTAMP, DECIMAL, func
from sqlalchemy.engine import URL
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

# Base para modelos SQLAlchemy
Base = declarative_base()

# =============================================================================
# MODELO: Lead CAPI
# =============================================================================

class LeadCAPI(Base):
    """Modelo para leads capturados com dados CAPI"""
    __tablename__ = 'leads_capi'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identificação
    email = Column(String(255), nullable=False, index=True)
    name = Column(String(255))  # Nome completo (mantido para compatibilidade)
    first_name = Column(String(255))  # Primeiro nome (para CAPI)
    last_name = Column(String(255))   # Sobrenome (para CAPI)
    phone = Column(String(50))

    # Dados CAPI
    fbp = Column(String(255))
    fbc = Column(String(255))
    event_id = Column(String(255), unique=True, index=True)

    # Tracking
    user_agent = Column(Text)
    client_ip = Column(String(50))
    event_source_url = Column(Text)

    # UTMs
    utm_source = Column(String(255))
    utm_medium = Column(String(255))
    utm_campaign = Column(String(255))
    utm_term = Column(String(255))
    utm_content = Column(String(255))

    # Outros
    tem_comp = Column(String(50))

    # Dados da Pesquisa (mapeados do Google Sheets)
    genero = Column(String(50))
    idade = Column(String(50))
    ocupacao = Column(String(255))
    faixa_salarial = Column(String(100))
    cartao_credito = Column(String(50))
    interesse_evento = Column(Text)
    estudou_programacao = Column(String(50))
    pretende_faculdade = Column(String(100))
    investiu_curso_online = Column(String(50))
    interesse_programacao = Column(Text)
    cidade = Column(String(100))

    # ML Scores
    lead_score = Column(DECIMAL(10, 8))
    decil = Column(String(10))
    scored_at = Column(TIMESTAMP)

    # Controle CAPI
    capi_sent_at = Column(TIMESTAMP, nullable=True, index=True)  # Quando foi enviado para CAPI
    capi_response_status = Column(String(20), nullable=True)  # "success", "error", "partial"
    capi_response_message = Column(Text, nullable=True)  # Detalhes de erro da Meta
    capi_events_received = Column(Integer, nullable=True)  # Eventos recebidos pela Meta
    capi_events_rejected = Column(Integer, nullable=True)  # Eventos rejeitados pela Meta

    # Timestamps
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> Dict:
        """Converte para dict"""
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'phone': self.phone,
            'fbp': self.fbp,
            'fbc': self.fbc,
            'event_id': self.event_id,
            'user_agent': self.user_agent,
            'client_ip': self.client_ip,
            'event_source_url': self.event_source_url,
            'utm_source': self.utm_source,
            'utm_medium': self.utm_medium,
            'utm_campaign': self.utm_campaign,
            'utm_term': self.utm_term,
            'utm_content': self.utm_content,
            'tem_comp': self.tem_comp,
            'genero': self.genero,
            'idade': self.idade,
            'ocupacao': self.ocupacao,
            'faixa_salarial': self.faixa_salarial,
            'cartao_credito': self.cartao_credito,
            'interesse_evento': self.interesse_evento,
            'estudou_programacao': self.estudou_programacao,
            'pretende_faculdade': self.pretende_faculdade,
            'investiu_curso_online': self.investiu_curso_online,
            'interesse_programacao': self.interesse_programacao,
            'cidade': self.cidade,
            'lead_score': float(self.lead_score) if self.lead_score else None,
            'decil': self.decil,
            'scored_at': self.scored_at.isoformat() if self.scored_at else None,
            'capi_sent_at': self.capi_sent_at.isoformat() if self.capi_sent_at else None,
            'capi_response_status': self.capi_response_status,
            'capi_response_message': self.capi_response_message,
            'capi_events_received': self.capi_events_received,
            'capi_events_rejected': self.capi_events_rejected,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

# =============================================================================
# CONFIGURAÇÃO DA ENGINE
# =============================================================================

def get_database_url() -> str:
    """
    Retorna URL de conexão com o banco

    Ordem de prioridade:
    1. DATABASE_URL (env var completa)
    2. CLOUD_SQL_CONNECTION_NAME (Cloud Run via Unix socket)
    3. Componentes individuais (DB_HOST, DB_NAME, etc)
    4. Fallback para SQLite local (desenvolvimento)
    """
    # Opção 1: URL completa
    if os.getenv('DATABASE_URL'):
        return os.getenv('DATABASE_URL')

    # Opção 2: Cloud SQL via Unix socket (Cloud Run)
    # Usa pg8000 driver que suporta Unix sockets
    instance_connection = os.getenv('CLOUD_SQL_CONNECTION_NAME')
    if instance_connection:
        db_name = os.getenv('DB_NAME', 'smart_ads')
        db_user = os.getenv('DB_USER', 'postgres')
        db_password = os.getenv('DB_PASSWORD', '')
        unix_socket_path = f"/cloudsql/{instance_connection}"
        logger.info(f"Conectando ao Cloud SQL via Unix socket: {instance_connection}")
        # Usar URL.create() para formato correto com pg8000
        return URL.create(
            drivername="postgresql+pg8000",
            username=db_user,
            password=db_password,
            database=db_name,
            query={"unix_sock": f"{unix_socket_path}/.s.PGSQL.5432"}
        )

    # Opção 3: Componentes individuais (Cloud SQL via IP)
    db_host = os.getenv('DB_HOST')
    db_port = os.getenv('DB_PORT', '5432')
    db_name = os.getenv('DB_NAME', 'smart_ads')
    db_user = os.getenv('DB_USER', 'postgres')
    db_password = os.getenv('DB_PASSWORD')

    if db_host and db_password:
        return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    # Opção 4: BLOQUEADO - SQLite não é permitido em produção
    # Se chegou aqui, nenhuma configuração de PostgreSQL foi encontrada
    environment = os.getenv('ENVIRONMENT', 'development')

    if environment == 'production':
        # PRODUÇÃO: BLOQUEAR DEPLOY SEM POSTGRESQL
        logger.critical("=" * 80)
        logger.critical("🚨 DEPLOY BLOQUEADO - CONFIGURAÇÃO DE BANCO DE DADOS AUSENTE 🚨")
        logger.critical("=" * 80)
        logger.critical("")
        logger.critical("NENHUMA das seguintes variáveis de ambiente foi encontrada:")
        logger.critical("  ❌ DATABASE_URL")
        logger.critical("  ❌ CLOUD_SQL_CONNECTION_NAME")
        logger.critical("  ❌ DB_HOST + DB_PASSWORD")
        logger.critical("")
        logger.critical("SQLite NÃO É PERMITIDO EM PRODUÇÃO!")
        logger.critical("Todos os dados de leads CAPI serão PERDIDOS a cada deploy com SQLite.")
        logger.critical("")
        logger.critical("SOLUÇÃO:")
        logger.critical("Configure Cloud SQL no deploy.sh ou adicione variáveis de ambiente:")
        logger.critical("  --update-env-vars=\"CLOUD_SQL_CONNECTION_NAME=smart-ads-451319:us-central1:smart-ads-db,DB_NAME=smart_ads,DB_USER=postgres,DB_PASSWORD=<senha>\"")
        logger.critical("")
        logger.critical("=" * 80)
        raise RuntimeError(
            "🚨 DEPLOY BLOQUEADO: PostgreSQL não configurado. "
            "SQLite não é permitido em produção devido a perda de dados em deploys."
        )

    # DESENVOLVIMENTO: Avisar mas permitir SQLite
    logger.warning("⚠️ Usando SQLite (desenvolvimento) - Configure PostgreSQL para produção!")
    logger.warning("⚠️ DADOS SERÃO PERDIDOS A CADA DEPLOY! Configure CLOUD_SQL_CONNECTION_NAME.")
    return "sqlite:////tmp/smart_ads_dev.db"

def get_engine():
    """Cria engine SQLAlchemy"""
    database_url = get_database_url()

    # SQLite precisa de configuração especial
    # database_url pode ser string ou objeto URL
    url_str = str(database_url) if not isinstance(database_url, str) else database_url

    if url_str.startswith('sqlite'):
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            echo=False
        )

    # PostgreSQL
    return create_engine(
        database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False
    )

# Engine global
engine = get_engine()

# SessionLocal para dependency injection
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_database():
    """Inicializa database (cria tabelas se não existirem)"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Database inicializado com sucesso")
        return True
    except Exception as e:
        logger.error(f"❌ Erro ao inicializar database: {e}")
        return False

def get_db() -> Session:
    """
    Dependency para FastAPI
    Uso: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =============================================================================
# OPERAÇÕES CRUD
# =============================================================================

def create_lead_capi(db: Session, lead_data: Dict) -> LeadCAPI:
    """Cria novo lead no banco"""
    lead = LeadCAPI(**lead_data)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead

def get_lead_by_email(db: Session, email: str) -> Optional[LeadCAPI]:
    """Busca lead por email (mais recente)"""
    return db.query(LeadCAPI).filter(LeadCAPI.email == email).order_by(LeadCAPI.created_at.desc()).first()

def get_lead_by_event_id(db: Session, event_id: str) -> Optional[LeadCAPI]:
    """Busca lead por event_id"""
    return db.query(LeadCAPI).filter(LeadCAPI.event_id == event_id).first()

def get_leads_by_emails(db: Session, emails: List[str]) -> List[LeadCAPI]:
    """Busca múltiplos leads por email (batch)"""
    return db.query(LeadCAPI).filter(LeadCAPI.email.in_(emails)).all()

def get_recent_leads(db: Session, limit: int = 100) -> List[LeadCAPI]:
    """Retorna leads mais recentes"""
    return db.query(LeadCAPI).order_by(LeadCAPI.created_at.desc()).limit(limit).all()

def count_leads(db: Session) -> int:
    """Conta total de leads"""
    return db.query(LeadCAPI).count()

def count_leads_with_fbp(db: Session) -> int:
    """Conta leads com FBP preenchido"""
    return db.query(LeadCAPI).filter(LeadCAPI.fbp.isnot(None)).count()

def count_leads_with_fbc(db: Session) -> int:
    """Conta leads com FBC preenchido"""
    return db.query(LeadCAPI).filter(LeadCAPI.fbc.isnot(None)).count()

def mark_lead_capi_sent(db: Session, email: str) -> bool:
    """Marca TODOS os registros do lead como enviado para CAPI"""
    try:
        # Buscar TODOS os registros com esse email (pode haver duplicatas)
        leads = db.query(LeadCAPI).filter(LeadCAPI.email == email).all()

        if not leads:
            logger.warning(f"⚠️ Lead {email} não encontrado no banco")
            return False

        # Marcar todos os registros
        for lead in leads:
            lead.capi_sent_at = func.now()

        db.commit()
        logger.info(f"✅ {len(leads)} registro(s) de {email} marcados como enviado para CAPI")
        return True
    except Exception as e:
        logger.error(f"❌ Erro ao marcar CAPI sent para {email}: {e}")
        db.rollback()
        return False

def update_capi_response(
    db: Session,
    email: str,
    status: str,
    events_received: int = 0,
    events_rejected: int = 0,
    error_message: Optional[str] = None
) -> bool:
    """
    Atualiza o status da resposta CAPI da Meta

    Args:
        db: Sessão do banco
        email: Email do lead
        status: "success", "error", ou "partial"
        events_received: Número de eventos que a Meta confirmou receber
        events_rejected: Número de eventos que a Meta rejeitou
        error_message: Mensagem de erro se houver

    Returns:
        True se atualizou com sucesso
    """
    try:
        # Buscar TODOS os registros com esse email (pode haver duplicatas)
        leads = db.query(LeadCAPI).filter(LeadCAPI.email == email).all()

        if not leads:
            logger.warning(f"⚠️ Lead {email} não encontrado no banco para atualizar CAPI response")
            return False

        # Atualizar todos os registros
        for lead in leads:
            lead.capi_response_status = status
            lead.capi_response_message = error_message
            lead.capi_events_received = events_received
            lead.capi_events_rejected = events_rejected

        db.commit()
        logger.debug(f"✅ {len(leads)} registro(s) de {email} atualizados com CAPI response: {status}")
        return True
    except Exception as e:
        logger.error(f"❌ Erro ao atualizar CAPI response para {email}: {e}")
        db.rollback()
        return False

def get_leads_not_sent_to_capi(db: Session, emails: List[str]) -> List[LeadCAPI]:
    """Busca leads que ainda NÃO foram enviados para CAPI"""
    return db.query(LeadCAPI).filter(
        LeadCAPI.email.in_(emails),
        LeadCAPI.capi_sent_at.is_(None)
    ).all()

def get_leads_already_sent_to_capi(db: Session, emails: List[str]) -> List[str]:
    """Retorna lista de emails que já foram enviados para CAPI"""
    leads = db.query(LeadCAPI.email).filter(
        LeadCAPI.email.in_(emails),
        LeadCAPI.capi_sent_at.isnot(None)
    ).all()
    return [lead[0] for lead in leads]

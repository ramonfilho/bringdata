"""
Configuração do banco de dados PostgreSQL
Gerencia conexão com Railway PostgreSQL e operações CRUD
"""

import os
from sqlalchemy import create_engine, Column, Integer, String, Text, TIMESTAMP, DECIMAL, func, text
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

    # Multi-cliente: client_id NÃO está mapeado aqui intencionalmente.
    # O schema Railway legado não tem essa coluna.
    # Quando um banco futuro tiver client_id, adicionar a linha abaixo e
    # re-ativar os filtros condicionais em has_client_id_column():
    #   client_id = Column(String(50), nullable=False, server_default=text("'devclub'"), index=True)

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
            'client_id': self.client_id,
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
    Retorna URL de conexão com o banco.

    Ordem de prioridade:
    1. DATABASE_URL (env var completa — genérico para qualquer cliente)
    2. RAILWAY_DB_* (variáveis Railway — cliente DevClub)
    """
    # Opção 1: URL completa
    if os.getenv('DATABASE_URL'):
        return os.getenv('DATABASE_URL')

    # Opção 2: Railway PostgreSQL
    railway_host = os.getenv('RAILWAY_DB_HOST')
    railway_password = os.getenv('RAILWAY_DB_PASSWORD')
    if railway_host and railway_password:
        port = os.getenv('RAILWAY_DB_PORT', '5432')
        name = os.getenv('RAILWAY_DB_NAME', 'railway')
        user = os.getenv('RAILWAY_DB_USER', 'postgres')
        logger.info(f"Conectando ao Railway PostgreSQL: {railway_host}:{port}/{name}")
        return f"postgresql://{user}:{railway_password}@{railway_host}:{port}/{name}"

    raise RuntimeError(
        "Configuração de banco de dados ausente. "
        "Defina DATABASE_URL ou RAILWAY_DB_HOST + RAILWAY_DB_PASSWORD."
    )

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

# Cache: None = não verificado ainda; True/False = resultado da verificação
_client_id_column_exists: Optional[bool] = None

def has_client_id_column(db: Session) -> bool:
    """
    Verifica se a coluna client_id existe em leads_capi.

    Cacheado em memória — a verificação ocorre apenas uma vez por processo.
    Quando a coluna não existe (ex: Railway legado), os filtros por client_id
    são omitidos automaticamente. Quando existir em futuros bancos, o filtro
    passa a ser aplicado sem nenhuma mudança de código.
    """
    global _client_id_column_exists
    if _client_id_column_exists is None:
        try:
            result = db.execute(text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_name = 'leads_capi' AND column_name = 'client_id'"
            ))
            _client_id_column_exists = result.scalar() > 0
            if _client_id_column_exists:
                logger.info("✅ Coluna client_id detectada — filtro multi-cliente ativo")
            else:
                logger.info("ℹ️  Coluna client_id ausente — filtro multi-cliente desativado (schema legado)")
        except Exception as e:
            logger.warning(f"⚠️  Erro ao verificar coluna client_id: {e} — assumindo ausente")
            _client_id_column_exists = False
            try:
                db.rollback()
            except Exception:
                pass
    return _client_id_column_exists

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
    """Cria novo lead no banco. lead_data deve conter 'client_id'."""
    lead = LeadCAPI(**lead_data)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead

def get_lead_by_email(db: Session, email: str, client_id: str = 'devclub') -> Optional[LeadCAPI]:
    """Busca lead por email (mais recente) dentro do cliente."""
    q = db.query(LeadCAPI).filter(LeadCAPI.email == email)
    if has_client_id_column(db):
        q = q.filter(text("leads_capi.client_id = :cid").bindparams(cid=client_id))
    return q.order_by(LeadCAPI.created_at.desc()).first()

def get_lead_by_event_id(db: Session, event_id: str) -> Optional[LeadCAPI]:
    """Busca lead por event_id (global — event_id já é único por construção)."""
    return db.query(LeadCAPI).filter(LeadCAPI.event_id == event_id).first()

def get_leads_by_emails(db: Session, emails: List[str], client_id: str = 'devclub') -> List[LeadCAPI]:
    """Busca múltiplos leads por email dentro do cliente."""
    q = db.query(LeadCAPI).filter(LeadCAPI.email.in_(emails))
    if has_client_id_column(db):
        q = q.filter(text("leads_capi.client_id = :cid").bindparams(cid=client_id))
    return q.all()

def get_recent_leads(db: Session, limit: int = 100, client_id: str = 'devclub') -> List[LeadCAPI]:
    """Retorna leads mais recentes do cliente."""
    q = db.query(LeadCAPI)
    if has_client_id_column(db):
        q = q.filter(text("leads_capi.client_id = :cid").bindparams(cid=client_id))
    return q.order_by(LeadCAPI.created_at.desc()).limit(limit).all()

def count_leads(db: Session, client_id: str = 'devclub') -> int:
    """Conta total de leads do cliente."""
    q = db.query(LeadCAPI)
    if has_client_id_column(db):
        q = q.filter(text("leads_capi.client_id = :cid").bindparams(cid=client_id))
    return q.count()

def count_leads_with_fbp(db: Session, client_id: str = 'devclub') -> int:
    """Conta leads com FBP preenchido do cliente."""
    q = db.query(LeadCAPI).filter(LeadCAPI.fbp.isnot(None))
    if has_client_id_column(db):
        q = q.filter(text("leads_capi.client_id = :cid").bindparams(cid=client_id))
    return q.count()

def count_leads_with_fbc(db: Session, client_id: str = 'devclub') -> int:
    """Conta leads com FBC preenchido do cliente."""
    q = db.query(LeadCAPI).filter(LeadCAPI.fbc.isnot(None))
    if has_client_id_column(db):
        q = q.filter(text("leads_capi.client_id = :cid").bindparams(cid=client_id))
    return q.count()

def mark_lead_capi_sent(db: Session, email: str, client_id: str = 'devclub') -> bool:
    """Marca TODOS os registros do lead (deste cliente) como enviado para CAPI"""
    try:
        leads = db.query(LeadCAPI).filter(
            LeadCAPI.email == email, LeadCAPI.client_id == client_id
        ).all()

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
    error_message: Optional[str] = None,
    client_id: str = 'devclub'
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
        client_id: Identificador do cliente

    Returns:
        True se atualizou com sucesso
    """
    try:
        leads = db.query(LeadCAPI).filter(
            LeadCAPI.email == email, LeadCAPI.client_id == client_id
        ).all()

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

def get_leads_not_sent_to_capi(db: Session, emails: List[str], client_id: str = 'devclub') -> List[LeadCAPI]:
    """Busca leads que ainda NÃO foram enviados para CAPI (deste cliente)."""
    return db.query(LeadCAPI).filter(
        LeadCAPI.email.in_(emails),
        LeadCAPI.client_id == client_id,
        LeadCAPI.capi_sent_at.is_(None)
    ).all()

def get_leads_already_sent_to_capi(db: Session, emails: List[str], client_id: str = 'devclub') -> List[str]:
    """Retorna lista de emails que já foram enviados para CAPI (deste cliente)."""
    leads = db.query(LeadCAPI.email).filter(
        LeadCAPI.email.in_(emails),
        LeadCAPI.client_id == client_id,
        LeadCAPI.capi_sent_at.isnot(None)
    ).all()
    return [lead[0] for lead in leads]


def get_database_url_for_client(client_config) -> str:
    """
    Retorna URL de conexão para o banco do cliente específico.
    Usa InfraConfig.db_url_env_var como nome da env var a ler.
    Fallback para get_database_url() (comportamento legado).

    Preparado para A2 (pipeline dict por cliente).
    """
    if client_config and hasattr(client_config, 'infra') and client_config.infra:
        env_var = getattr(client_config.infra, 'db_url_env_var', None)
        if env_var == 'RAILWAY':
            # Modo Railway: compor URL a partir de RAILWAY_DB_* env vars
            host = os.getenv('RAILWAY_DB_HOST')
            password = os.getenv('RAILWAY_DB_PASSWORD')
            if host and password:
                port = os.getenv('RAILWAY_DB_PORT', '5432')
                name = os.getenv('RAILWAY_DB_NAME', 'railway')
                user = os.getenv('RAILWAY_DB_USER', 'postgres')
                return f"postgresql://{user}:{password}@{host}:{port}/{name}"
        elif env_var and os.getenv(env_var):
            return os.getenv(env_var)
    return get_database_url()

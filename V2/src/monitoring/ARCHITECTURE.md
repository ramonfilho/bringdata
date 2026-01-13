# Arquitetura de Monitoramento Centralizado

## Estrutura de Arquivos

```
src/monitoring/
├── __init__.py                  # já existe
├── category_tracker.py          # já existe (drift detection functions)
├── models.py                    # Alert, Severity, AlertCategory
├── orchestrator.py              # MonitoringOrchestrator
├── checks/
│   ├── __init__.py
│   ├── base.py                  # BaseMonitor (abstract)
│   ├── data_quality.py          # DataQualityMonitor (usa category_tracker.py)
│   ├── operational.py           # OperationalMonitor
│   └── capi_quality.py          # CAPIQualityMonitor
└── notifiers/
    ├── __init__.py
    └── slack.py                 # SlackNotifier (futuro)

api/
└── app.py                       # endpoint /monitoring/daily-check
```

## Fluxo de Execução

```
Apps Script (00:00 diário)
    ↓
Busca últimas 24h do Google Sheets
    ↓
POST /monitoring/daily-check
    body: { "leads": [...] }
    ↓
MonitoringOrchestrator
    ├── DataQualityMonitor(leads_data)    ← Usa JSON do Sheets
    ├── OperationalMonitor(db)            ← Usa PostgreSQL
    └── CAPIQualityMonitor(db)            ← Usa PostgreSQL
    ↓
Retorna List[Alert]
```

## Checks Implementados

### 1. DataQualityMonitor (fonte: Sheets via JSON)
- **category_drift**: Categorias não vistas no treino
- **distribution_drift**: Mudanças drásticas nas proporções (threshold: 15pp cat, 2σ num)
- **missing_rate_high**: Missing rate > 20% em qualquer coluna
- **score_distribution_change**: Mudança nas proporções de decis

### 2. OperationalMonitor (fonte: PostgreSQL)
- **no_leads_6h**: Mais de 6h sem receber leads (`created_at`)
- **no_capi_6h**: Mais de 6h sem enviar CAPI (`capi_sent_at`)

### 3. CAPIQualityMonitor (fonte: PostgreSQL)
- **capi_missing_rate_high**: Missing rate fbp/fbc > 50%
- **capi_rejection_high**: Alta taxa de rejeição (via logs - futuro)

## Modelos de Dados

### Alert
```python
@dataclass
class Alert:
    type: str                # 'category_drift', 'no_leads_6h', etc
    severity: Severity       # HIGH, MEDIUM, LOW
    category: AlertCategory  # DATA_QUALITY, OPERATIONAL, CAPI_QUALITY
    message: str             # Texto user-friendly
    details: Dict            # Dados técnicos
    timestamp: datetime
    metric_value: float      # Valor da métrica
    threshold: float         # Threshold usado
```

### Severity
```python
class Severity(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
```

### AlertCategory
```python
class AlertCategory(Enum):
    DATA_QUALITY = "data_quality"
    OPERATIONAL = "operational"
    CAPI_QUALITY = "capi_quality"
```

## Interface BaseMonitor

```python
class BaseMonitor(ABC):
    @abstractmethod
    def check(self, *args, **kwargs) -> List[Alert]:
        """Executa checks e retorna lista de alertas"""
        pass
```

## API Endpoint

```python
@app.post("/monitoring/daily-check")
async def daily_monitoring_check(
    request: DailyCheckRequest,
    db: Session = Depends(get_db)
) -> DailyCheckResponse:
    """
    Request:
        {
            "leads": [
                {
                    "Data": "2026-01-12 10:30:00",
                    "E-mail": "...",
                    "lead_score": 0.75,
                    "decil": "D8",
                    ... (todas colunas do Sheets)
                }
            ]
        }

    Response:
        {
            "total_alerts": 5,
            "alerts_by_severity": {"HIGH": 2, "MEDIUM": 1, "LOW": 2},
            "alerts_by_category": {"data_quality": 3, "operational": 1, "capi_quality": 1},
            "alerts": [...]
        }
    """
```

## Fontes de Dados

| Check | Fonte | Campos Necessários |
|-------|-------|-------------------|
| Category drift | Sheets → JSON | Todas colunas categóricas (14) |
| Distribution drift | Sheets → JSON | Todas colunas categóricas (14) |
| Missing rate | Sheets → JSON | Todas colunas |
| Score distribution | Sheets → JSON | lead_score, decil |
| 6h sem leads | PostgreSQL | created_at |
| 6h sem CAPI | PostgreSQL | capi_sent_at |
| CAPI missing rate | PostgreSQL | fbp, fbc |
| CAPI rejection | Cloud Run logs | (futuro) |

## Thresholds Configuráveis

```python
# src/monitoring/config.py
THRESHOLDS = {
    'category_drift': {
        'enabled': True
    },
    'distribution_drift': {
        'categorical': 0.15,  # 15pp
        'numerical': 2.0      # 2σ
    },
    'missing_rate': {
        'threshold': 0.20     # 20%
    },
    'score_distribution': {
        'threshold': 0.10     # 10pp por decil
    },
    'operational': {
        'no_leads_hours': 6,
        'no_capi_hours': 6
    },
    'capi_quality': {
        'missing_rate': 0.50  # 50%
    }
}
```

## Dependências

- Google Sheets: Apps Script busca dados via Sheets API
- PostgreSQL: API acessa via SQLAlchemy (já configurado)
- Modelo ML: Usa arquivos `categorias_esperadas.json` e `distribuicoes_esperadas.json`
- Cloud Run: API hospedada (já em produção)

# CLAUDE.md — Bring Data V2

Leia este arquivo no início de toda sessão antes de qualquer tarefa.

---

## Documentos autoritativos

| Documento | O que contém |
|---|---|
| `docs/ARQUITETURA_SISTEMA_COMPLETA.md` | Arquitetura completa, fluxos, endpoints, comandos úteis |
| `docs/PLANO_REFACTOR_MLOPS.md` | Plano de refactor em andamento, mapeamento de hardcodes, decisões arquiteturais |

Quando houver dúvida sobre o que um componente deve fazer, esses documentos são a fonte de verdade.

---

## Contexto de negócio

- **Cliente atual:** DevClub (curso de programação)
- **Segundo cliente:** chegando em breve — toda decisão arquitetural deve considerar multi-cliente
- **Fluxo de lançamento:** Semana 1 captação (7d) → Semana 2 CPL/nutrição (6d) → Semana 3 vendas/carrinho (7d)
- **Sinal central:** lead preenche pesquisa → modelo atribui decil D1–D10 → evento `LeadQualified` enviado ao Meta em ~5 minutos com valor proporcional ao decil

---

## Regras críticas de sincronização

**Toda transformação de dados deve ser idêntica em treino, produção e monitoramento.**

Já houve quebra em produção por divergência de normalização (UTM com `.lower()` aplicado no treino mas não na produção). Esta é a principal motivação do refactor para `src/core/`.

- Treino (`train_pipeline.py`) importa 100% de `core/` para transformações
- Produção (`production_pipeline.py`) importa 100% de `core/` — comportamento idêntico ao treino por construção
- Monitoramento (`monitoring/orchestrator.py`) chama `core.preprocessing.preprocess()` com wrapper de preservação de `decil`/`lead_score`
- **Nunca reimplementar uma transformação fora de `core/`**

---

## O que é canônico quando há conflito

| Componente | Versão canônica |
|---|---|
| Encoding | `encoding.py` de produção (tem feature registry, reordenação, `mapeamentos_especificos`) |
| UTM unification | `core/utm.py` com `.lower()` — corrige divergência histórica |
| Medium unification | `core/medium.py` — elimina os 3 arquivos atuais |
| Matching | `core/matching.py` — consolida os 6 arquivos de `src/matching/` |
| Janela de conversão | Simétrica — remove TODOS os leads após `date_limite`, não só `target=1` |

---

## Convenção de assinatura em `src/core/`

Todas as funções em `src/core/` seguem o padrão:

```python
def transform(df: pd.DataFrame, config: SubConfig, **artifacts) -> pd.DataFrame:
```

Funções utilitárias sem DataFrame seguem:

```python
def utility_name(input, config: SubConfig) -> output:
```

Nunca adicionar hardcodes dentro de funções `core/`. Todo valor específico de cliente vem do `ClientConfig`.

---

## ClientConfig

- Carregado de `configs/clients/{cliente}.yaml`
- Dataclass tipado em `src/core/client_config.py`
- Todo campo novo deve ter valor default para não quebrar clientes existentes
- Após refactor: modelo ativo em `configs/active_models/{cliente}.yaml` (hoje: `configs/active_model.yaml`)

---

## O que não tocar sem aprovação explícita

- `configs/active_model.yaml` — aponta para o modelo em produção
- `src/production_pipeline.py` em produção — qualquer mudança requer teste completo de paridade com treino
- `META_ACCESS_TOKEN` — expira a cada 60 dias, não alterar
- Pipelines em execução no Cloud Run

---

## Como rodar localmente

```bash
# Banco de dados (Cloud SQL Proxy)
cloud-sql-proxy smart-ads-451319:us-central1:bring-data-db --port=5432 &
sleep 8
export DB_HOST=127.0.0.1 DB_PORT=5432 DB_NAME=bring_data DB_USER=postgres DB_PASSWORD=SmartAds2026DB!

# Treinar modelo
python -m src.train_pipeline --initial-matching email_telefone --set-active

# Monitoramento local
bash src/monitoring/run_monitoring_local.sh

# Retreino mensal
python src/retrain/retraining_orchestrator.py --config configs/retreino_mensal.yaml
```

---

## Estado atual do refactor (branch `refactor/mlops-core`)

**Implementado em `src/core/`:**
- `client_config.py` — dataclass ClientConfig com sub-configs
- `utils.py`, `ingestion.py`, `column_unification.py`, `category_unification.py`
- `utm.py`, `medium.py`, `matching.py`, `dataset_versioning.py`
- `feature_engineering.py`, `encoding.py`, `preprocessing.py`

**Pendente:**
- Migração de `train_pipeline.py` para importar de `core/`
- Migração de `production_pipeline.py` para importar de `core/`
- Migração de `monitoring/orchestrator.py`
- `configs/clients/devclub.yaml` com todos os hardcodes mapeados
- Retreino automático Sprint 2–3 (comparação champion/challenger, deploy condicional)

---

## Divergências conhecidas ainda não resolvidas

| Divergência | Localização | Status |
|---|---|---|
| UTM `.lower()` | `utm_unification.py:36` vs `utm_training.py` | Resolvido em `core/utm.py` — pendente migração |
| Medium mapping_dict | `medium_unification.py` vs `medium_training.py` | Resolvido em `core/medium.py` — pendente migração |
| Encoding ordinal nomes de colunas | treino usa `'idade'`; produção usa `'Qual a sua idade?'` | Pendente em `core/encoding.py` |
| `binary_top3` Medium | Removido do treino; produção ainda usa | Verificar `encoding.py` antes de migrar |
| `nome_valido`/`email_valido`/`telefone_valido` | Removidos do treino; verificar se produção ainda cria | Pendente |

---

## Infraestrutura de produção

- **API:** FastAPI + Uvicorn em Cloud Run (`https://bring-data-api-12955519745.us-central1.run.app`)
- **Banco:** PostgreSQL Cloud SQL (`smart-ads-451319:us-central1:bring-data-db`)
- **Tabela principal:** `leads_capi`
- **Scheduler:** Cloud Scheduler → Cloud Run Job (monitoramento diário, retreino mensal)
- **Notificações:** Slack

```bash
# Ver logs do Cloud Run
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=bring-data-api" --limit=50
```

# Modelo Guru Only (tmb_risk_filter=none)

Modelo treinado **sem alunos TMB** no dataset. Usar quando o cliente quiser otimizar anúncios exclusivamente para leads orgânicos (Guru), sem o ruído de ex-alunos de concorrentes.

---

## Modelo de standby disponível

| Campo | Valor |
|---|---|
| Run ID | `a859c68b1cb94c3b93767a3131eda89a` |
| Treinado em | 24/03/2026 |
| AUC | 0.737 |
| Monotonia | 88.9% (quebra em D02→D03, suavizada via PAV no CAPI) |
| Lift máximo | 3.3x |
| Período dos dados | 27/10/2025 → 03/03/2026 (127 dias) |
| Leads | 67.457 (47.219 treino / 20.238 teste) |
| Positivos | 415 (0.62%) |
| Features | 59 |
| Split | temporal_leads (70/30) |
| Matching | email_telefone |
| Hiperparâmetros | n_estimators=300, max_depth=8, max_features=sqrt, min_samples_leaf=1 |

---

## Como ativar (sem retreinar)

> **O modelo de produção atual é TMB All (`2a98e51ca4834697bbc94ec3dd31fcf7`).**
> O Guru Only só entra em produção se você rodar o comando abaixo e fizer o deploy explicitamente.
> O próximo deploy automático vai subir o que estiver nos arquivos — não rode o comando abaixo sem intenção de fazer o deploy em seguida.

```bash
# 1. Ativar o Guru Only localmente (altera 3 arquivos)
python -m src.train_pipeline --activate-run a859c68b1cb94c3b93767a3131eda89a

#    Arquivos alterados:
#    - configs/active_models/devclub.yaml  → run_id atualizado
#    - api/business_config.py              → CONVERSION_RATES atualizadas (com PAV)
#    - configs/clients/devclub.yaml        → business.conversion_rates atualizado

# 2. Deploy
# gcloud run deploy ...

# Para voltar ao TMB All:
python -m src.train_pipeline --activate-run 2a98e51ca4834697bbc94ec3dd31fcf7
```

---

## Como testar localmente antes do deploy

```bash
# Subir a API localmente
uvicorn api.app:app --reload

# Enviar um lead de teste
curl -X POST http://localhost:8000/predict/single \
  -H "Content-Type: application/json" \
  -d '{"email": "teste@exemplo.com", ...}'

# Conferir o decil e o valor projetado na resposta
```

Inspecionar os arquivos alterados sem subir: os arquivos são modificados localmente pelo `--activate-run`. O Cloud Run não é afetado até o deploy explícito.

---

## Fallback: retreinar do zero

Se o run `a859c68b` ficar inválido ou os dados precisarem ser atualizados:

```bash
python -m src.train_pipeline \
  --tmb-risk-filter none \
  --split-method temporal_leads \
  --initial-matching email_telefone \
  --hyperparams '{"n_estimators": 300, "max_depth": 8, "max_features": "sqrt", "min_samples_leaf": 1, "min_samples_split": 2}' \
  --set-active
```

> O modelo retreinado não será idêntico ao original (os dados cresceram), mas seguirá a mesma receita.

---

## Quando usar Guru Only vs TMB All

| Cenário | Modelo |
|---|---|
| Lançamento padrão (público misto) | TMB All — mais dados, melhor AUC |
| Campanha focada em novatos | Guru Only — sem ruído de ex-alunos TMB |
| Cliente sinaliza que TMB converte menos | Guru Only |

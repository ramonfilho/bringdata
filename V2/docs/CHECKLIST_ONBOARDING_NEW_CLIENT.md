# Checklist Onboarding — Novo Cliente

## 1. Criar o YAML do cliente

Copiar `configs/clients/devclub.yaml` → `configs/clients/{novo_cliente}.yaml`

Campos obrigatórios para ajustar:

- `client_id` — identificador único (ex: `"novaempresa"`)
- `ingestion.tmb_detection_columns` — colunas que identificam o arquivo TMB (se aplicável)
- `ingestion.pesquisa_date_column` — nome da coluna de data no formulário
- `ingestion.product_filter_keyword` — palavra-chave para filtrar produtos do cliente
- `ingestion.has_tmb` — `true` se usa TMB, `false` se só Guru
- `validation.required_survey_columns` — colunas obrigatórias no formulário do cliente
- `validation.required_sales_columns` — colunas obrigatórias no arquivo de vendas
- `validation.feature_missing_thresholds` — features críticas do modelo e seus thresholds de missing

---

## 2. Inspecionar os dados brutos

Antes de treinar, confirmar manualmente:

- [ ] Nomes exatos das colunas no formulário (Google Sheets ou Excel)
- [ ] Nomes exatos das colunas no arquivo de vendas
- [ ] Identificador do produto a filtrar (ex: nome do curso)
- [ ] Se tem plataforma de pagamento parcelado (TMB ou equivalente)
- [ ] Formato da coluna de data (ex: `dd/mm/yyyy`)

Atualizar o YAML com o que for encontrado.

---

## 3. Treinar o modelo

```bash
python -m src.train_pipeline \
  --client {novo_cliente} \
  --initial-matching email_telefone \
  --set-active
```

O pipeline vai:
- Validar o schema na **Célula 4** (colunas, tamanho, datas, email)
- Validar missing rates na **Célula 8** (features críticas vs. thresholds)
- Explodir com mensagem clara se algo estiver errado no formato dos dados

---

## 4. Verificar no MLflow

Após o treino confirmar:

- [ ] Experimento criado com nome `{client_id}_lead_scoring`
- [ ] AUC dentro do esperado para o cliente
- [ ] Arquivo `configs/active_models/{client_id}.yaml` gerado pelo `--set-active`

---

## 5. Deploy

O mesmo serviço Cloud Run serve múltiplos clientes — o `client_id` é passado no payload do `/predict/batch`. Não é necessário novo deploy.

Verificar apenas:

- [ ] `configs/clients/{novo_cliente}.yaml` está no repositório
- [ ] `configs/active_models/{novo_cliente}.yaml` existe (gerado pelo `--set-active`)
- [ ] Variáveis de ambiente do cliente (META_PIXEL_ID, etc.) estão configuradas no Cloud Run

---

## Referências

- Arquitetura completa: `docs/ARQUITETURA_SISTEMA_COMPLETA.md`
- Hardcodes e campos do ClientConfig: `docs/PLANO_REFACTOR_MLOPS.md`
- Exemplo de config completo: `configs/clients/devclub.yaml`

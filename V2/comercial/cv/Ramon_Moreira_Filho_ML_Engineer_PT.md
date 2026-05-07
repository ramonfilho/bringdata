# Ramon Moreira Filho

**Machine Learning Engineer · MLOps · Data Scientist**

Belo Horizonte, MG, Brasil · +55 37 99961-0179 · ramon@bring-data.com · linkedin.com/in/ramon-moreira-filho

---

## RESUMO

Machine Learning Engineer com 7 anos em captação digital (+120 ciclos de lançamento) e 4 anos em projetos de ciência de dados ponta-a-ponta. Fundador da Bring Data, onde desenvolvi sozinho um sistema de lead scoring em produção que envia sinais de propensão ao Meta via Conversions API em menos de 5 minutos.

Resultado verificado em operação real: **R$ 470k de margem incremental em 4 meses**, **+92¢ por R$1 investido em anúncios**, ROAS superior em **12 de 12 lançamentos** vs Controle (**p<0,05 em 5 de 7 testes A/B**), CPL **27–44% menor**.

Especialista em MLOps end-to-end, arquitetura multi-cliente e patterns de produção: parity audit treino↔serving, feature registry, canary deploy gradual, fail-loud asserts, validador pré-encoding.

---

## EXPERIÊNCIA PROFISSIONAL

### Machine Learning Engineer — Bring Data — Jan/2025 – Presente
*Fundador e único desenvolvedor. Sistema de lead scoring por ML em produção no GCP, arquitetura multi-tenant.*

- **Sistema end-to-end** com RandomForest sobre 59 features (AUC 0,745); arquitetura multi-cliente via `ClientConfig` (153 hardcodes refatorados em 15 sub-configs tipadas em Python) — novos clientes onboardados sem alteração de código.

- **Resultado verificado (DevClub, 4 meses):** R$ 470k de margem incremental · +92¢ por R$1 em anúncios · ROAS superior em **12/12 lançamentos** vs Controle (**p<0,05 em 5/7** testes A/B) · CPL **27–44% menor** · zero canibalização (Pearson −0,23).

- **MLOps em produção:** SSoT `src/core/` (15 módulos) elimina training-serving skew por construção; **parity audit** coluna-a-coluna entre treino e produção; **feature registry** sincronizado via MLflow; **fail-loud asserts** obrigatórios em transformações críticas; **canary deploy** gradual (`--no-traffic` → 5% → 10% → 100%) com **progression gate** automatizado; **validador pré-encoding** com snapshot offline.

- **Infraestrutura GCP:** 31 endpoints FastAPI em Cloud Run + Cloud Scheduler + MLflow (Cloud SQL Postgres + GCS) + Railway PostgreSQL (~100k leads em produção). 11 itens de safeguard Tier 1 entregues incrementalmente.

- **Retraining mensal** com hook injection (zero duplicação de lógica de treino) e quality gate em AUC, monotonia e concentração de positivos antes de promover. **A/B champion/challenger** em produção via UTM routing com event names CAPI distintos — ROAS por modelo lido direto no Ads Manager.

- **Monitoramento diário automatizado** (drift de features, qualidade CAPI/FBP/FBC, taxa de rejeição Meta, 12 pontos de verificação por ciclo) com alertas Slack. **Integrações:** Meta Conversions API, Guru, Hotmart, Google Sheets via Apps Script.

### Cientista de Dados — Data Mundo — Jun/2024 – Jan/2025

- Projetos end-to-end: EDA, modelagem preditiva, entrega em produção.
- Pipelines ETL com SQL, Pandas e Apache Spark para grandes volumes de dados.
- Modelos preditivos (Random Forest, XGBoost, LightGBM) para churn e otimização de campanhas — **+20% ROI**.
- Dashboards em Power BI e Tableau; relatórios executivos para stakeholders não-técnicos.

### Fundador & Diretor de Dados — Produções de Los Angeles — Jan/2017 – Jun/2024

- Estratégias data-driven para campanhas digitais — mais de **US$ 450k anuais** em receita.
- Lead scoring com ML supervisionado — redução de **15% no custo de aquisição** de leads.
- Integrações de coleta em tempo real via API (Google Ads, Meta Ads).
- **+120 ciclos de lançamento** em produtos de educação digital — domínio profundo do funil de captação.

---

## PROJETO PRINCIPAL — BRING DATA

Sistema de ML que classifica leads em decis D1–D10 e envia sinal calibrado ao Meta via Conversions API em <5 min — algoritmo do Meta otimiza para perfis com maior probabilidade de conversão real, não só de preenchimento de formulário.

| | |
|---|---|
| **Arquitetura** | FastAPI · Cloud Run · Cloud Scheduler · MLflow (Cloud SQL + GCS) · Railway PostgreSQL · scikit-learn (RandomForest, 59 features) · facebook-business · Apps Script |
| **Patterns MLOps** | Parity audit · feature registry · fail-loud · canary deploy · validador pré-encoding · dispatch CAPI por plataforma · A/B via UTM com event names distintos |
| **Resultado** | R$ 470k incremental · +92¢/R$1 · 12/12 lançamentos · p<0,05 em 5/7 A/B · CPL −27% a −44% · top-2 decis converte 3× acima da média |

---

## HABILIDADES TÉCNICAS

| | |
|---|---|
| **Linguagens** | Python, SQL, R, JavaScript (Node.js) |
| **ML** | Scikit-learn, XGBoost, LightGBM, RandomForest, SHAP, TensorFlow, PyTorch |
| **MLOps Patterns** | Parity audit (treino↔serving), feature registry, fail-loud asserts, canary deploy gradual, schema validation pré-treino, A/B via UTM routing, dispatch por plataforma, retraining com quality gate |
| **MLOps Tooling** | MLflow, FastAPI, Pydantic, SQLAlchemy, Docker, Cloud Run, Cloud Scheduler, Git/GitHub, CI/CD |
| **Cloud / Infra** | GCP (Cloud Run, Cloud SQL, Cloud Storage, BigQuery, Cloud Logging) · AWS (S3, EC2, SageMaker) |
| **Bancos de dados** | PostgreSQL (Railway, Cloud SQL), MySQL, BigQuery, SQLite |
| **Visualização** | Power BI, Tableau, Plotly, Matplotlib, ggplot2 |
| **Big Data** | Apache Spark, Apache Airflow |
| **Integrações** | Meta Conversions API (facebook-business), Meta Ads API, Google Ads API, Google Sheets API + Apps Script, Guru API, Hotmart API |

---

## FORMAÇÃO & CERTIFICAÇÕES

| Instituição | Programa |
|---|---|
| **Stanford / DeepLearning.AI** | Machine Learning Specialization — Andrew Ng |
| **DeepLearning.AI** | Machine Learning in Production — MLOps Specialization |
| **Google** | Machine Learning Engineer Professional Certificate |
| **University of Michigan** | Python for Everybody |
| **IBM / Coursera** | Databases and SQL for Data Science |
| **MLOps Community** | First Stack MLOps |
| **Data Mundo** | Certificação em Ciência de Dados |

---

## IDIOMAS

Português — Nativo · Inglês — Fluente · Espanhol — Fluente

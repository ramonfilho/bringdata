# Ramon Moreira Filho

**Machine Learning Engineer · MLOps · Data Scientist**
*Available for international relocation*

Belo Horizonte, MG, Brazil · +55 37 99961-0179 · ramon@bring-data.com · linkedin.com/in/ramon-moreira-filho

---

## SUMMARY

Machine Learning Engineer with 7 years in digital lead acquisition (+120 launch cycles) and 4 years focused on end-to-end data science projects. Founder of Bring Data, where I single-handedly built a production lead scoring system that sends propensity signals to Meta via the Conversions API in under 5 minutes.

Verified results in real operation: **R$ 470k of incremental margin in 4 months**, **+R$ 0.92 returned per R$ 1 invested in ads**, higher ROAS in **12 of 12 launches** vs Control (**p<0.05 in 5 of 7 A/B tests**), CPL **27–44% lower**.

Specialist in end-to-end MLOps, multi-tenant architecture, and production patterns: training-serving parity audit, feature registry, gradual canary deploy, fail-loud asserts, pre-encoding validator.

---

## PROFESSIONAL EXPERIENCE

### Machine Learning Engineer — Bring Data — Jan/2025 – Present
*Founder and sole developer. ML lead scoring system in production on GCP, multi-tenant architecture.*

- **End-to-end system** with RandomForest over 59 features (AUC 0.745); multi-tenant architecture via `ClientConfig` (153 hardcodes refactored into 15 typed sub-configs in Python) — new clients onboarded with no code changes.

- **Verified results (DevClub, 4 months):** R$ 470k incremental margin · +R$ 0.92 returned per R$ 1 spent on ads · higher ROAS in **12/12 launches** vs Control (**p<0.05 in 5/7** A/B tests) · CPL **27–44% lower** · zero cannibalization (Pearson −0.23).

- **Production MLOps:** SSoT `src/core/` (15 modules) eliminates training-serving skew by construction; column-by-column **parity audit** between training and production; **feature registry** synchronized via MLflow; mandatory **fail-loud asserts** on critical transforms; gradual **canary deploy** (`--no-traffic` → 5% → 10% → 100%) with automated **progression gate**; **pre-encoding validator** with offline snapshot.

- **GCP infrastructure:** 31 FastAPI endpoints on Cloud Run + Cloud Scheduler + MLflow (Cloud SQL Postgres + GCS) + Railway PostgreSQL (~100k leads in production). 11 Tier 1 safeguard items delivered incrementally.

- **Monthly retraining** with hook injection (zero training-logic duplication) and quality gate on AUC, monotonicity and positives concentration before promotion. **A/B champion/challenger** in production via UTM routing with distinct CAPI event names — per-model ROAS read directly from Meta Ads Manager.

- **Daily automated monitoring** (feature drift, CAPI/FBP/FBC quality, Meta rejection rate, 12 verification points per cycle) with Slack alerts. **External integrations:** Meta Conversions API, Guru, Hotmart, Google Sheets via Apps Script.

### Data Scientist — Data Mundo — Jun/2024 – Jan/2025

- End-to-end projects: EDA, predictive modeling, production delivery.
- ETL pipelines with SQL, Pandas and Apache Spark for large data volumes.
- Predictive models (Random Forest, XGBoost, LightGBM) for churn and campaign optimization — **+20% ROI**.
- Power BI and Tableau dashboards; executive reports for non-technical stakeholders.

### Founder & Data Director — Produções de Los Angeles — Jan/2017 – Jun/2024

- Data-driven strategies for digital campaigns — over **US$ 450k annually** in revenue.
- Lead scoring with supervised ML — **15% reduction in lead acquisition cost**.
- Real-time data collection integrations via API (Google Ads, Meta Ads).
- **+120 launch cycles** in digital education products — deep domain knowledge of acquisition funnels.

---

## MAIN PROJECT — BRING DATA

ML system that classifies leads into deciles D1–D10 and sends a calibrated signal to Meta via Conversions API in <5 min — Meta's algorithm optimizes for profiles with higher real conversion probability, not just form completions.

| | |
|---|---|
| **Architecture** | FastAPI · Cloud Run · Cloud Scheduler · MLflow (Cloud SQL + GCS) · Railway PostgreSQL · scikit-learn (RandomForest, 59 features) · facebook-business · Apps Script |
| **MLOps patterns** | Parity audit · feature registry · fail-loud · canary deploy · pre-encoding validator · per-platform CAPI dispatch · A/B via UTM with distinct event names |
| **Outcome** | R$ 470k incremental · +R$ 0.92 / R$ 1 · 12/12 launches · p<0.05 in 5/7 A/B · CPL −27% to −44% · top-2 deciles convert 3× above average |

---

## TECHNICAL SKILLS

| | |
|---|---|
| **Languages** | Python, SQL, R, JavaScript (Node.js) |
| **ML** | Scikit-learn, XGBoost, LightGBM, RandomForest, SHAP, TensorFlow, PyTorch |
| **MLOps Patterns** | Training-serving parity audit, feature registry, fail-loud asserts, gradual canary deploy, pre-training schema validation, UTM-routed A/B, per-platform dispatch, retraining with quality gate |
| **MLOps Tooling** | MLflow, FastAPI, Pydantic, SQLAlchemy, Docker, Cloud Run, Cloud Scheduler, Git/GitHub, CI/CD |
| **Cloud / Infra** | GCP (Cloud Run, Cloud SQL, Cloud Storage, BigQuery, Cloud Logging) · AWS (S3, EC2, SageMaker) |
| **Databases** | PostgreSQL (Railway, Cloud SQL), MySQL, BigQuery, SQLite |
| **Visualization** | Power BI, Tableau, Plotly, Matplotlib, ggplot2 |
| **Big Data** | Apache Spark, Apache Airflow |
| **Integrations** | Meta Conversions API (facebook-business), Meta Ads API, Google Ads API, Google Sheets API + Apps Script, Guru API, Hotmart API |

---

## EDUCATION & CERTIFICATIONS

| Institution | Program |
|---|---|
| **Stanford / DeepLearning.AI** | Machine Learning Specialization — Andrew Ng |
| **DeepLearning.AI** | Machine Learning in Production — MLOps Specialization |
| **Google** | Machine Learning Engineer Professional Certificate |
| **University of Michigan** | Python for Everybody |
| **IBM / Coursera** | Databases and SQL for Data Science |
| **MLOps Community** | First Stack MLOps |
| **Data Mundo** | Data Science Certification |

---

## LANGUAGES

Portuguese — Native · English — Fluent · Spanish — Fluent

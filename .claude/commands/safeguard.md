# /safeguard — Verificação de Integridade do Projeto

Você é um auditor de MLOps. Seu objetivo é verificar sistematicamente os pontos de falha conhecidos deste projeto e identificar riscos antes que virem bugs em produção.

Conduza cada seção abaixo em ordem. Para cada item, emita um veredicto: ✓ OK / ⚠ Atenção / ✗ Falha. Ao final, produza um resumo com os itens críticos.

Referência de erros históricos: `V2/docs/Erros_cometidos.md` — leia antes de começar.

---

## BLOCO 1 — Encoding: treino vs produção

**Por que importa:** o maior bug do projeto (DT-12) era silencioso — features chegavam zeradas sem erro explícito. A divergência treino/produção ficou ativa por semanas.

### 1.1 — Features críticas chegando com valor esperado

Pegue 50 leads recentes do Railway que responderam a pesquisa e passe pelo pipeline de produção. Verifique:

```python
import sys; sys.path.insert(0, 'V2')
from src.production_pipeline import LeadScoringPipeline
p = LeadScoringPipeline()

# Para uma amostra de leads, verifique as features abaixo:
features_criticas = [
    'Medium_Linguagem_programacao',    # nunca deve ser 100% zero
    'Qual_a_sua_idade_25_34_anos',     # ou equivalente ordinal
    'Atualmente_qual_a_sua_faixa_salarial_mais_de_r5001_reais_ao_mes',
    'utm_source_facebook_ads',         # utm normalizado para lowercase
]
# Calcule: % de leads onde cada feature = 0
# Alerta se > 95% zero para qualquer feature crítica
```

Alerta vermelho: qualquer feature estruturalmente importante com 100% de zeros.

### 1.2 — Encoding ordinal: nomes de colunas batem entre yaml e DataFrame

Leia `V2/configs/active_models/devclub.yaml`, bloco `encoding_overrides.ordinal_variables`.
Verifique que cada chave existe como coluna no DataFrame após o pré-processamento.

```python
# Nome no yaml: "Qual a sua idade?"
# Nome no DataFrame após processing: pode ser "Qual_a_sua_idade?" ou diferente
# Rodar um lead de teste e inspecionar df.columns antes do encoding
```

Alerta: qualquer `KeyError` silencioso durante encoding → feature zera sem avisar.

### 1.3 — Medium encoding: binary_top3 vs OHE

Verifique qual estratégia está ativa em produção e se é a mesma que foi usada no treino do modelo ativo.

```bash
grep -n "medium_strategy\|binary_top3\|Medium_Linguagem" V2/src/production_pipeline.py V2/src/train_pipeline.py
```

Alerta: se treino usou `binary_top3` mas produção usa OHE (ou vice-versa), `Medium_Linguagem_programacao` vai chegar errada.

### 1.4 — UTM: normalização lowercase consistente

```bash
grep -n "\.lower()\|utm_source\|utm_campaign" V2/src/production_pipeline.py V2/src/train_pipeline.py
```

Confirme que tanto o treino quanto a produção aplicam `.lower()` antes de criar features de UTM. Uma fonte sem normalização gera variáveis duplicadas (`Facebook-Ads` ≠ `facebook-ads`).

---

## BLOCO 2 — CAPI: integridade do sinal enviado ao Meta

**Por que importa:** D9 ficou 2 meses sem enviar evento. Valor de conversão foi calculado errado em 3 formas diferentes. Esses erros treinaram o Meta com dados incorretos.

### 2.1 — Todos os decils estão enviando eventos

```sql
SELECT
    decil,
    COUNT(*) AS leads_totais,
    COUNT(CASE WHEN "capiStatus" = 'success' THEN 1 END) AS capi_success,
    COUNT(CASE WHEN "capiStatus" = 'blocked' OR "capiStatus" IS NULL THEN 1 END) AS capi_ausente,
    ROUND(COUNT(CASE WHEN "capiStatus" = 'success' THEN 1 END) * 100.0 / COUNT(*), 1) AS pct_success
FROM "Lead"
WHERE "createdAt" >= NOW() - INTERVAL '14 days'
  AND decil IS NOT NULL
GROUP BY decil
ORDER BY decil;
```

Alerta: qualquer decil com `pct_success < 80%` ou `capi_ausente > 10%`.

Alerta vermelho: qualquer decil com 0 eventos de sucesso (bug tipo D9=0%).

### 2.2 — Formato das chaves de decil (D01–D10 vs D1–D10)

```bash
grep -n "D0\|D1\|D9\|D10\|decil\|conversion_rates" V2/api/capi_integration.py V2/src/production_pipeline.py | head -40
```

Confirme que o formato das chaves no código (`D01`, `D02`...) bate exatamente com o formato no yaml (`D01`, `D02`...). Mismatch de formato faz o lookup retornar None → valor de conversão zero.

### 2.3 — Fórmula do valor de conversão

Leia `V2/api/capi_integration.py` e verifique como `value` é calculado:

- [ ] Usa ticket real (não ticket médio simples)
- [ ] Aplica fator de realização TMB se necessário
- [ ] Não usa tabela hardcoded de valores por decil
- [ ] Valor para D1–D6 é zero (conforme configurado)

```bash
grep -n "value\|ticket\|conversion_rate\|tmb\|guru" V2/api/capi_integration.py | head -30
```

### 2.4 — Leads duplicados não sendo reenviados

```sql
SELECT email, COUNT(*) AS envios
FROM "Lead"
WHERE "capiStatus" = 'success'
  AND "capiSentAt" >= NOW() - INTERVAL '7 days'
GROUP BY email
HAVING COUNT(*) > 1
ORDER BY envios DESC
LIMIT 10;
```

Alerta: qualquer email com mais de 1 envio no período indica falta de deduplicação.

---

## BLOCO 3 — Pipeline de dados: qualidade do dataset de treino

**Por que importa:** dois bugs silenciosos no dataset de treino produziram um modelo que aprendia padrões falsos. Ambos ficaram ativos desde o início do projeto.

### 3.1 — Janela de conversão simétrica

Leia `V2/src/train_pipeline.py` e verifique o filtro de data limite:

```bash
grep -n "date_limite\|data_limite\|cutoff\|conversion_window\|filter" V2/src/train_pipeline.py | head -20
```

Confirme que o código remove do dataset **todos** os leads após `date_limite` — não apenas os compradores. Se apenas os compradores são removidos, leads sem compra perto do fim ficam e criam viés ("leads recentes não compram").

### 3.2 — Filtro TMB aplicado antes do cruzamento com vendas

```bash
grep -n "tmb\|risk_filter\|inadim\|cruzamento\|merge.*venda\|venda.*merge" V2/src/train_pipeline.py | head -20
```

Confirme a ordem: `filtro_tmb()` → `merge_com_vendas()`. Se a ordem for invertida, compradores inadimplentes entram marcados como `comprou=1` e depois somem — o sinal positivo fica contaminado.

### 3.3 — Sem leads duplicados no dataset de treino

```python
# Após carregar o dataset de treino, verificar:
assert df.duplicated(subset=['email']).sum() == 0, "Duplicatas por email no dataset de treino"
```

### 3.4 — Distribuição de decis no test set não é absurda

No `model_metadata`, verifique `decil_analysis`. D10 com > 25% de todos os leads no test set é sinal de feedback loop acumulado no dataset de treino.

```bash
python3 -c "
import json
d = json.load(open('V2/files/$(ls V2/files/ | tail -1)/model_metadata_*.json'))
for k, v in d['decil_analysis'].items():
    print(f\"{k}: {v['pct_total_conversions']:.1f}% das conversões, lift={v['lift']:.2f}\")
"
```

Alerta: D10 com lift < 1.5 ou D10 com > 35% de todos os leads (feedback loop).

---

## BLOCO 4 — Infraestrutura e configuração

**Por que importa:** modelo sendo servido da pasta errada, MLflow registrando no experimento errado, credenciais ausentes em scripts diretos — todos esses erros são invisíveis até quebrarem.

### 4.1 — Caminho do modelo: treino salva onde o servidor busca

```bash
grep -n "MODEL_PATH\|model_path\|files/" V2/api/Dockerfile V2/api/deploy_capi.sh V2/configs/active_models/devclub.yaml
```

Confirme que o `MODEL_PATH` no Dockerfile corresponde ao path registrado em `devclub.yaml → active_model.model_path`.

### 4.2 — MLflow experiment ID não está hardcoded

```bash
grep -rn "experiment_id\s*=\s*['\"]?[0-9]" V2/src/ | grep -v ".pyc"
```

Alerta: qualquer ID numérico fixo no código. IDs de experimento mudam entre ambientes e entre clientes.

### 4.3 — Credenciais carregadas em todos os entry points

```bash
grep -rn "load_dotenv\|DATABASE_URL\|META_ACCESS_TOKEN" V2/api/app.py V2/src/train_pipeline.py V2/scripts/ | head -20
```

Confirme que todos os scripts que precisam de credenciais carregam o `.env` explicitamente no início — não apenas o app principal.

### 4.4 — Token Meta dentro da validade

```bash
# Verificar data de expiração do META_ACCESS_TOKEN
python3 -c "
import os; from dotenv import load_dotenv; load_dotenv('V2/.env')
token = os.getenv('META_ACCESS_TOKEN', '')
print('Token presente:', bool(token))
print('Primeiros 20 chars:', token[:20] if token else 'AUSENTE')
# Token Meta expira a cada 60 dias — verificar data de última rotação
"
```

O token expira a cada ~60 dias. Se não há registro da última rotação, confirmar manualmente no Meta Business Manager.

### 4.5 — FBP/FBC sendo capturados antes do submit

Confirme que a landing page envia os cookies FBP/FBC no `page_view` (antes do submit do formulário). Se só forem enviados após submit, leads que abandonam o formulário perdem a atribuição.

---

## BLOCO 5 — Deploy: segurança e reversibilidade

**Por que importa:** deploy de novo modelo com 100% de tráfego imediato destruiu o sinal por 10 dias. Rollback manual demorou dias.

### 5.1 — Estratégia de canário ativa

```bash
gcloud run services describe smart-ads-api --region us-central1 --format="value(spec.traffic)"
```

Confirme que novos deploys sempre iniciam com `--no-traffic` e sobem gradualmente (5% → 10% → 100%).

### 5.2 — Revisão de rollback identificada

```bash
gcloud run revisions list --service smart-ads-api --region us-central1 --limit 5
```

Identifique qual revisão é o "rollback seguro" atual e anote o nome. Em caso de emergência, o rollback deve poder ser executado em < 2 minutos:

```bash
# Rollback imediato:
# gcloud run services update-traffic smart-ads-api --to-revisions=<REVISAO_SEGURA>=100
```

### 5.3 — Proteção de branch main ativa

```bash
gh api repos/$(git remote get-url origin | sed 's/.*github.com\///' | sed 's/\.git//')/branches/main/protection 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('Proteção ativa:', d.get('required_pull_request_reviews') is not None)" || echo "Verificar manualmente no GitHub"
```

---

## BLOCO 6 — Fuso horário: UTC como convenção

**Por que importa:** o mesmo bug de timezone apareceu 3 vezes em componentes diferentes por falta de convenção explícita.

### 6.1 — Todas as queries usam UTC explícito

```bash
grep -rn "NOW()\|CURRENT_TIMESTAMP\|datetime.now()\|pd.Timestamp" V2/src/ V2/api/ | grep -v ".pyc" | grep -v "utc\|UTC\|timezone" | head -20
```

Alerta: qualquer `datetime.now()` sem `timezone=utc` ou `NOW()` sem conversão explícita em código que compara com dados do Railway (que armazena em UTC).

### 6.2 — Conversão BRT → UTC documentada em queries manuais

Convenção: `00:00 BRT = 03:00 UTC`. Em toda query manual que usa janelas de data, confirmar que os limites estão em UTC.

---

## BLOCO 7 — Monitoramento: alertas automáticos existem?

**Por que importa:** D9 ficou 2 meses sem enviar evento, feedback loop ficou 3 meses ativo, features zeradas ficaram semanas — nenhum desses foi detectado automaticamente.

### 7.1 — Alertas de CAPI configurados

Verifique se existe algum mecanismo que alerta quando:
- [ ] `capi_blocked` ou `null` > X% em qualquer decil
- [ ] Volume de leads com score cai > 50% vs dia anterior
- [ ] D10% sai do intervalo [15%, 50%]

```bash
grep -rn "alert\|slack\|notify\|threshold\|monitor" V2/src/monitoring/ | grep -v ".pyc" | head -20
```

### 7.2 — Score médio e D10% sendo logados por lançamento

```sql
SELECT
    DATE_TRUNC('week', "createdAt") AS semana,
    COUNT(*) AS leads,
    ROUND(AVG("leadScore")::numeric, 4) AS score_medio,
    ROUND(AVG(CASE WHEN decil = 10 THEN 1.0 ELSE 0 END) * 100, 1) AS d10_pct
FROM "Lead"
WHERE "createdAt" >= NOW() - INTERVAL '60 days'
  AND "leadScore" IS NOT NULL
GROUP BY 1
ORDER BY 1;
```

Se D10% em qualquer semana < 15% ou > 50%, investigar imediatamente.

---

## BLOCO 8 — Grupo controle e feedback loop

**Por que importa:** sem grupo controle, o modelo treinou em leads que ele mesmo selecionou por 3 meses — feedback loop que levou D10% a 41% do total.

### 8.1 — Grupo controle ativo nas campanhas

Confirme com o gestor de tráfego: existe budget alocado fora do ML (campanhas sem otimização via CAPI ou com evento neutro)? Esse grupo deve representar 10–20% do volume.

### 8.2 — Dataset de retreino inclui leads do grupo controle com peso maior

```bash
grep -rn "importance_weight\|sample_weight\|controle\|control" V2/src/train_pipeline.py V2/src/retrain/ | grep -v ".pyc"
```

Se o retreino não aplica pesos maiores para leads do grupo controle, o viés de seleção continua se acumulando.

---

## BLOCO 9 — Relatório de validação: números cruzados

**Por que importa:** o relatório acumulou erros por meses porque não havia número externo de referência para validar.

### 9.1 — Total de leads no relatório bate com fonte primária

Após gerar qualquer relatório de validação, confirme:
- Total de leads no relatório ≈ total de leads no Meta Ads Manager para o mesmo período
- Diferença aceitável: < 5% (deduplicação, leads sem pesquisa respondida)
- Diferença > 10%: investigar antes de apresentar ao cliente

### 9.2 — Query sem limite implícito de 10.000 registros

```bash
grep -rn "LIMIT 10000\|\.head(10000)\|fetchmany(10000)" V2/src/ V2/scripts/ | grep -v ".pyc"
```

Alerta: qualquer query com limite hardcoded que pode truncar silenciosamente lançamentos grandes.

### 9.3 — Vendas não aprovadas excluídas

```bash
grep -rn "nao_aprovado\|não aprovado\|status.*venda\|aprovado\|estorno" V2/src/ | grep -v ".pyc" | head -10
```

Confirme que vendas com status "não aprovado", "estornado" ou "inadimplente" estão sendo filtradas antes de entrar no cálculo de conversão.

---

## BLOCO 10 — Autorização de processo: o deploy deveria acontecer?

**Por que importa:** em 20/04/2026, código do branch `main` foi deployado e serviu 100% do tráfego por horas. O safeguard encontrou dois bugs de código, eles foram corrigidos, o usuário autorizou o deploy — mas ninguém verificou se `main` estava autorizada para produção nem se os pré-requisitos do PLANO_EXECUCAO.md estavam satisfeitos. O `deploy_capi.sh` tem proteção de branch, mas é contornável manualmente sem trail. O safeguard avalia integridade de código; este bloco verifica se o deploy deveria acontecer.

### 10.1 — Branch atual está autorizada para produção

```bash
CURRENT_BRANCH=$(git -C V2 rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
echo "Branch atual: $CURRENT_BRANCH"
grep -A3 "AUTHORIZED_BRANCHES" V2/api/deploy_capi.sh
```

Alerta: se a branch **não está** em `AUTHORIZED_BRANCHES`, o deploy requer `--force-deploy` com autorização documentada. Indicar explicitamente no relatório — não é decisão silenciosa.

### 10.2 — Pré-requisitos T1 do PLANO_EXECUCAO.md satisfeitos antes de deployar `main`

```bash
grep "T1-[1-9]" V2/docs/PLANO_SAFEGUARD.md | grep "Pendente"
# Esperado: nenhum resultado (todos implementados)
```

Alerta: qualquer item T1-1 a T1-7 ainda "Pendente" é pré-requisito não satisfeito. Deploy de `main` em produção requer Tier 1 concluído.

### 10.3 — Parity check: `main` produz scores idênticos ao que está em produção?

```bash
python -m pytest V2/tests/parity_audit.py -v 2>&1 | tail -15
```

Alerta: qualquer falha significa que `main` produz scores diferentes da versão em produção. Deploy não autorizado até paridade comprovada.

### 10.4 — Split de tráfego atual está documentado e rollback identificado

```bash
gcloud run services describe smart-ads-api \
  --region us-central1 --project smart-ads-451319 \
  --format="value(spec.traffic)"
```

Registrar: qual revisão tem quanto de tráfego. Qual é o rollback seguro. O protocolo obrigatório é:
- Deploy sempre com `--no-traffic`
- 10% → aguardar ao menos 1h de tráfego real, sem aumento de erros
- 50% → requer confirmação explícita do usuário
- 100% → requer confirmação explícita do usuário + rollback identificado por nome

Alerta: qualquer salto além desse fluxo — especialmente 10% → 100% sem confirmação — é violação de protocolo.

---

## SÍNTESE FINAL

Produza uma tabela consolidada:

| Bloco | Item | Status | Risco se ignorado |
|---|---|---|---|
| Encoding | Features críticas sem zeros | | Sinal degradado silenciosamente |
| Encoding | Treino/produção mesma estratégia | | Score incorreto em produção |
| CAPI | Todos decils enviando | | Decil sem sinal = Meta cego |
| CAPI | Valor de conversão correto | | Meta otimiza para objetivo errado |
| Dataset | Janela de conversão simétrica | | Modelo aprende padrão falso |
| Dataset | Filtro TMB antes do merge | | Sinal positivo contaminado |
| Infra | Model path consistente | | Deploy sobe sem modelo |
| Infra | Token Meta válido | | CAPI para de enviar silenciosamente |
| Deploy | Canário configurado | | Bug de modelo exposto a 100% do tráfego |
| Deploy | Rollback identificado | | Recuperação lenta em emergência |
| Deploy | Branch autorizada para produção | | Código não-autorizado servindo tráfego real |
| Deploy | Pré-requisitos Tier 1 satisfeitos | | Bugs conhecidos chegam a produção |
| Deploy | Parity check main vs produção | | Scores divergentes sem alerta |
| Deploy | Gate de progressão de tráfego | | 100% de tráfego sem canário ou confirmação |
| Timezone | UTC em todas as queries | | Leads perdidos ou atribuídos ao dia errado |
| Monitoramento | Alertas de D10% e CAPI | | Bugs silenciosos por semanas |
| Controle | Grupo controle ativo | | Feedback loop no próximo retreino |
| Relatório | Total bate com fonte primária | | Número errado apresentado ao cliente |

**Itens com ✗ ou ⚠:** listar com ação corretiva e responsável.

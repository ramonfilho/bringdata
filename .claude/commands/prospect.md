# /prospect — Pesquisa de contato comercial com alta confiança

Use esta skill quando precisar pesquisar contatos em uma empresa-alvo antes de redigir outreach (via `/copy`). Output é um **dossiê estruturado com confidências explícitas e fontes URL para cada campo**.

**Princípio central:** prefiro 3 contatos de alta confiança a 10 de baixa. Erro de nome, cargo ou empresa descredita o contato inteiro e sinaliza automação.

---

## PRINCÍPIOS

1. **Multi-source confirmation** — toda informação factual precisa de ≥2 fontes independentes, ou é marcada como `single-source`.
2. **Tenure current** — a pessoa precisa estar **ativa na empresa no cargo citado**. Verificar LinkedIn "current position" + atividade pública nos últimos **6 meses** (post, release, menção em news).
3. **Canonical name spelling** — grafia vem de LinkedIn profile URL **ou** press release oficial onde a pessoa é sujeito. Nunca de fonte secundária transcrita.
4. **Role ≠ mandate** — título não implica decisão. Buscar evidência de escopo (projetos anunciados, contratações sob eles, áreas que responderam publicamente).
5. **Email tier explícito**:
   - `confirmed_public` — publicado em site oficial ou press release
   - `inferred_pattern` — padrão validado com ≥2 exemplos confirmados **na mesma empresa**
   - `guess` — padrão não validado → **não enviar** sem aprovação manual
6. **Red flags no topo** — M&A recente, reestruturação, rumor de saída, silêncio >12 meses. Não enterrar no meio do dossiê.

---

## SOURCE RANKING (tier matters)

| Tier | Fontes | Uso |
|---|---|---|
| **1 — Golden** | Site oficial da empresa, LinkedIn oficial da pessoa, press release oficial, investidor relations | Pode sustentar fato sozinha |
| **2 — Sólido** | Valor, Exame, InfoMoney, NeoFeed, Seu Dinheiro, Meio&Mensagem, LinkedIn posts públicos recentes, podcasts com transcript | Pode corroborar; sozinha precisa contexto |
| **3 — Cauteloso** | RocketReach, ZoomInfo, ContactOut, Apollo, Lusha, SignalHire | **Nunca sozinhas.** Só como corroboração. |

Regra: um fato precisa ter **pelo menos 1 fonte Tier 1 ou 2 Tier 2s**. RocketReach-only = não conta.

---

## CHECKLIST POR CONTATO (7 itens)

Para cada pessoa a reportar:

- [ ] **Nome canonicamente grafado** (fonte Tier 1)
- [ ] **Cargo atual confirmado** com data de entrada **ou** menção recente (<6 meses)
- [ ] **Empresa tenure current** — não é "ex-empresa"
- [ ] **Email**: `confirmed_public` **ou** `inferred_pattern` com ≥2 exemplos
- [ ] **Relevância ao pitch**: evidência de escopo/mandato/budget
- [ ] **Atividade recente** nos últimos 6 meses
- [ ] **Sem red flag não-resolvido** (M&A, rumor de saída, silêncio longo)

Cada item faltante **não** bloqueia — mas baixa a `confidence_overall`. Contatos com `confidence: low` não entram na lista de envio automaticamente; vão pra "verify_first".

---

## OUTPUT SCHEMA (YAML por contato)

```yaml
nome: "string"
nome_source: "url"                       # Tier 1 obrigatório
nome_canonical: true|false

cargo: "string"
cargo_since: "YYYY-MM"                   # ou "unknown"
cargo_source: "url"

empresa: "string"
empresa_tenure_current: true|false
empresa_evidence_date: "YYYY-MM"

email: "string"
email_type: "confirmed_public|inferred_pattern|guess"
email_source: "url ou padrão"
email_pattern_examples: ["exemplo1", "exemplo2"]   # só se inferred
email_bounce_risk: "low|medium|high"

relevance:
  score: 0.0-1.0
  reasoning: "1 linha"
  source: "url"

activity_last_6m: true|false
activity_evidence: "url ou descrição"

red_flags:
  - "descrição do risco"

confidence_overall: "high|medium|low"
recommended_action: "send|verify_first|skip"
```

---

## ANTI-PATTERNS (rejeitar antes de entregar)

- ❌ Email exclusivamente de RocketReach/ZoomInfo sem corroboração
- ❌ Cargo sem menção pública nos últimos 12 meses
- ❌ Nome só em fonte terceirizada (não LinkedIn nem empresa)
- ❌ Email pattern inferido de **1 único** exemplo
- ❌ Pessoa sem atividade pública nos últimos 12 meses → provavelmente saiu
- ❌ Dados que não consigo ligar a URL verificável
- ❌ Contato "top do organograma" sem nenhuma evidência de mandato sobre o tema

## DADOS QUE VÃO PARA COPY vs. DADOS QUE FICAM NO DOSSIÊ

Esta skill produz **dossiê interno** — estruturado e denso. Mas **nem tudo que descubro deve ir para a copy do outreach** (regra em `/copy` sobre staleness).

Para o dossiê: capturar **tudo** com fonte, inclusive números específicos (AUC, nº assessores, datas de aquisição). São úteis para contexto de decisão ("esse contato vale a pena?") e para futuras validações.

Para a copy de outreach: a pessoa que redige (`/copy`) deve **filtrar e só usar afirmações direcionais**. Não jogar os números específicos do dossiê na mensagem — eles envelhecem e, se errados, descredibilizam.

**Exemplo do que colocar no dossiê vs. copy:**

| Dossiê (capturar com fonte) | Copy (usar se relevante) |
|---|---|
| "AUC R$36bi em mai/2025" (NeoFeed) | "crescimento acelerado de custódia" |
| "Aquisição Únimo mai/2025, R$2bi" | "movimento recente de aquisições" |
| "800+ funcionários, 22 filiais" | "rede de assessores" / "operação em escala" |
| "meta R$100bi até 2027" (press release) | "meta de R$100bi até 2027" ← essa pode sim ir (meta pública e durável) |

**Heurística:** se o número envelhece rápido e a pessoa notar — vai pro dossiê. Se é meta pública de longo prazo ou claim direcional — pode ir pra copy.

---

## PROTOCOLO DE EXECUÇÃO

1. **Contexto da empresa primeiro**
   - Site oficial — home, quem somos, institucional, parcerias, imprensa
   - Modelo de negócio atual (não legado): AAI? Corretora? Vinculada a quem? Aquisição recente?
   - Tamanho: AUC, nº funcionários, receita se pública
   - Pipeline: contratações recentes, restruturações, press últimos 6 meses

2. **Emails institucionais**
   - Rodapé, `/contato`, `/fale-conosco`, `/imprensa`, `/trabalhe-conosco`, `/parcerias`
   - Política de privacidade, termos de uso (às vezes DPO)
   - Identificar **padrão de domínio** e **padrão nominal** (ex.: `nome.sobrenome@`)

3. **Decisores — LinkedIn com verificação**
   - Buscar: CMO, Head Marketing, Head Growth, Head Digital, Head Produto, Head Dados, CTO, Diretor Comercial, Head Canais, Sócios
   - Para cada candidato: **abrir o perfil** (via WebFetch) para confirmar current position + atividade
   - Cruzar com press releases recentes

4. **Fit ao pitch**
   - Para cada candidato, perguntar: "existe evidência pública de que esta pessoa decide (ou influencia fortemente) sobre [tema do pitch]?"
   - Coletar 1 URL que responda essa pergunta

5. **Sanity check pre-delivery**
   - [ ] Todo `recommended_action: send` tem ≥5 de 7 itens do checklist ✓
   - [ ] Todo email `inferred_pattern` tem ≥2 exemplos
   - [ ] Red flags visíveis no topo
   - [ ] Toda URL é clicável e verificável (não inventada)

6. **Entregar**:
   - Dossiê completo (YAML por contato)
   - Resumo executivo (3 linhas): quantos contatos, quantos `send` vs `verify_first` vs `skip`
   - **Recomendação única** de rota primária (1 pessoa + racional)

---

## QUANDO USAR

- Antes de qualquer outreach novo para empresa que nunca foi contatada
- Antes de adicionar contatos nominais a `bring_data_contatos` (via `/sheets`)
- Verificação periódica de contatos antigos (re-validar current position a cada 6 meses)

**Não usar para:**
- Lookup rápido de email em contato que já existe e foi verificado recentemente
- Casos em que `/copy` já vai usar canal institucional (`imprensa@`, `contato@`) sem nominal

---

## FLUXO COMPLETO POR EMPRESA

```
1. /prospect "Blue3"
     → dossiê YAML com N contatos + confidências
     → usuário aprova quais entram no send

2. Adicionar linhas aprovadas em `contatos.csv` via `/sheets`
     → Nome, Email, Tipo, Observações com cargo + fontes

3. /copy redige mensagem por contato (fica na coluna Copy)

4. Push + criar drafts via Gmail MCP

5. Usuário revisa drafts e envia

6. Registrar Status = Enviado + Data
```

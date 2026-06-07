# /linkedin — Redação de posts no LinkedIn a partir do portfólio Bring Data

Use esta skill para **compor ou revisar** posts no LinkedIn que usem o projeto Bring Data como portfólio técnico e pessoal de Ramon Filho.

**Pré-requisito inegociável:** toda fonte de números, claims e histórias está em `V2/docs/portfolio_linkedin.md`. Esta skill **não inventa**. Se faltar informação, parar e perguntar.

> Contexto operacional do projeto está em `/ctx`. Contexto comercial (decks, precificação) está em `/comercial`. Esta skill é sobre **conteúdo de portfólio**, não venda direta.

---

## OPERAÇÃO PADRÃO — FILA DE POSTS

O fluxo esperado é **3 posts por semana**, entregues sob demanda: o usuário dispara `/linkedin`, copia o texto, cola no LinkedIn. Sem API, sem scheduler.

**Estado persistente:** `~/Desktop/empregabilidade/linkedin/posts/queue.yaml`
**Arquivo de posts publicados:** `~/Desktop/empregabilidade/linkedin/posts/archive/<AAAA-MM-DD>-<slug>.md`

### Modos de invocação

| Comando | O que faz |
|---|---|
| `/linkedin` | Scan de git + puxa próximo item de `pending` + compõe draft |
| `/linkedin next` | Alias explícito de `/linkedin` |
| `/linkedin scan` | Só varre commits novos desde `meta.last_scanned_commit`, propõe adições à fila, atualiza hash — **não compõe post** |
| `/linkedin queue` | Mostra fila (`pending` + `on_hold` + `ideas`), oferece reordenar/mover/editar |
| `/linkedin force <id>` | Bypass de rotação — compõe o item `<id>` mesmo que quebre variedade de tom/tema |
| `/linkedin <tema> <ângulo>` | Modo ad-hoc — não consome da fila, não grava estado |
| `/linkedin adicionar "<descrição>"` | Adiciona entrada à `pending` (pede tema/tom/comprimento se não inferível) |

### Fluxo de `/linkedin` (default)

1. **Ler** `queue.yaml` e `V2/docs/portfolio_linkedin.md`.
2. **Scan de git:** `git log <meta.last_scanned_commit>..HEAD --oneline --no-merges`.
   - Classificar cada commit novo pelo prefixo (ver tabela abaixo) e propor entrada.
   - Mostrar em 1 bloco compacto: "N commits novos. Propostas de adição: [lista]. [a]ceitar todos / [e]ditar / [s]kip".
   - Atualizar `meta.last_scanned_commit` para HEAD ao final (mesmo em skip — a varredura já aconteceu).
3. **Seleção:** pegar topo de `pending` que **não** viole rotação:
   - Não repetir `tema` nos últimos 2 posts (`meta.recent_themes[:2]`).
   - Não repetir `tom` no post anterior (`meta.recent_tones[:1]`).
   - Se todo o topo violar, descer até achar; se nenhum encaixa, perguntar qual forçar.
4. **Confirmação** em 1 linha: `Próximo: <tema> · <ângulo resumido> · <tom> · <comprimento>. Seguir? [y] / [outro <id>] / [editar]`.
5. **Compor** o post usando "TEMPLATES POR TEMA" + "INVARIANTES" abaixo.
6. **Entregar** em bloco de código para revisão.
7. **Quando o usuário confirmar que postou** ("postei", "foi", "publicado"):
   - Mover entrada de `pending` para `posted:` com campos `publicado: <data>`, `link:` (vazio, o usuário preenche depois), `engajamento:` (vazio).
   - Atualizar `meta.last_post_date`, `meta.recent_tones`, `meta.recent_themes` (guardar últimos 5 de cada).
   - Arquivar texto em `archive/<AAAA-MM-DD>-<slug>.md` com front-matter (ver §FORMATO DE ENTREGA).
8. **Se o usuário pediu edição** antes da publicação, iterar no draft — só atualizar estado após "postei".

### Heurísticas do scan de git

| Prefixo de commit | Proposta de entrada |
|---|---|
| `safeguard(T1-X)` / `safeguard(T2-X)` | `design-decision` ou `milestone`, tom `confidente-tecnico` |
| `fix(DT-X)` / `fix(<bug crítico>)` | `war-story`, tom `honesto-com-bug` |
| `feat(core/...)`, `feat(ab-test)`, `feat(encoding)` | `technical-deep-dive`, tom `confidente-tecnico` |
| `feat(capi/...)` | `design-decision`, tom `confidente-tecnico` |
| `docs(fase*)`, `docs(analise)` | verificar se trouxe número novo — se sim, candidato a `business-value` |
| `refactor(rename)`, `style(...)`, `chore(...)`, `docs(skills)` | ignorar (ruído) |

Entradas propostas entram em `pending` com `prioridade: media` (topo mas abaixo dos que já estão com `alta`).

---

## PARÂMETROS A DEFINIR NO INÍCIO

Aplicam-se quando o usuário bypassa a fila (`/linkedin <tema>` ou `/linkedin adicionar`). No modo default, os parâmetros já vêm da entrada da fila.

Se não estiverem óbvios da mensagem do usuário, perguntar de forma curta (1 pergunta por vez ou tudo junto em uma lista):

| Parâmetro | Opções |
|---|---|
| **Tema** | `technical-deep-dive` · `war-story` · `business-value` · `design-decision` · `journey` · `meta-insight` · `career` · `milestone` |
| **Ângulo específico** | citar algo concreto do portfolio doc (ex.: §4.1 SSoT, §5.2 Medium zerada, §6.1 R$470k, §8 budismo → ML) |
| **Tom** | `confidente-tecnico` · `honesto-com-bug` · `mostra-resultado` · `contrarian` · `celebrando-marco` |
| **Comprimento** | `short` (<100 palavras, punchline) · `medium` (100–250, padrão LinkedIn) · `long` (250–500, deep dive) |
| **CTA** | `none` (só conteúdo) · `soft` (pergunta ou convite a comentário/DM) · `hard` (direcionamento específico, ex.: agenda uma call) |
| **Público** | `tecnico` (MLOps, ML engineers, CDS) · `negocio` (CMO, growth, marketing) · `misto` (padrão) |

**Disparos de invocação ad-hoc (bypass da fila):**
- `/linkedin war story medium zerada` → fixa tema + ângulo, pergunta tom/comprimento
- `/linkedin R$ 470k` → tema `business-value`, ângulo `§6.1`, pergunta tom/comprimento
- `/linkedin milestone T1-11 concluído` → tema `milestone`, ângulo `§7 Safeguards`

> Sem args (`/linkedin` puro), o modo é **fila** (§OPERAÇÃO PADRÃO). Para forçar o modo ad-hoc interativo, usar `/linkedin ad-hoc`.

---

## ANATOMIA DE UM POST NO LINKEDIN

```
[1] HOOK               → primeira linha(s) que aparece antes do "ver mais"
[2] CONTEXTO           → 1 frase que situa o leitor (opcional em posts curtos)
[3] MIOLO              → 1–3 parágrafos curtos com substância
[4] PONTO CENTRAL      → a ideia única que o post defende
[5] CTA ou FECHO       → opcional; convite, pergunta, observação silenciosa
[6] HASHTAGS           → 3–5, no final, separadas por espaço
```

**O hook é o tudo.** As primeiras 2 linhas decidem se alguém clica em "ver mais". Gastar tempo no hook > gastar tempo no miolo.

Blocos obrigatórios: 1, 3, 4, 6.
Blocos opcionais: 2 (dispensável em posts curtos), 5.

---

## TEMPLATES POR TEMA

### technical-deep-dive
```
Hook: pergunta técnica específica OU declaração contra-intuitiva
Contexto: o problema em 1 frase
Miolo: o problema → a decisão → o trade-off aceito → o resultado visível
Fecho: um detalhe que só quem já construiu saberia
```
**Exemplos de hooks fortes:**
- "Treino e produção fazem encoding diferente até você provar que fazem igual."
- "Se você envia `LeadQualified` ao Meta sem value calibrado, o algoritmo aprende com sinal plano."
- "153 hardcodes no código. 1 YAML no fim. O refactor levou 5 semanas e eu ganharia o dobro de tempo em troca de tê-lo feito no dia zero."

### war-story
```
Hook: a falha em uma linha sem preâmbulo
Contexto: como se descobriu (ou não se descobriu)
Miolo: impacto quantitativo → causa raiz técnica → correção estrutural
Lição: o que isso ensinou sobre MLOps / fail-loud / observability
```
**Exemplos de hooks fortes:**
- "Tive uma feature de 5% de peso zerada em produção por 3 semanas. Nenhum alerta disparou."
- "Meu modelo treinou em dados que ele mesmo produziu por 3 meses."
- "Bug de `'D9'` vs `'D09'`. 10% dos meus eventos de conversão sumiram por 2 meses."

### business-value
```
Hook: número direto, sem adjetivo
Contexto: o que o número é e o que não é
Miolo: metodologia (mencionar que é contrafactual/A-B, não extrapolação)
Detalhe: um dado qualitativo (CPL −34%, p<0,001) que mostra rigor
Fecho: o que o número NÃO prova
```
**Exemplos de hooks fortes:**
- "R$ 470.000 de margem incremental em 4 meses, auditável contra grupo de controle."
- "+92 centavos por R$1 investido. Não é extrapolação — é contrafactual direto."
- "5 de 7 testes A/B com p<0,05. Os outros 2 foram inconclusivos, não negativos."

### design-decision
```
Hook: a decisão em uma frase
Contexto: o problema que motivou
Miolo: alternativas consideradas → o trade-off aceito → o que não funcionou
Detalhe: código ou config concreto que torna a decisão visível
```
**Exemplos de hooks fortes:**
- "Escolhi event names CAPI distintos para cada variante do A/B. ROAS virou leitura direta no Ads Manager."
- "`utm_source_allowlist` em 1 linha de config. O Meta parou de aprender com leads que nunca gerou."

### journey
```
Hook: o ponto de virada em uma linha pessoal
Miolo: marco inicial → obstáculo → mudança de abordagem → estado atual
Lição: uma coisa não-óbvia que só se aprende fazendo
```
**Exemplos de hooks fortes:**
- "Há 12 meses eu não sabia o que era RandomForest. Hoje meu modelo roda em produção com AUC 0.745."
- "Vendi uma escola de budismo e fui estudar machine learning. Não foi metáfora."

### meta-insight
```
Hook: afirmação que desafia crença do público
Miolo: a lógica por trás → por que a prática padrão falha → a alternativa
Referência: Kahneman (ilusão da validade), modelos lineares vs não-lineares
```
**Exemplos de hooks fortes:**
- "Lead scoring por regras está matematicamente errado."
- "Você está otimizando seu anúncio para o lead errado."
- "Esperar 21 dias por um evento de Purchase é literalmente escolher aprender 56× mais devagar."

### career
```
Hook: detalhe pessoal concreto e pouco comum
Miolo: o que acompanhou a decisão → o que foi mais difícil → o que deu certo
Conexão: com o projeto atual / cliente atual
```

### milestone
```
Hook: o marco em números
Miolo: o que foi entregue → o número que importa → quem ajudou (se aplicável)
Fecho: próximo marco
```
**Exemplos de hooks fortes:**
- "688 commits depois, o sistema rodou o primeiro mês com 100% ML."
- "Safeguard Tier 1 fechado — 11 itens, 11 bugs que não vão mais acontecer em silêncio."

---

## INVARIANTES

### Idioma — todo post em inglês

Todo post é redigido **em inglês**, sem exceção. Hooks, miolo, lista de correção estrutural, lição final, hashtags — tudo em inglês. O portfolio doc, queue.yaml e a conversa em sessão continuam em português; a tradução para inglês acontece no momento de compor o post.

**Por quê:** o público-alvo do LinkedIn de Ramon inclui prospects e recrutadores nos EUA. Posts em português reduzem alcance e sinalizam mercado regional. Inglês como default amplia audiência e mantém consistência com a estratégia de captação internacional.

**Como aplicar:** ao compor, traduzir o ângulo do queue (em PT) para o post em EN. Manter números, nomes próprios e termos técnicos consagrados (MLOps, AUC, A/B test) sem tradução. Evitar tradução literal de expressões idiomáticas — preferir equivalente natural em inglês americano.

Quando o usuário pedir variante em PT explicitamente (`/linkedin <args> --pt` ou pedido textual), entregar PT como variante adicional, nunca como padrão.

### Números só saem do portfolio doc ou /comercial

Se o post precisa de um número, ele **precisa estar em** `V2/docs/portfolio_linkedin.md` §10 ou em `/comercial`. Se não estiver, parar e perguntar a Ramon — nunca inventar. Se não for possível obter, **reformular o post para não precisar do número**.

### Tom permanente

- **Direto, sem preâmbulo.** Primeira palavra conta.
- **Primeira pessoa** — "eu construí", "errei", "descobri" é mais forte que voz passiva.
- **Não prometer futuro** — sempre "verificado em operação real".
- **Sem emoji** salvo pedido explícito do usuário.
- **Sem jargão de IA genérico** — revolucionar, transformar, game-changer, exponencial, disruptivo, IA de última geração.
- **Preferir um número concreto a três adjetivos.**
- **Admitir trade-off / ressalva** quando houver — aumenta credibilidade técnica.

### Direcional > específico quando o número pode envelhecer

- ✅ "~100k leads em produção"
- ❌ "107.342 leads em produção" (envelhece em dias)
- ✅ "12 meses de desenvolvimento"
- ❌ "exatos 378 dias desde o primeiro commit" (envelhece diariamente)

### Cliente

- **DevClub** pode ser citado (público nas propostas comerciais)
- **Cliente B** e prospects: nunca nominalmente. Usar "um segundo cliente chegando" se relevante
- Nunca revelar dados de leads individuais

### Proibido em qualquer post

- Número que não está em `portfolio_linkedin.md` §10 ou `/comercial`
- Nome de colegas, gestores, fornecedores, concorrentes sem autorização
- Valores de contratos, preços, MRR
- Screenshots sem ofuscar emails, tokens, URLs de produção
- Commits específicos sem auditar o que eles expõem
- Crítica nominal a empresas ou pessoas

---

## REGRAS DE FORMATAÇÃO (LINKEDIN)

- **Primeira linha é o hook** — nunca gastar com "Hoje eu quero falar sobre".
- **Parágrafos curtos** — máximo 3 frases por parágrafo. Usuário lê no celular.
- **Linha em branco entre parágrafos** — LinkedIn respeita quebras.
- **Nada de markdown** — asteriscos, underline, bold viram caracteres literais no LinkedIn.
- **Listas com `—` (travessão)**, não `•` nem `1.`
- **Hashtags:** 3–5 no final, separadas por espaço. Sem hashtags no meio do texto.
- **Link externo:** no primeiro comentário, não no post (LinkedIn penaliza links no post).
- **Negrito:** LinkedIn não renderiza. Se o usuário quiser ênfase, usar MAIÚSCULAS com moderação ou reestruturar a frase.

---

## FORMATO DE ENTREGA (obrigatório)

1. **Mostrar o post inline em bloco de código** para o usuário revisar antes de postar.
2. Se o usuário pedir múltiplas variantes, entregar em blocos separados e **identificados**:
   ```
   ## Variante A — tom confidente-técnico, curto

   [bloco de código com o post]

   ## Variante B — tom honesto-com-bug, médio

   [bloco de código com o post]
   ```
3. **Nunca postar por conta própria.** Usuário copia e cola manualmente no LinkedIn. O ritual manual é intencional.
4. **Após o usuário confirmar que postou** ("postei", "foi", "publicado", "mandado"):
   - Arquivar o texto em `~/Desktop/empregabilidade/linkedin/posts/archive/<AAAA-MM-DD>-<slug>.md` com front-matter:
     ```markdown
     ---
     id: w-medium-zerada
     tema: war-story
     angulo: medium_linguagem_programacao_zerada
     tom: honesto-com-bug
     comprimento: medium
     publicado: 2026-04-25
     link:
     ---
     ```
   - Atualizar `~/Desktop/empregabilidade/linkedin/posts/queue.yaml`:
     - Mover a entrada do array `pending` para `posted`, preservando o `id`.
     - `meta.last_post_date = <data>`; append em `meta.recent_tones` / `meta.recent_themes` (manter últimos 5 de cada, descartar mais antigos).
   - **No modo ad-hoc** (sem item da fila), não atualizar `queue.yaml` — só arquivar o `.md` em `archive/` com `id: adhoc-<slug>`.

---

## CHECKLIST ANTES DE ENTREGAR

- [ ] Parâmetros (tema / ângulo / tom / comprimento / CTA / público) confirmados.
- [ ] Post está em inglês — incluindo hashtags.
- [ ] Todo número do post está em `portfolio_linkedin.md` §10 ou `/comercial`.
- [ ] Primeira linha funciona como hook sem contexto adicional — lida sozinha, faz alguém querer ver mais.
- [ ] Nenhuma promessa de resultado futuro.
- [ ] Sem jargão de IA genérico ("revolucionar", "transformar", etc.).
- [ ] Sem menção a Cliente B ou prospects nominais.
- [ ] Sem nome de colegas/fornecedores/concorrentes sem autorização.
- [ ] Parágrafos curtos, linha em branco entre cada.
- [ ] Hashtags apenas no final, 3–5.
- [ ] Post entregue em bloco de código limpo, sem markdown decorativo dentro.
- [ ] Direcional em vez de específico onde o número pode envelhecer.
- [ ] Se tom for `honesto-com-bug`, a correção estrutural está explícita (não só o bug).
- [ ] Se tom for `mostra-resultado`, a metodologia está mencionada (não só o número).

# /copy — Redação de mensagens iniciais comerciais

Use esta skill para **compor ou revisar** mensagens de outreach comercial (email, LinkedIn, WhatsApp) da Bring Data.

Pré-requisito: contexto de produto e claims verificados estão em `/comercial`. Esta skill define **estrutura, ângulos e adaptações** — nunca invente números ou promessas fora do que estiver em `/comercial`.

> O "copy" final vai na coluna **I (`Copy`)** da planilha `bring_data_contatos` via `/sheets`.

---

## PARÂMETROS A DEFINIR NO MOMENTO DO ENVIO

Antes de escrever, confirmar com o usuário (pergunta curta, se não estiverem óbvios):

| Parâmetro | Opções |
|---|---|
| **Tipo de parceiro** | `financeiro-institucional` (BTG/XP/canais) · `assessoria-AAI` · `marketing/infoprod` · `e-commerce` · `outro` |
| **Sub-perfil** (se AAI) | `digital-nativo` · `expansão/varejo` · `private/alta-renda` |
| **Estágio** | `cold` (1º contato) · `warm` (redirecionado, referenciado, respondeu) · `follow-up` (sem resposta após N dias) |
| **Canal** | `email-institucional` · `email-pessoal` · `linkedin` · `whatsapp` · `formulário` |
| **Contexto específico** | Quem redirecionou, lançamento em vista, evento, conexão comum — qualquer detalhe a incorporar |

---

## ANATOMIA DA MENSAGEM

```
[1] SAUDAÇÃO                 → "Prezados," (formal) | "Boa tarde," (resposta/warm)
[2] GANCHO DE CONTEXTO       → só em warm/follow-up: quem redirecionou, referência, etc.
[3] INTRO DO REMETENTE       → nome + empresa + especialização (1 linha)
[4] OBJETIVO DO CONTATO      → opcional; usar só em cold institucional
[5] NÚCLEO DO PRODUTO        → parágrafo-padrão (ver "INVARIANTES")
[6] OFERTAS COMPLEMENTARES   → lista bulletada (cold longo) ou prosa condensada (warm curto)
[7] FECHO                    → soft CTA (cold) | ask direto por data/horário (warm)
[8] ASSINATURA               → Ramon Filho + contato
```

Blocos **obrigatórios**: 1, 3, 5, 7, 8.
Blocos **condicionais**: 2 (só warm), 4 (só cold institucional), 6 (opcional em warm curto).

---

## INVARIANTES (nunca alterar os números — sempre copiar literal)

### Bloco [3] — Intro do remetente
- **Cold financeiro:** "Meu nome é Ramon Filho, fundador da Bring Data, empresa especializada em machine learning aplicado a operações de marketing digital e gestão de clientes no mercado financeiro."
- **Cold marketing/infoprod:** "Meu nome é Ramon Filho, fundador da Bring Data, empresa especializada em machine learning aplicado a captação e gestão de clientes."
- **Warm (qualquer público):** mesma linha **sem o recorte de setor** — "...gestão de clientes."

### Bloco [5] — Núcleo do produto (parágrafo canônico)
> "Nosso produto principal é um sistema de lead scoring por machine learning que envia sinais de propensão à Meta, Google e TikTok via API em menos de 5 minutos após o lead chegar. O modelo aprende com o histórico real de cada operação — quem preencheu o formulário e quem efetivamente se tornou cliente — e ensina o algoritmo da plataforma a trazer mais perfis com esse padrão. Em operação verificada, o sistema gerou 92 centavos de margem incremental para cada R$1 investido em anúncios, com ROAS superior ao grupo de controle em 12 de 12 lançamentos e significância estatística em 5 testes A/B simultâneos."

Variação curta (warm ou LinkedIn): omitir a segunda frase; manter as duas pontas (o que é + resultado verificado).

### Claims permitidos
- **5 min** após o lead chegar · **API server-side** · **Meta, Google, TikTok**
- **92 centavos de margem incremental por R$1** investido
- **12/12 lançamentos** com ROAS > controle · **5 A/B** com significância estatística
- **+131%** de receita mediana por real investido (vs. controle simultâneo)
- **CPL 28–44% menor** que o controle

### Claims proibidos
- Prometer resultado futuro ("vamos gerar X").
- Citar preços em mensagens para público financeiro-institucional.
- Usar palavras-ingresso genéricas de IA ("revolucionar", "transformar", "exponencial").
- Qualquer número que não esteja em `/comercial`.

### Regra de scope — tenure confirmado, scope fuzzy

Se a pessoa tem **tenure Tier 1 confirmado** (realmente trabalha lá, realmente é o cargo) mas o **escopo específico não é confirmado** (ex.: sócio-fundador sem mandato claro sobre MKT/growth/dados), **ainda enviar** — usando **copy genérica** que não alega escopo específico.

**Não usar copy genérica para:**
- Tenure não confirmado (só Tier 3) → verify_first ou skip
- Nome não canonical → skip (risco de mandar pro destinatário errado)

**Template de copy genérica (scope-agnóstico):**

```
Subject: Lead scoring por ML — Bring Data — verificando a via correta na [Empresa]

[Nome], tudo bem?

Meu nome é Ramon Filho, fundador da Bring Data. Estou em contato com algumas lideranças da [Empresa] em paralelo para apresentar um produto que potencialmente se encaixa em áreas de marketing, growth, dados ou captação digital. Se a decisão sobre esse tipo de tema passa por você ou por outra área, agradeço o direcionamento.

Desenvolvemos um sistema de lead scoring por machine learning que envia sinais de propensão à Meta, Google e TikTok via API em menos de 5 minutos após o lead chegar. O modelo aprende com o histórico real da operação — quem preencheu o formulário e quem efetivamente abriu conta e virou cliente — e ensina o algoritmo da plataforma a trazer mais perfis com o padrão dos melhores clientes.

Em operação verificada: 92 centavos de margem incremental para cada R$1 investido em anúncios, ROAS superior ao grupo de controle em 12 de 12 lançamentos e significância estatística em 5 testes A/B simultâneos.

Gostaria de apresentar em uma conversa de 30 minutos — ou de saber se a via correta passa por outra pessoa.

Atenciosamente,
Ramon Filho
Fundador — Bring Data
+55 37 99961-0179
ramon@bring-data.com
```

### Regra de email compartilhado (mesmo destino, múltiplos decisores)

Quando vários contatos da mesma empresa compartilham o **mesmo email institucional** (ex.: Pequod onde todos passam por `contato@`), **não enviar em batch no mesmo dia** — vira spam. Em vez disso:
- 1 draft no dia com A/C da pessoa primária recomendada
- Demais contatos ficam como **follow-up explícito em Observações**, com gatilho temporal (D+7, D+14) e A/C diferente por rodada
- Nunca "cobrir" os demais com uma única mensagem mencionando-os — o propósito é ter pontos de entrada distintos em datas distintas, não consolidar

### Fatos sobre o destinatário — regra de staleness

Sobre o **destinatário** (empresa/pessoa), usar apenas afirmações **direcionais e duráveis**. Números específicos envelhecem e, se errados, sinalizam bot.

**✅ OK (direcional / meta pública / durável):**
- "meta de R$100bi até 2027"
- "movimento recente de aquisições"
- "crescimento acelerado"
- "campanha com [celebridade pública]"
- "rede de assessores" (sem número)
- "após a partnership com [X]"

**❌ Evitar (específico / volátil / verificável-e-passível-de-erro):**
- Número de assessores ("800+ profissionais", "300 assessores")
- AUC específico ("R$36bi sob custódia")
- Datas de aquisição ("Únimo, maio/2025")
- Nº de filiais ("22 filiais")
- Nº de clientes ("40 mil clientes ativos")
- Ticket médio / receita específica

**Por quê:** se o destinatário ler um número errado em 10% sobre a própria empresa dele, perde confiança no resto da mensagem. Prefiro texto mais genérico e verdadeiro a um específico e possivelmente stale.

**Teste rápido:** antes de incluir um número, pergunte — "essa informação pode estar desatualizada em 6 meses?" Se sim, trocar por versão direcional.

---

## ÂNGULOS (BLOCO [4]/[5] — como entrar na conversa)

Escolha **um** por mensagem, alinhado ao tipo de parceiro:

| Ângulo | Quando usar | Frase-gatilho |
|---|---|---|
| **Canal institucional** | Financeiro-institucional (BTG, XP, plataformas) | "...soluções relevantes tanto para os escritórios parceiros do [nome] quanto para as operações internas de captação da plataforma." |
| **Sinal fraco** | AAI digital-nativo (já anuncia bem) | "Vocês já fazem o que a maioria dos escritórios ainda não faz: captam investidores via tráfego pago com consistência. Exatamente por isso faz sentido conversar..." |
| **Plataforma aprende errado** | AAI expansão/varejo | "Quando um escritório anuncia nas plataformas, o algoritmo aprende com quem preenche o formulário — não com quem abre conta." |
| **R$200k ≠ R$5M** | AAI private/alta renda | "No segmento private, volume de leads não é o objetivo — perfil é. A plataforma trata um lead de R$200k e um de R$5M como equivalentes." |
| **Compradores, não leads** | Marketing/infoprod | "O algoritmo da plataforma aprende com quem clica e preenche — não com quem compra. Muda o sinal, muda o resultado." |

Cada ângulo tem uma cópia-de-base no repositório (linhas 2–13 da `bring_data_contatos`). Puxar via `/sheets` quando precisar do texto completo.

---

## OFERTAS COMPLEMENTARES (BLOCO [6])

Catálogo completo (8 itens):

1. **Predição de churn** — identificar clientes com risco de saída antes que saiam.
2. **Predição de LTV** — estimar o valor potencial de cada novo cliente.
3. **Score de reativação** — ranquear inativos por probabilidade de retorno.
4. **Audiência personalizada enriquecida** — lookalike a partir dos melhores clientes, não dos leads em geral.
5. **Integração com CRM** — priorizar follow-up automaticamente.
6. **Rastreamento e qualidade de dados** — auditar e estruturar a coleta para viabilizar modelos futuros.
7. **Análise de precificação** — modelos para otimizar ticket, oferta ou segmentação por capacidade de pagamento.
8. **Experimentos A/B estruturados** — desenho e análise com rigor estatístico.

### Formatos

**Cold longo (lista bulletada, 5–8 itens):**
```
Além da captação, oferecemos serviços de ciência de dados sob demanda:
— Predição de churn: identificar clientes com risco de saída antes que saiam
— Predição de LTV: estimar o valor potencial de cada novo cliente
— Score de reativação: ranquear inativos por probabilidade de retorno
— Audiência personalizada enriquecida: lookalike a partir dos melhores clientes
— Integração com CRM: priorizar follow-up automaticamente
```

**Warm curto (prosa condensada, 4–6 itens em 1 frase):**
```
Além da captação, o sistema abre espaço para análises sobre churn,
estimativa de LTV, score de reativação de inativos, audiências enriquecidas
com o perfil dos melhores clientes e integração com CRM.
```

Para **financeiro-institucional**: priorizar churn, LTV, segmentação de base, audiências.
Para **marketing/infoprod**: priorizar audiência enriquecida, A/B, rastreamento, LTV.

---

## FECHO (BLOCO [7])

| Estágio | Fecho |
|---|---|
| **Cold** | "Ficaria à disposição para apresentar os resultados verificados em operação real e discutir como essas soluções poderiam ser aplicadas [contexto do parceiro]. Estou disponível para uma conversa a qualquer momento conveniente." |
| **Warm (redirecionado)** | "O interesse é entender se há abertura para uma conversa com alguma das áreas envolvidas (marketing, tecnologia, martech ou dados). Caso haja, encaminhar por gentileza data e horário desejados." |
| **Follow-up** | "Retomo este contato para confirmar se a mensagem anterior chegou à pessoa certa. Se houver alguém mais adequado para tratar do tema, agradeço a indicação." |

---

## ASSINATURA PADRÃO

```
Atenciosamente,

Ramon Filho
Fundador — Bring Data
+55 37 99961-0179
ramon@bring-data.com
```

(Alguns envios antigos usam `ramonfceo@gmail.com` — padronizar em `ramon@bring-data.com` para novos contatos.)

---

## ADAPTAÇÕES POR CANAL

- **Email-institucional** (DL-mkt-branding, atendimento@): versão mais formal, bloco [4] presente, ofertas em lista.
- **Email-pessoal** (sócio/diretor identificado): pode abrir com ângulo direto (bloco [4] opcional), ofertas em prosa.
- **LinkedIn InMail**: limite ~300 palavras → cortar bloco [4] e [6], manter [3] curto, [5] em 2 frases.
- **WhatsApp**: ~120 palavras, ângulo + núcleo + CTA. Sem assinatura formal.
- **Formulário**: seguir template do email-institucional.

---

## FORMATO DE ENTREGA (obrigatório)

### Caminho principal — **coluna Copy do CSV** (contatos rastreados)

Se o destinatário **já tem uma linha** em `bring_data_contatos` (CSV `V2/comercial/contatos.csv`), a copy final **vai direto na coluna `Copy`** dessa linha, via edição do CSV + `--push`. A célula do Sheets preserva newlines nativamente — copiar de célula (duplo clique, Cmd+A, Cmd+C) entrega o texto íntegro para Gmail/WhatsApp.

**Fluxo:**
1. Montar a mensagem.
2. **Mostrar inline em bloco** para o usuário aprovar o conteúdo.
3. Após aprovação, editar o CSV: `df.loc[mask, "Copy"] = texto`.
4. `python V2/comercial/contatos_sync.py --push`.
5. Para enviar: usuário clica na célula Copy no Sheet → Cmd+A → Cmd+C → cola no cliente.

Se a linha tiver Copy anterior (histórico de contatos), **acrescentar** ao final com separador `\n\n---\n\n` em vez de sobrescrever.

### Caminho de fallback — `.drafts/<slug>.txt` (mensagens avulsas)

Usar **só quando o destinatário não está na planilha** (teste rápido, contato efêmero, rascunho antes de adicionar contato). Arquivo em `.drafts/<slug>.txt`, aberto via `cursor <path>`. O diretório `.drafts/` está no `.gitignore`.

### Regras de conteúdo (valem em qualquer caminho)

- **Parágrafos separados por exatamente uma linha em branco.** Nunca duas ou mais seguidas.
- **Sem indentação extra** no começo das linhas.
- **Sem decoração markdown** (`>`, `**`, bullets com `•` — use `-` literal se precisar).
- **Para email:** primeira linha = `Subject: ...`; depois uma linha em branco; depois o corpo.
- **Para WhatsApp / LinkedIn:** apenas o corpo. Sem `Subject:`.
- **Dentro de um parágrafo, nunca quebrar a linha manualmente.** Deixar o parágrafo como uma string única — o editor e o destino cuidam do wrap.

---

## PROTOCOLO DE ENVIO (após redigir)

1. **Entregar no formato acima** (bloco pronto para copiar) — nunca enviar direto ao destinatário.
2. Confirmar **Subject/assunto** (para email): padrão `Proposta de Parceria — Bring Data` para institucional; para outros, puxar do ângulo (ex.: "O sinal que você envia para a plataforma pode ser muito melhor — Bring Data").
3. Após o usuário confirmar que **enviou de fato**, registrar em `bring_data_contatos` via `/sheets`:
   - Coluna F (`Copy`) = mensagem completa com `Subject:` na primeira linha (para email) ou corpo puro (WhatsApp/LinkedIn). Se já houver histórico, **acrescentar** ao final em vez de sobrescrever.
   - Coluna G (`Status de envio`) = `Enviado` ou `Follow-up` conforme o estágio.
   - Coluna H (`Data de envio`) = data ISO (`YYYY-MM-DD`).
   - Coluna I (`Observações`) = próxima ação planejada ou contexto livre.
4. Se o contato é **dedup** de alguém já na planilha, **atualizar** a linha existente em vez de criar nova (ver protocolo em `/sheets`).

---

## CHECKLIST ANTES DE ENTREGAR UMA MENSAGEM

- [ ] Parâmetros (tipo/sub-perfil/estágio/canal) confirmados com o usuário.
- [ ] Apenas claims de `/comercial` aparecem — nenhum número inventado.
- [ ] Financeiro: sem preço, foco em AuC/carteira, não em leads.
- [ ] Ângulo alinhado ao sub-perfil (tabela acima).
- [ ] Extensão compatível com o canal (email-inst longo; LinkedIn/WhatsApp curto).
- [ ] Ausência de promessa futura ("vamos gerar", "garantimos").
- [ ] Assinatura padrão com email correto (`ramon@bring-data.com`).
- [ ] Subject/assunto definido.
- [ ] Mensagem entregue em bloco de código puro, sem markdown, com parágrafos separados por uma única linha em branco.
- [ ] **Após aprovação**, gravei na coluna `Copy` da linha correspondente (via CSV + `--push`) — ou, se o destinatário não tiver linha na planilha, em `.drafts/<slug>.txt` aberto no Cursor.
- [ ] Plano de registro em `/sheets` combinado com o usuário.

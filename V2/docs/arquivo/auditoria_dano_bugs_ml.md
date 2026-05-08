> **DEPRECADO em 2026-05-08.** Conteúdo migrado para [registro_erros_ml.md](../registro_erros_ml.md), re-tecnicado para audiência interna (Champion/Challenger, ordinal vs OHE, encoding_overrides, LQHQ vs LQ).
> Versão original (linguagem leve para cliente externo) preservada aqui para referência. PDF em `V2/propostas_e_apresentacoes/auditoria_dano_bugs_ml.pdf`.

---

# Auditoria de Dano — Bugs do Sistema de ML

> DevClub — período mar–mai/2026
> Metodologia: backtest contrafactual (re-scoring dos leads de cada período com e sem o bug, usando o modelo que estava ativo na janela).
>
> *Glossário rápido:* uma **feature** é uma das informações que o modelo usa para decidir o decil de cada lead — por exemplo, idade, origem do tráfego, faixa salarial. O modelo combina dezenas delas.
>
> Bugs apresentados em **ordem cronológica de início**.

---

## Erro 1 — Modelo aprendia em circuito fechado

**Severidade:** Baixa  
**Janela:** histórica (até abril/2026)

**O quê:** sem uma campanha de controle (sem ML) rodando em paralelo, o modelo era retreinado em dados já influenciados pelas decisões dele mesmo. Ficava difícil separar o efeito real do modelo do perfil dos leads que chegavam.

**Contexto:** a suspeita foi levantada em mar/2026 durante uma queda de performance e motivou a mudança abrupta para o evento LQ amplo (Erro 4). Em abril, testes com pesos por grupo mostraram que o impacto real era pequeno — variação de performance abaixo de 0,3%. A hipótese que motivou o Erro 4 nem havia sido confirmada.

**Insight central:** fragilidade reconhecida e já mitigada — campanha de controle agora roda em paralelo, e o ML mostra ganho consistente sobre ela (lift de 6,88× em D9+D10).

---

## Erro 2 — D9 invisível para a Meta

**Severidade:** Média  
**Janela:** ~mid-jan → 15/mar (~2 meses, com múltiplos fixes parciais ao longo do período)

**O quê:** durante cerca de 2 meses, o evento de "alta qualidade" enviado à Meta — o sinal principal usado pelo algoritmo para otimizar campanhas — estava saindo apenas para leads D10. Os leads D9 (também de alta qualidade) ficaram **invisíveis** nesse sinal.

**Contexto:** o sistema usava dois formatos diferentes em módulos distintos do código (`D9` em um lado, `D09` em outro). O acréscimo de zero (`D09` em vez de `D9`) tinha sido solicitado pelo gestor de tráfego para facilitar a ordenação manual dos leads quando ainda eram organizados em Google Sheets — mas a mudança foi feita só em parte do código, criando a divergência. A comparação só casava para D10 (que é igual nos dois formatos) e falhava em D9. Múltiplos fixes parciais foram necessários ao longo de fev-mar para alinhar todos os módulos — o último deles em 15/mar fechou a janela.

**Impacto (descritivo):** durante ~2 meses, a Meta recebeu o sinal de alta qualidade de **apenas metade** dos leads top — só ~10% do volume (apenas D10) em vez dos ~20% esperados (D9 + D10). O algoritmo otimizou para um perfil mais estreito do que o ideal, perdendo a oportunidade de aprender com leads D9. Não há medição financeira direta possível, mas o efeito existiu.

---

## Erro 3 — Modelo em produção há 3+ meses sem retreino

**Severidade:** Média  
**Janela:** contínua (treino 30/jan/2026 com dados até 24/set/2025)

**O quê:** o modelo em produção tem mais de 3 meses de uso e os dados em que ele aprendeu terminam em set/2025 — quase 7 meses atrás. O perfil de leads e o comportamento de conversão provavelmente mudaram desde então. O impacto exato não é mensurável sem um modelo novo em produção pra comparar.

**Contexto:** várias mudanças de código nos últimos meses tinham como objetivo substituir esse modelo por um mais novo. Cada tentativa trouxe efeitos colaterais documentados (Erros 6.1, 6.2, 7) que precisaram ser corrigidos antes de avançar.

**Insight central:** dívida técnica em aberto, não bug pontual. O próximo retreino + deploy controlado (com as salvaguardas já implementadas — ver Medidas Corretivas) fecha esse risco.

---

## Erro 4 — Evento LQ enviado com cobertura ampla e valor superestimado

**Severidade:** Média  
**Janela:** 10/mar → início abr (revertido pouco antes do rollback de 13/abr)

**O quê:** dois problemas no evento `LeadQualified` que o sistema envia ao Meta como sinal de otimização das campanhas:

1. **Cobertura:** o evento passou a ser disparado para todos os decis (D1–D10) com valor proporcional, em vez de só D9–D10 como antes.
2. **Valor:** o valor financeiro atribuído a cada conversão estava calibrado pelo **total a ser recebido no longo prazo, já descontada a inadimplência projetada** — não pelo valor à vista efetivamente recebido. Isso superestimava o retorno de cada conversão a curto prazo.

**Contexto:** a decisão foi tomada por se acreditar que enviar um evento "mais rico" (cobrindo todos os decis com valor proporcional) ajudaria a Meta a otimizar melhor as campanhas. Na prática, abriu o sinal para perfis mais amplos e inflou o retorno aparente.

**Resultado (descritivo, sem medição direta):** o algoritmo de otimização da Meta passou a buscar um perfil de lead mais amplo e a "remunerar" cada conversão com um valor inflado. A audiência das campanhas degradou progressivamente. O ROAS dos LFs do período ficou significativamente abaixo dos LFs limpos (LF44/45), mas o período coincide com o período de março em que a Meta declarou ter passado por instabilidade no sistema de anúncios.

**Insight central:** a criação do novo pixel pode ter ajudado a reverter esse erro mais rapidamente.

---

## Erro 5 — Feature de tráfego zerada (`Medium_Linguagem_programacao`)

**Severidade:** Baixa  
**Janela:** 26/mar → 13/abr (~18 dias)

**O quê:** uma feature de origem de tráfego (segmento "Linguagem de programação") deixou de chegar ao modelo por divergência de nome de coluna entre treino e produção. Em produção a feature ficava zerada.

**Contexto:** durante uma reorganização do código que processa as origens de tráfego, uma transformação de texto removeu acentos das categorias. O segmento "Linguagem de programação" virou "Linguagem de programacao" (sem cedilha) — mas o modelo, treinado com o nome anterior, não a reconhecia. A feature passou a chegar zerada. Foi corrigida em 14/abr.

**Backtest:**

| Métrica | Sem bug | Com bug | Δ |
|---|---|---|---|
| Leads em D9–D10 | 14.227 | 14.234 | +7 |
| Conversões observadas em D9–D10 | 144 | 144 | 0 |

**Dano estimado: ~R$ 0**

**Insight central:** a feature pesa ~5% no modelo globalmente, mas na janela analisada a audiência veio 78,9% de campanhas "aberto" e apenas 0,1% do segmento "Linguagem de programação". A feature já estava praticamente vazia para essa audiência — o bug existiu, mas não teve onde causar dano.

---

## Erro 6.1 — Idade e salário não chegaram ao modelo (após rollback do modelo)

**Severidade:** Alta  
**Janela:** 26/mar → 01/abr (~6 dias)

**O quê:** o modelo antigo voltou a rodar em 26/mar após um rollback, mas o código continuou na versão preparada para o modelo novo. Resultado: durante 6 dias, **idade** e **faixa salarial** não chegaram ao modelo — ele tomou todas as decisões como se esses dois campos fossem desconhecidos. Essas duas variáveis representam cerca de **8% do peso total** das decisões do modelo.

**Contexto:** em 15/mar foi colocado em produção um modelo novo, treinado em uma pipeline nova que esperava idade e salário em formato diferente do antigo. Em 25/mar o resultado ficou ruim e foi feito rollback do modelo para o antigo — mas só o modelo voltou, o código permaneceu na versão nova. O modelo antigo passou então a receber idade e salário em um formato que ele não reconhecia, com esses dois campos zerados nas decisões. Foi corrigido em 01/abr.

**Backtest — leads alterados por decil de origem:**

| Decil sem bug | Total | Alterados | % alterado |
|---|---|---|---|
| D01 | 498 | 65 | 13,1% |
| D02 | 491 | 153 | 31,2% |
| D03 | 345 | 163 | 47,2% |
| D04 | 375 | 171 | 45,6% |
| D05 | 562 | 219 | 39,0% |
| D06 | 911 | 327 | 35,9% |
| D07 | 1.003 | 361 | 36,0% |
| D08 | 1.138 | 336 | 29,5% |
| D09 | 1.362 | 320 | 23,5% |
| D10 | 3.891 | 260 | 6,7% |
| **Total** | **10.576** | **2.375** | **22,5%** |

**Dano direto (referência histórica suavizada):**

- Rebaixamentos (perda real): R$ 2.620
- Promoções espúrias (falsos positivos): R$ 1.832
- **Saldo líquido: R$ 788**
- Movimentação total de valor entre decis: R$ 4.451

**Insight central:** o saldo líquido modesto (~R$ 800) **não significa ausência de impacto**. O bug embaralhou a ordenação dos leads em vez de empurrá-la em uma direção — rebaixamentos e promoções se compensaram em valor médio. Mas o efeito real é maior:

1. **Poder discriminativo degradado** — 22,5% dos leads receberam decil errado, com taxa de erro acima de 35% nos decis médios (D3–D7).
2. **Eventos `LeadQualified` enviados ao Meta com decis contaminados** — leads de qualidade média foram para o Meta como D9–D10, e parte dos D9–D10 reais caiu para decis intermediários. O sinal de otimização da campanha chegou ruidoso.
3. **Otimização da campanha perdida** — durante a janela, o algoritmo da Meta treinou em sinal contaminado e perdeu capacidade de encontrar o perfil correto de lead. Esse efeito acumula no tempo e não é quantificado aqui.

---

## Erro 6.2 — Idade e salário não chegaram ao modelo (A/B reativado)

**Severidade:** Alta  
**Janela:** 29/abr → 05/mai (~7 dias)

**O quê:** quando o teste A/B foi reativado em 29/abr, uma peça de configuração ficou faltando para o modelo principal. Resultado: durante 7 dias, **idade** e **faixa salarial** dos leads não chegaram ao modelo — ele tomou todas as decisões como se esses dois campos fossem desconhecidos. Essas duas variáveis representam cerca de **8% do peso total** das decisões do modelo.

**Contexto:** o erro veio da reativação do teste A/B em 29/abr para comparar o modelo antigo (em produção) com um modelo novo. Os dois foram treinados com pipelines diferentes e esperavam **idade** e **salário** em formatos distintos. Ao religar o A/B, o código só aplicou o formato correto para o modelo novo — os leads que caíam no modelo antigo (~90% ou + do tráfego) chegaram sem essas duas variáveis. A correção equivalente já existia em outro trecho do código, mas não tinha sido replicada nesse caminho. Foi corrigida em 05/mai.

**Backtest — leads alterados por decil de origem:**

| Decil sem bug | Total | Alterados | % alterado |
|---|---|---|---|
| D01 | 1.066 | 93 | 8,7% |
| D02 | 718 | 209 | 29,1% |
| D03 | 467 | 223 | 47,8% |
| D04 | 596 | 271 | 45,5% |
| D05 | 946 | 433 | 45,8% |
| D06 | 1.652 | 698 | 42,3% |
| D07 | 1.983 | 835 | 42,1% |
| D08 | 2.034 | 674 | 33,1% |
| D09 | 2.184 | 541 | 24,8% |
| D10 | 5.779 | 394 | 6,8% |
| **Total** | **17.425** | **4.371** | **25,1%** |

**Dano direto (referência histórica suavizada):**

- Rebaixamentos (perda real): R$ 4.218
- Promoções espúrias (falsos positivos): R$ 4.318
- **Saldo líquido: ~R$ 0**
- Movimentação total de valor entre decis: R$ 8.536

**Insight central:** o saldo líquido próximo de zero **não significa ausência de impacto**. O bug embaralhou a ordenação em vez de empurrá-la em uma direção — rebaixamentos e promoções se compensaram em valor médio. Mas o efeito real é maior:

1. **Poder discriminativo degradado** — 25,1% dos leads receberam decil errado, com taxa de erro acima de 40% nos decis médios (D3–D7).
2. **Eventos `LeadQualified` enviados ao Meta com decis contaminados** — leads de qualidade média foram para o Meta como D9–D10, e parte dos D9–D10 reais caiu para decis intermediários. O sinal de otimização da campanha chegou ruidoso.
3. **Otimização da campanha perdida** — durante a janela, o algoritmo da Meta treinou em sinal contaminado e perdeu capacidade de encontrar o perfil correto de lead. Esse efeito acumula no tempo e não é quantificado aqui.

O dano total do bug é a soma do efeito direto (~R$ 0 medido) **mais** a degradação acumulada da otimização Meta.

---

## Erro 7 — Evento LQ enviado sem valor por 7 dias

**Severidade:** Média  
**Janela:** 29/abr → 06/mai (~7 dias)

**O quê:** durante 7 dias o evento `LeadQualified` saiu para a Meta sem o valor financeiro associado. As campanhas que estavam otimizando nesse evento continuaram gastando, mas sem o sinal econômico que o algoritmo da Meta precisa para aprender a buscar leads com maior retorno.

**Contexto:** o erro veio de uma evolução da arquitetura — o sistema estava sendo migrado de uma estrutura com valores escritos diretamente no código para uma versão configurável e generalizável, que vai facilitar a manutenção e suportar novos modelos do DevClub no futuro. Na reescrita da parte que carrega os valores que os leads de cada decil valem, ficou faltando a leitura do arquivo de configuração — os valores não chegaram ao evento. O `LeadQualified` continuou sendo enviado, mas com o campo de valor vazio.

**Gasto no período:** **R$ 8.433,19** na campanha *DEVLF | CAP | FRIO | FASE 04 | ADV | PIXEL NOVO | MACHINE LEARNING | LQ | PG2 | 2025-04-15* (id `120242248118610390`).

**Insight central:** o gasto direto no período é o que pode ser atribuído de forma defensável. O efeito indireto — a Meta tendo gastado 7 dias sem sinal de valor para refinar o perfil dos leads — não é mensurável diretamente, mas se soma aos demais erros que distorceram o sinal de otimização nesse mesmo período (Erros 6.2 e 9).

---

## Erro 8 — Lista de origens de tráfego chegou vazia em produção

**Severidade:** Baixa  
**Janela:** 30/abr → 02/mai (~2-3 dias em produção)

**O quê:** o sistema mantém uma lista oficial das categorias de origem de tráfego (tipos de campanha, lookalikes, criativos) que o modelo conhece — categorias com as quais ele foi treinado. Essa lista é gravada em arquivo durante o treino e é lida na produção. Por uma divergência de caminho entre onde o sistema **gravava** e onde **lia** o arquivo, a lista chegou **vazia** em produção. Quando um lead chegava com origem rara ou nova (tag de criativo nova, lookalike novo, variante de campanha), o sistema não a reconhecia e **zerava todas as colunas relacionadas a esse tipo de origem para esses leads**.

**Contexto:** o bug existia no código desde meados de março, mas não impactou produção imediatamente — até 30/abr o sistema rodava uma versão anterior do código (rollback). Quando a versão atual do código subiu a 100% do tráfego em 30/abr, o bug se manifestou. Foi detectado e corrigido em 02/mai.

**Insight central:** janela curta em produção (~2-3 dias). Natureza similar ao Erro 5 (feature de origem zerando), mas com features distintas afetadas. Sem medição direta de dano financeiro pela curta duração, mas se soma à degradação de sinal vivenciada no mesmo período (sobrepõe Erros 6.2, 7 e 9).

---

## Erro 9 — Campanha A/B otimizando em evento ainda não aprovado pela Meta

**Severidade:** Baixa  
**Janela:** 02/mai → 04/mai (~2-3 dias)

**O quê:** uma campanha A/B foi colocada em produção otimizando num evento HQLB que ainda não tinha sido aprovado pela Meta. Durante esses dias a campanha gastou dinheiro sem que o evento de otimização estivesse sendo reconhecido — a campanha rodou totalmente cega.

**Contexto:** erro inicial do gestor de tráfego ao subir a campanha antes da aprovação do evento, somado à ausência de monitoramento da minha parte que detectasse o evento não aprovado em tempo hábil.

**Gasto no período:** **R$ 1.444,89** na campanha *DEVLF | CAP | FRIO | FASE 04 | ADV | PIXEL NOVO API | MACHINE LEARNING | LEAD | PG2 | 2025-04-30* (id `120243354440640390`).

**Insight central:** todo o gasto pode ser atribuído como desperdiçado — sem evento aprovado, a Meta não recebia nenhum sinal de otimização, então rodou só por entrega bruta. Diferente do Erro 7 (onde havia evento mas sem valor), aqui não havia evento algum.

---

## Medidas corretivas implementadas (abr–mai/2026)

Todas implementadas em produção, com data de deploy verificável. Atacam diretamente o bug-raiz "deploy de modelo com 100% de tráfego sem testes prévios".

### Deploy agora é controlado e testado

- **Progressão obrigatória de tráfego:** toda nova versão começa atendendo 0% dos leads, sobe para 10% (com 1h de monitoramento), depois 50% (24h de confirmação), e só vai a 100% após critérios cumpridos. Permite rollback instantâneo. _(21/abr)_
- **Teste automático antes de cada deploy:** o sistema roda 5 leads de teste reais e bloqueia o deploy se score, decil ou evento não saem corretos. _(21/abr)_
- **Atalho perigoso eliminado:** o caminho que permitia deploy direto a 100% foi removido do código. Agora sempre passa pelo protocolo de progressão. _(02/mai)_

### Detecção de features faltando

- **Verificação antes do envio ao modelo:** se uma feature crítica não chegar com o nome ou tipo certo, o sistema falha alto e bloqueia — em vez de seguir silenciosamente com a feature zerada. _(23/abr)_
- **Verificação após o encoding:** se uma feature importante aparecer zerada em mais de 5% dos leads, o sistema gera alerta e bloqueia. Salvaguarda que faltava nos Erros 5, 6.1, 6.2 e 8. _(21/abr)_
- **Painel de cobertura de features:** dashboard com últimas 24h de problemas — quais features tiveram issues e em quantos lotes. _(23/abr)_

### Paridade entre treino e produção

- **Auditoria automática treino↔produção:** antes de cada deploy, o sistema pega dados do treino, roda no pipeline de produção, compara coluna a coluna. Se divergir, bloqueia. _(21/abr)_
- **Verificação do modelo na inicialização:** quando o sistema sobe, confere que o modelo carregado é o declarado na configuração — detecta cenário de versão antiga rodando. _(29/abr)_
- **Reconciliação de identificador do modelo:** confirma que o modelo em produção é o mesmo da configuração. _(29/abr)_

### Monitoramento e alertas

- **Alerta para decis sem eventos:** se algum decil (D1–D10) não receber evento por 24h, alerta vermelho. Previne situação como o Erro 2 (D9 invisível por ~2 meses). _(20/abr)_
- **Eliminação de exceções silenciosas:** pontos onde erros eram engolidos sem log foram convertidos em falhas auditáveis. _(28/abr)_
- **Encoding falha alto em divergência de nome:** quando uma coluna não casa entre treino e produção, o sistema falha visivelmente em vez de pular o encoding silenciosamente. _(20/abr)_

### Filtros e correções pontuais

- **Whitelist de origens válidas para o evento Meta:** só envia evento ao Pixel para leads com origem rastreável (`facebook-ads`, `instagram`). _(30/abr)_
- **Path correto de categorias de origem:** corrigido bug em que a lista de origens válidas chegava vazia em produção (Erro 8). _(02/mai)_

### Itens em andamento

- Auditoria automática de paridade durante o treino (próximo retreino).
- Resolução final de algumas categorias residuais de origem (próximo retreino).

---

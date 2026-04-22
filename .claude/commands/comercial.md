# /comercial — Contexto Comercial: propostas em circulação

Use esta skill como ponto de partida para qualquer trabalho relacionado ao **funil comercial** da Bring Data: leitura, edição ou derivação de material de venda.

> **Escopo atual:** apenas propostas/apresentações. Tracking de contatos é operado na planilha `bring_data_contatos` (ver `/sheets`), mas o conteúdo dos contatos **não** pertence a esta skill.

---

## MATERIAL ATIVO (abril/2026)

Pasta: `V2/propostas_e_apresentacoes/`

| Arquivo | Público-alvo | Diferenciador |
|---|---|---|
| `bring_data_fin_ponta_v4.pptx` | **Financeiro / assessorias de investimento** (BTG, XP, escritórios) | Narrativa de AuC/AUM e wallet share. **Sem slide de preços.** Tem slide de custo interno (DS sênior + MLOps, R$60–90k/mês) como contraste. 12 slides. |
| `bring_data_mkt_v4.pptx` | **Marketing / infoprodutos** | Deck completo com **tabela de preços**. 12 slides. |
| `bring_data_gen_v5.pptx` | **Pitch genérico / flexível** | Mais enxuto (11 slides). Sem preços — fecha com slide "Como isso pode se encaixar" (cliente direto, revenue share, projeto piloto). Headline: +92% de retorno em infoproduto. |

Para extrair texto ou editar, usar `/pptx`.

---

## NÚCLEO DA PROPOSTA (idêntico entre as três versões)

### O problema que o sistema resolve
Plataformas de ads (Meta, TikTok, Google) aprendem com quem preenche formulário, não com quem compra/abre conta. O sinal servidor padrão é linear (score somado por resposta) e não captura combinações não-lineares entre 40–100 variáveis.

### O que o sistema faz
Modelo ML treinado nos dados reais do cliente → score de propensão por lead → envio do sinal calibrado à plataforma via server-side em **< 5 min** → plataforma otimiza para perfil de comprador, não de lead.

### Referência intelectual
Citação de Daniel Kahneman — "ilusão da validade" de modelos lineares.

---

## CASE DE RESULTADO (compartilhado nos três decks)

| Métrica | Valor |
|---|---|
| Margem incremental verificada | **R$ 470.000** em 4 meses |
| Investimento do período | R$ 508.000 |
| Retorno extra | **+92 centavos por R$1 investido** |
| Receita mediana por real investido vs. controle | **+131%** |
| CPL ML vs. controle | **28–44% menor** em todos os períodos |
| Superioridade ML vs. controle | **12/12 lançamentos**, 7 testes A/B com grupo simultâneo (5 com significância estatística) |

### Quebra mensal (valores arredondados)

| Período | Com ML | Sem ML | Ganho ML |
|---|---|---|---|
| dez/2025 (3 lançamentos) | R$ 104.000 | R$ 80.000 | +R$ 24.000 |
| jan/2026 | R$ 340.000 | R$ 195.000 | +R$ 145.000 |
| fev/2026 (2 lançamentos) | R$ 204.000 | R$ 38.000 | +R$ 166.000 |
| mar/2026 (100% ML) | R$ 140.000 | R$ 39.000 (est.) | +R$ 101.000 |

### Lançamentos do case (nomes internos, aparecem no deck mkt_v4)
`LF40`, `LF41`, `LF42` (dez/25) · `DEV19` (jan/26) · `LF43`, `LF44` (fev/26).
Cliente de origem: **DevClub** (infoproduto — educação em programação).

---

## PRECIFICAÇÃO (exclusiva do `bring_data_mkt_v4.pptx`)

### Planos mensais (para operação perpétua ou 6+ lançamentos/ano)

| Plano | Setup | Mensalidade | Inclui |
|---|---|---|---|
| **Essencial** | — | R$ 12.500/mês | Lead scoring + CAPI + monitoramento; atualização trimestral |
| **Avançado** (recomendado) | R$ 17.500 | R$ 17.500/mês | Essencial + atualização mensal + CRM + relatórios + audiência enriquecida |
| **Mais Popular** | R$ 17.500 | R$ 35.000/mês | Avançado + cientista dedicado + predição de churn + predição de LTV |
| **Personalizado** | R$ 15.000 | R$ 15.000/mês | Sob consulta |

### Revenue share (para lançamentos pontuais)

| Modalidade | Setup | % sobre receita nova |
|---|---|---|
| Com setup (recomendado) | R$ 25.000 | 20% |
| Sem setup (mais popular) | Isento | 25% |

Em reuniões com perfil financeiro (BTG, XP, escritórios), **não apresentar preços** — o deck `fin_ponta_v4` foi construído para essa lógica (parceria de canal, não SaaS).

---

## OFERTAS COMPLEMENTARES (presentes em todas as versões, "Expansão do sistema")

Predição de churn · Predição de LTV · Score de reativação · Audiência lookalike enriquecida (atualizada automaticamente) · Rastreamento e qualidade de dados · Integração com CRM · Análise de cohort · Análise de precificação · Experimentos A/B estruturados.

---

## IDENTIDADE DO REMETENTE

- **Fundador:** Ramon Filho — 7 anos de mercado, +120 ciclos de captação.
- **Stack de formação (citado nos decks):** Stanford (ML), University of Michigan (Python), DeepLearning.AI (ML in Production), Google (ML Engineer Certificate), MLOps Community, IBM (SQL/DB).
- **Citação-assinatura:** "In God we trust, all the others must bring data." — W. Edwards Deming.

---

## PRINCÍPIOS EDITORIAIS DOS DECKS

- **Não prometer resultado** — sempre "verificado em operação real", com referência ao case.
- **Financeiro recebe narrativa de AuC/patrimônio**, não de leads. Marketing recebe narrativa de ROAS.
- **Preços só aparecem no deck `mkt_v4`.** Nos outros, fechamento é uma CTA para conversa.
- Manter citação de Kahneman — é o ganho intelectual que separa o discurso de "mais um fornecedor de IA".
- Evitar emoji e jargão (exceto os que já estão nos decks).

---

## EDIÇÃO DOS DECKS

- Usar `/pptx` para qualquer alteração de conteúdo. **Não** recriar os arquivos do zero — o design foi feito externamente.
- Atualização de números do case: alterar nos três decks simultaneamente (idêntico em todos).
- Novo público-alvo (ex.: e-commerce, SaaS) → duplicar `gen_v5` como base e adaptar headline/linguagem, não criar um deck do zero.

---

## CHECKLIST ANTES DE QUALQUER ENVIO

- [ ] Confirmei a versão correta do deck para o público (financeiro = `fin_ponta`, marketing = `mkt`, genérico = `gen`).
- [ ] Os números do case batem entre deck e e-mail (R$ 470k / +92c / 12/12).
- [ ] Se financeiro: removi qualquer menção a preço na comunicação.
- [ ] Assinatura do remetente correta (Ramon Filho, contato).

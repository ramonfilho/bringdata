# Notas do Ramon, 01/09/2026: auditoria do painel LF65 + modelo

Fila viva, irmã do NOTAS_RAMON_3108.md. Não apagar item; marcar resolvido.

## A. Fechados em 01/09

- [x] A1. **Teto do AD0160 na base do CPL:** era 12,09 (teto agregado de todas as
  campanhas) contra CPL só do ML; na base certa é **13,09 e o criativo está
  VERDE** (folga R$ 1,78). Ações corrigidas e republicadas. ATENÇÃO: o
  "12,09/amarelo" foi citado pra Luiza no WhatsApp em 31/08; corrigir com ela
  é decisão do Ramon.
- [x] A2. "5 campanhas >R$ 1k sem venda (~R$ 11k)" viraram **3 e R$ 5,5k**
  (duas venderam no dia 31). Corrigido nas Ações.
- [x] A3. ad0154 com teto único (9,57): agora os DOIS tetos reais (ML 14,40
  contra CPL 15,73; Lead 6,92 contra 11,64). Corte mantido.
- [x] A4. TOTAL do lucro (R$ 25.783 contra soma da coluna R$ 572): **MANTIDO**
  por decisão do Ramon (realidade do lançamento: orgânico e não-base entram).
- [x] A5. Conclusão precipitada "a diferença é só calendário": removida.
- [x] A6. Travessão longo em texto novo: removido (3 ocorrências).
- [x] A7. **Medições do dia:** (i) a tabela de separação usa nota MISTA (a da
  variante que atendeu cada lead); (ii) régua única do Champion no LF65:
  top30 2,47x p=0,012, contra 1,53x ruído da mista; (iii) série LF64+LF65
  (90 vendas, colunas confiáveis): Champion 2,66x e Challenger 2,72x, ambos
  p<0,00001, diferença entre eles p=0,665 = **EMPATE**; (iv) lucro por decil
  LF65 frio: top30 do Champion **+R$ 21.506** contra **+R$ 22** do resto;
  fundo D1-D5 queima R$ 9.798 (ROAS 0,48); D10 fraco nos DOIS modelos.

## B. Decisões do Ramon em aberto

- [x] B1. EXECUTADO (01/09, PR #255): **"Parcela 1 de 12." na régua** por
  casamento EXATO de produto (`launch_products_exact` no yaml) — exato porque a
  variante "RENEGOCIAÇÃO" contém o mesmo texto e NÃO é venda nova. Boletex =
  boleto = 50% automático. Dupla contagem TRATADA no filtro: entrada Asaas de
  comprador que já tem a Parcela exata na janela é descartada (mesmo contrato).
  OBSERVAÇÃO pra decisão futura: existem "Parcela 1 de 9/11" avulsas pequenas
  (ex.: R$ 191) que NÃO entraram — só o "Parcela 1 de 12." decidido.
- [x] B2. DECIDIDO E EXECUTADO (01/09, PR #256, feito pelo Ramon com a OUTRA
  sessão): a régua do julgamento virou **só gasto ≥ R$ 300** (corte_leads 100→0).
  Medição do PR: dentro 1,47→1,49 e fora 0,83→0,82 de ROAS com R$ 54k a mais
  julgados (48,7k caem do lado FORA, como esperado). Confere com o backtest da
  seção F. O piso de 100 leads segue onde existe por OUTRO motivo (comparação
  %D9-D10 na planilha da agência). A seção do painel virou narrativa da
  transição: o que a régua nova recuperou, dupla a dupla, com prejuízo.
- [x] B3. DECIDIDO (01/09, Ramon): **folga do PAR**, sem mix com teto de campanha
  (o backtest reprovou o teto de campanha: 70,1% contra 73,9% do par). Na tabela
  "o que mudou" a folga sai em DUAS colunas na transição: régua nova (R$ 300) e
  régua antiga (100 leads + R$ 300). **A coluna antiga sai depois do LF67**, que
  já está rodando com a régua nova desde 01/09. Implementado em
  `scripts/comparativo_lancamentos.py` (`teto15_velho`).

- [~] B4. SEPARADO (01/09): farol é interpretação/frente própria, fora desta fila. Farol verde/amarelo/vermelho automático na planilha da agência (o
  teto por criativo já vai; falta a cor calculada). Ofertado em 01/09.
- [x] B5. EXECUTADO (01/09, PR #255): **gateway Asaas inteiro na régua**
  (`launch_sale_gateways` no yaml): toda venda asaas na janela de carrinho
  conta (produto NULL em 100% das linhas), como boleto (50%). Vale pra TODOS os
  LFs → os contratos da corrida foram re-gerados com a régua nova. Ressalva
  declarada: entrada Asaas de produto não-lançamento na janela também entra
  (não há como distinguir sem descrição — decisão consciente do Ramon).
- [ ] B6. Linha do LF66 na planilha PC FORMULÁRIOS (captação 25 a 30/08,
  carrinho abre 07/09).

## C. Execução aprovada, em fila

- [x] C1. FEITO (01/09): `scripts/gera_acoes.py` + `acoes_template.html` na
  pasta do LF = **molde com buracos**. O julgamento continua autoral no molde;
  os números saem do CONTRATO a cada emissão via tokens ({{cpl:ad0160:jul_24}},
  {{teto15:...}}, {{folga...}}, {{prejuizo...}}, {{camps1k_n/gasto}}). Token sem
  resolução ABORTA a emissão listando o que faltou. Plugado no
  painel_lancamento.sh (contrato → ações → comparativo → render). Engole m1
  (contagens do contrato) e m2 (teto agregado pesado, nunca média de médias);
  m3 (base com/sem DEV21) já está declarado no comparativo.
- [x] C1b. Regra aplicada onde há média: comparativo (média e top 5 sem DEV21,
  rotulados) e contagens que o incluem dizem isso no texto. Segue valendo como
  regra de conduta pra análises novas.
- [x] C2. FEITO (01/09, PR #254): CPL da unidade e do criativo agregado agora
  dividem por CADASTRO (a tabela de campanhas já era assim). O teto re-baseia
  na MESMA régua (teto × leads_ledger ÷ cadastros), então o gasto máximo da
  unidade não muda e o veredito fica estável por construção. Verificação
  pós-aplicação (mudança de cor) na re-geração desta data: seção F2.
- [x] C3. FEITO (01/09, PR #254): separação com régua ÚNICA do Champion quando
  a captação é >= 25/07 (LF64+); antes disso segue a mista, e o contrato grava
  `separacao_regua` dizendo qual foi. O painel rotula a régua na própria seção.
  Veredito de modelo pela SÉRIE segue como regra de leitura (memória gravada).
- [x] C4. FEITO (01/09): o item 3 do comparativo agora diz "faturamento BRUTO
  de gateway (régua de produto; por isso maior que o atribuído do painel)" nos
  dois ramos do veredito.
- [x] C5. RESOLVIDO (01/09, PR #257). O "gêmeo com 0" do ad0128 é o sufixo
  **"— cópia"** do gerenciador: a duplicata abria gaveta própria com histórico
  ZERO (no LF65, 111 leads lendo 0 de um histórico de 1.267 → teto desinformado
  6,43). Conserto = 4ª regra da `chave_canonica` (remove o sufixo "— cópia"),
  valendo pro painel E pra planilha da agência (mesma função). Também fundiu
  ad0156 (5.929+3.348 leads), ad0140 (+1.042), ad0141 (+260) e ad0043 (+640).
  SOBRA pra decisão do Ramon: nomes TRUNCADOS tipo "dev-ad0106-vid-captação-v-"
  (7 casos, 75-179 leads cada) e famílias com grafia dupla tipo
  "estãopagando"/"estão pagando" no ad0150 — fundir exige mapa de apelidos
  nome→nome (mecanismo novo), não dá pra deduzir com segurança só da grafia.
- [x] C6. DECIDIDO E FEITO (01/09): `lucro por decil` virou bloco do contrato
  (gerador) + seção do painel (render): Champion decil a decil + resumo
  top30/resto/fundo dos DOIS modelos. Custo = CPL por lead do ledger da dupla
  de cada lead. Só sai com captação >= 25/07 e venda ingerida (senão: None,
  sem seção).
- [x] C7. **BACKTEST FEITO (01/09)**, sem re-rodar nada (contratos congelados; a regra atual já estava medida e no delta ela é 'sem veredito' por definição): nos LFs fechados, 3 regras por unidade, sempre com informação da
  época (histórico cortado em cap_start): (a) atual, julga só com 100+ leads
  e R$ 300+; (b) teto do PAR liberado com R$ 300 de gasto; (c) teto da
  CAMPANHA enquanto o par não chega a 100 leads (o nível campanha já existe
  no cálculo de teto). Métrica: % do GASTO classificado certo (dentro e
  lucrou / fora e perdeu) + prejuízo que cada regra teria apontado a tempo.
  Reusa a infra da corrida das 3 réguas.

## D. ENTREGUE no relatório (01/09): "o dinheiro que o corte não julga"

Virou seção FIXA do painel (dentro de "Teto de CPL"), gerada do contrato a cada
emissão: total sem veredito, a fatia julgável antecipado (R$ 300+, <100 leads)
com tabela dos maiores estouros na régua 1,5, e a orientação nova com o
resultado do backtest (fora rende 0,75 por real; dentro, 2,66).

No LF65 de hoje (base nova, CPL por CADASTRO): R$ 11.845 sem veredito (24,8%
do gasto Meta), 13 duplas na fatia R$ 300+ (R$ 9.112), 12 estourando o teto
1,5 — as maiores entre 1,7x e 2,3x. A tabela viva mora no painel; números
antigos por respondente desta seção foram substituídos pela versão do contrato.


## E. Achado novo de 01/09 (no meio do backtest): VERBA FANTASMA nos contratos da corrida

- Leads com `utm_campaign` = só o ID criavam um SEGUNDO grupo da mesma campanha,
  e o join dava a verba (E as vendas) INTEIRAS pros dois. LF56-LF63: 63 duplas
  fantasmas, R$ 381.604 de gasto duplicado nas unidades. A cobertura DENUNCIOU
  (pct_gasto_casado impresso entre 149% e 197%) e ninguém travou. CORREÇÃO de
  01/09 à tarde: o bug NÃO tinha morrido no código; DEV21/LF64/LF65 só escapam
  porque os leads deles não têm essa UTM, e re-gerar LF56-LF63 reproduziu os
  fantasmas. Raiz consertada no PR #254 (fusão por cid).
- Estrago medido no PUBLICADO: tabela de campanhas OK; "% dentro do teto 1,5"
  OK (fantasmas nunca entram no julgável); média conc1 da série 56,8% -> 53,0%
  e conc3 87,0% -> 84,0% (corrigido em 01/09 com blindagem `_sem_fantasma` no
  comparativo). Corrida das 3 réguas: conclusões intactas (só usa julgáveis).
- [x] Blindagem no comparativo (scripts), regenerado.
- [x] C8. FEITO (01/09): guarda no gerador (`relatorio_lancamento.py`): casado
  acima de 102% = exit 4 com mensagem de verba DUPLICADA, contrato gravado só
  pra diagnóstico. E a raiz: fusão por (canal, cid, criativo) no PR #254, cada
  verba e cada venda contadas UMA vez por unidade real. Teste sintético trava
  o caso (utm = id puro não cria 2ª unidade).
- [x] B7. AUTORIZADO E FEITO (01/09): contratos LF56-LF63 re-gerados do banco.
  DESCOBERTA no caminho: o bug NÃO estava morto no código, a 1ª re-geração
  reproduziu os fantasmas (149-197% de casado), porque a causa é o DADO da época
  (utm_campaign gravada só com o ID) passando pelo agrupamento por STRING.
  Conserto na RAIZ no PR #254 (fusão por cid em `tabela_unidades`); re-geração
  final limpa. Backup dos contratos antigos em `_corrida_bak_20260901/`.

## F. Resultado FINAL do backtest (C7) — contratos limpos, régua 1,5, base cadastro

Medido em 01/09 sobre os 10 LFs fechados re-gerados (pós PR #254). A régua foi
o teto 1,5 DESDE a primeira rodada (= teto 2,0 do contrato × 4/3).

**A cascata do gasto Meta (responde "por que só R$ 45 mil?"):**

| fatia | duplas | gasto |
|---|---|---|
| total Meta por unidade | 431 | R$ 661.379 |
| JULGADO pela regra atual (100 leads + R$ 300) | 104 | R$ 597.240 (90,3%) |
| DELTA do backtest (R$ 300+, <100 leads) | 65 | R$ 44.950 (6,8%) |
| cauda <R$ 300 (fora de qualquer regra) | 262 | R$ 19.190 (2,9%) |

Os "centenas de milhares" JÁ são julgados hoje. O backtest só roda onde a regra
é cega por desenho: a fatia de R$ 300+ sem 100 leads.

**As duas regras antecipadas nessa fatia:**

| regra | dentro | fora | certo (do gasto) |
|---|---|---|---|
| **teto do PAR a R$ 300** | 10 duplas, R$ 4.818, ROAS **2,66**, +R$ 8.003 | 55 duplas, R$ 40.132, ROAS **0,75**, -R$ 10.076 | 73,9% |
| teto da CAMPANHA até 100 leads | 7 duplas, R$ 4.117, ROAS 1,43, +R$ 1.772 | 58 duplas, R$ 40.833, ROAS 0,91, -R$ 3.845 | 70,1% |

Veredito: **o teto do PAR a R$ 300 ganha com folga** (nos contratos limpos o
"empate técnico" da 1ª rodada sumiu: o teto de campanha deixou o dentro em
1,43 e apontou menos prejuízo a tempo). Recomendação mantida e reforçada:
PAR a R$ 300. Papel: VISIBILIDADE no relatório (seção "o dinheiro que o corte
não julga", já no painel), não gatilho automático. Ressalva de sempre: o balde
"dentro" é pequeno (R$ 4,8k).

## F2. Verificação pós-C2 (troca da base do CPL pra cadastro)

- LF64: 22 julgáveis antes e depois, dentro/acima idênticos, **0 flips** de
  veredito no teto 1,5 (o re-baseamento do teto compensa por construção).
- LF65: 13 julgáveis antes e depois, dentro 2 / acima 11 idênticos, **0 flips**
  no teto 1,5. Ações re-citadas na base nova (AD0160 10,11 vs 11,70 segue
  VERDE; ad0154 13,77 vs 12,60 e 8,08 vs 4,80 seguem corte; ad0170 idem).

## G. Rodada de ajustes do painel (01/09, tarde)

- [x] G1. Separação: linhas sem lift (orgânico, Meta sem nome) saíram da tabela.
- [x] G2. Separação da SÉRIE no corte top 30 (8-10), o que vai pra Meta:
  abr_28 2,58x contra jul_24 2,78x em 11.167 leads de Meta frio (LF64+LF65).
  É a medição que sustenta manter os dois modelos no ar; um LF sozinho não decide.
- [x] G3. Lucro por decil: "fundo" virou **Bottom 50** e a descrição passou a
  trazer a fórmula por extenso (lucro = faturamento − custo; ROAS = faturamento
  ÷ custo) com exemplo real preenchido do próprio contrato.
- [x] G4. "O dinheiro que o corte não julgava": a tabela dupla a dupla SAIU
  (o prejuízo somado da fatia é R$ 411 líquido, R$ 5.702 nas que perderam,
  não justifica tabela). Fica a frase + a linha do backtest.
- [x] G5. Confirmado: o "44,3% do gasto julgável dentro do teto 1,5" já sai da
  régua nova (o contrato traz `corte_leads=0`), não do corte antigo.

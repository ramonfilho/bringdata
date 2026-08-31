# Lucro ML vs Lead — a investigação refeita na estrutura nova (31/08/2026)

**Resposta em uma linha: NÃO se confirmou.** O lead encareceu, mas o modelo continua
lucrando mais que o Lead padrão: ganhou em **7 de 9** lançamentos fechados, e no
agregado fez **R$ +1,36 de lucro por cadastro** contra **R$ -0,93** do Lead.

## O que foi perguntado

A hipótese antiga era: "o lead encareceu, logo comprar lead pelo modelo (campanhas
com etiqueta Champion/Challenger) não dá mais lucro que a captação padrão (Lead)".
Refeita aqui sobre a estrutura nova de dados, a pedido do Ramon (28/08).

## Método (reproduzível: `python3 medir.py`)

- **Fonte:** os contratos congelados da corrida (`docs/relatorios/_corrida/<LF>/contrato.json`),
  os 9 lançamentos fechados LF56→DEV21 reconstruídos pela máquina canônica
  (`scripts/relatorio_lancamento.py`) com a régua de produção de 27/08.
  DEV21 foi reconstruído em 31/08 com `--as-of 2026-08-27` (mesma data-base dos outros;
  o original caiu por queda de rede). LF64 entra como linha extra, PROVISÓRIA
  (contrato de 26/08, carrinho ainda aberto na data).
- **Recorte:** só campanhas da META. **Quente fica fora da comparação** (regra de
  16/08: público quente tem economia própria) e é listado à parte. "Frio" aqui =
  tudo que não é quente, incluindo as poucas campanhas sem QUENTE/FRIO no nome.
- **Lados:** ML = campanhas com etiqueta de modelo (Champion abr_28 + Challenger
  jul_24). Lead = rótulo "Lead Padrão (Meta)".
- Dinheiro como a máquina calcula: boleto com haircut, gasto Meta com imposto ×1,13,
  régua de produto atual (família FullStack Pro, commit de 25/08 — já dentro dos
  contratos de 27/08).

## Resultado por lançamento (lucro POR CADASTRO, R$)

| LF | estado | CPL ML | CPL Lead | ROAS ML | ROAS Lead | lucro ML | lucro Lead | R$/cad ML | R$/cad Lead |
|---|---|---|---|---|---|---|---|---|---|
| LF56 | maduro | 9,75 | 6,44 | 4,13 | 1,62 | +6.861 | +23.882 | +30,49 | +3,98 |
| LF57 | maduro | 11,97 | 8,93 | 2,10 | 0,98 | +12.347 | -776 | +13,16 | -0,15 |
| LF58 | maduro | 9,98 | 7,47 | 1,59 | 0,31 | +12.305 | -33.613 | +5,88 | -5,14 |
| LF59 | maduro | 9,13 | 7,55 | 1,44 | 0,43 | +8.669 | -20.696 | +4,01 | -4,32 |
| LF60 | maduro | 6,34 | 5,08 | 1,07 | 0,98 | +4.344 | -125 | +0,47 | -0,13 |
| LF61 | imaturo | 6,91 | 4,83 | 1,31 | 0,92 | +16.107 | -362 | +2,15 | -0,38 |
| LF62 | imaturo | 7,00 | 4,37 | 1,10 | **3,11** | +5.170 | **+9.813** | +0,72 | **+9,23** |
| LF63 | imaturo | 7,14 | 3,96 | 0,09 | 0,18 | **-40.902** | -4.266 | -6,48 | -3,23 |
| DEV21 | imaturo | 6,91 | 4,62 | 1,36 | 0,89 | +27.501 | -813 | +2,51 | -0,53 |
| LF64* | provisório | 12,79 | 7,19 | 1,38 | 0,89 | +15.115 | -4.289 | +4,90 | -0,80 |

*LF64 fora do placar (carrinho aberto no contrato usado).

**Agregado dos 10 (frio):** ML gastou R$ 375k em 49.700 cadastros (CPL 7,55),
ROAS 1,18, lucro **+R$ 67,5k**. Lead gastou R$ 234k em 33.653 (CPL 6,96), ROAS 0,87,
lucro **-R$ 31,2k**. Quente (só DEV21, 2 campanhas): ROAS 2,02, +R$ 59,2k.

## Leitura

1. **A hipótese caiu.** O CPL subiu para os DOIS lados (o ML sempre paga cadastro
   mais caro: compra gente melhor). Mesmo assim o ML lucra mais por cadastro em
   7 de 9 fechados, e a distância é grande: conversão 0,59% contra 0,40%.
2. **As 2 exceções têm cara própria.** LF62: o Lead acertou um bolsão (ROAS 3,11,
   melhor linha do lançamento). LF63: os dois lados perderam; o ML perdeu MAIS
   (-R$ 40,9k) porque concentrou verba num lançamento que não vendeu.
3. **O que o ML ainda NÃO faz:** separar DENTRO do frio (descoberta do DEV21,
   lift 1,06x). O lucro maior vem de escolher público/lookalike melhor, não de
   ranquear pessoas dentro do mesmo público. As duas coisas agora são medidas
   automaticamente em todo lançamento (seção fixa do painel, PR da worktree
   `temperatura-relatorio`).

## Decisão do Ramon (31/08)

"Lucro vira seção fixa": implementado. Todo painel de lançamento passa a trazer
a tabela quente vs frio, o confronto ML vs Lead (só frio) e a separação
topo/base por público.

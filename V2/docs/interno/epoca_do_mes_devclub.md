# Época do mês: meio de pagamento e conversão

DevClub · 18 lançamentos · vendas dez/2025 a jun/2026

> **Meio de pagamento (sólido).** A fatia de vendas no boleto sobe dos lançamentos de início de mês (~66%) para os de fim de mês (~79%). O padrão se mantém mesmo comparando lançamentos dentro de um mesmo mês (março: correlação dia × %boleto = +0,77), então não é a tendência temporal. **Conversão (fraco).** A taxa aparenta subir rumo ao fim do mês (de 0,53% para 0,94%), mas com poucos lançamentos por janela e um lançamento puxando o resultado — não conclusivo. **Causa não testada** — apenas a relação foi medida.

## Boleto por posição do lançamento no mês

| Posição (dia de início das vendas) | Lançamentos | Pedidos | % boleto |
|---|---|---|---|
| Início (dias 1-10) | 6 | 1.283 | 66,0% |
| Meio (dias 11-20) | 5 | 1.357 | 73,4% |
| Fim (dias 21-31) | 4 | 682 | 79,2% |

Controle da tendência temporal, dentro de março (5 lançamentos): dia 2 = 55%, dia 9 = 51%, dia 16 = 86%, dia 23 = 83%, dia 30 = 79% (correlação +0,77).

## Conversão por posição do lançamento no mês

| Posição | Lançamentos | Leads | Taxa de conversão |
|---|---|---|---|
| Início (1-10) | 6 | 137.009 | 0,53% |
| Meio (11-20) | 4 | 98.098 | 0,76% |
| Fim (21-31) | 4 | 44.749 | 0,94% |

Sinal fraco: n pequeno por janela, e o lançamento de 30/03 (2,9%) puxa o balde do fim do mês.

## Lançamentos analisados

| Lançamento | Início das vendas | Posição | Observação |
|---|---|---|---|
| LF40 | 08/12 | início | outlier |
| LF41 | 15/12 | meio | outlier |
| LF42 | 22/12 | fim | - |
| DEV19 | 19/01 | meio | turma |
| LF43 | 02/02 | início | - |
| LF44 | 09/02 | início | - |
| LF45 | 02/03 | início | - |
| LF46 | 09/03 | início | - |
| LF47 | 16/03 | meio | - |
| LF48 | 23/03 | fim | - |
| LF49 | 30/03 | fim | - |
| LF50 | 01/04 | início | - |
| LF51 | 13/04 | meio | Padrão Ouro |
| LF52 | 17/04 | meio | fora da conversão (lacuna no UTMTracking na captação) |
| LF53 | 27/04 | fim | outlier |
| LF54 | 18/05 | meio | - |
| LF55 | 25/05 | fim | - |
| LF56 | 08/06 | início | - |

## Notas

- **Posição.** Pelo dia do mês em que as vendas do lançamento começam (1-10 início, 11-20 meio, 21-31 fim).
- **% boleto.** Pela origem da venda (tmb / asaas / boletex = boleto; guru / hotmart = cartão) — 100% das vendas classificáveis. Base: pedidos únicos na semana de vendas de cada lançamento (parcelas de boleto não contam como vendas separadas). No período inteiro são ~3.300 compradores únicos.
- **Conversão.** Conversões divididas por leads de captação. O denominador de leads vem dos emails únicos da tabela UTMTracking (Railway). LF52 fora da conversão: o UTMTracking teve uma lacuna de dados na semana de captação dele (07–12/04: 333 emails, contra ~14k na semana anterior), então o denominador ficou inválido. Receita e vendas do LF52 não são afetadas. Outliers (LF40 e LF41 = Black Friday; LF53 = upsell de segundo produto) fora das duas tabelas. LF51 ("Padrão Ouro") incluído.

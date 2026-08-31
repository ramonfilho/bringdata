# Notas do Ramon sobre o painel do LF65 (31/08/2026) — fila de trabalho

Registro fiel das 8 observações, com status. Não apagar item; marcar resolvido.

Status 31/08 (mesmo dia): 1, 2, 4, 5-texto e 8 IMPLEMENTADOS (commits na main);
3 e 6 MEDIDOS; pareceres de 5, 6 e 7 entregues em conversa. Achado novo no
caminho da nota 8: TODAS as 1.213 vendas Asaas (fev→hoje) têm produto NULL,
o gateway inteiro está fora da régua de produto — pendência pro Ramon decidir.

1. **[x] Tabela por público só quando houver quente.** A comparação quente vs frio
   isolada só serve quando existe público quente no LF. Lucro (ML vs Lead) e
   separação topo/base fazem sentido SEMPRE. (Concordância pedida: sim, concordo.)
   → render: tabela por público vira condicional (>= 2 públicos entre campanhas).

2. **[ ] Retirar a observação do DEV21** ("No DEV21 o modelo não separava dentro
   do frio (lift 1,06x)...") do texto fixo da seção de separação.
   **[ ] Investigar o que exatamente é "sem público no nome"** (no LF65: 1.261
   respondentes, lift 3,91x) — que campanhas/fontes caem ali.

3. **[ ] Investigar: duas campanhas de ML, mesma ordem de verba, sinais opostos.**
   Challenger R$ 8,7k → ROAS 1,56 (+R$ 4.851) vs Challenger R$ 7,6k → ROAS 0,58
   (-R$ 3.189). Se o relatório não explica, descobrir. Hipótese dele: criativo.

4. **[ ] Seção fixa de COMPARAÇÃO no fim do relatório:** este LF vs LF64; vs a
   média do LF56 pra cá; vs os X melhores lançamentos de ROAS parecido do LF56
   pra cá. Testar a hipótese de ÉPOCA DO MÊS (1ª, 2ª, 3ª, 4ª semana de captação).

5. **[ ] Trocar o título do parágrafo** "Como ler os destaques:" → "O que tirar
   dessa tabela:". **[ ] Parecer:** faz sentido ordenar a tabela campanha a
   campanha por LUCRO (hoje é por gasto)? Existe conclusão diferente da já
   delineada (público define patamar, criativo separa dentro do público)
   extraível desses números?

6. **[ ] Conferir se o LF65 é a PIOR performance de teto da série** (parece).
   Se for, formular hipóteses da queda. Atenção: 1º dia de carrinho, medido é
   imaturo; comparar pelo lado que já está fechado (compra de lead na captação).

7. **[ ] Parecer sobre a tabela "Criativo agregado por tipo":** dá pra extrair
   conclusão? Qual?

8. **[x] A venda Asaas (produto None, R$ 219) ENTRA no faturamento.**
   → operacionalizar: fazer essa venda contar na régua de produto do LF65.

Decisões anteriores do dia que continuam valendo: corrida NÃO re-roda; balde
"Quente sem modelo" só no próximo lançamento quente.

## Segunda rodada de notas (31/08, mesma conversa) — TODAS resolvidas

- **[x] Balde "sem público no nome" corrigido** (PR #252): canal decide antes do
  nome. Baldes agora: frio / quente / Google / orgânico ou sem rastro / Meta sem
  público no nome.
- **[x] Parágrafo de leitura do comparativo** reescrito em língua de gente, com
  linha de fonte (data de geração de cada contrato).
- **[x] Seção "Ações e recomendações"** no fim do painel (conclusao.html da pasta;
  título padronizado no render). LF65: comprar pelo teto 1,5; escalar ad0160;
  desligar ad0154/ad0170 e as 5 campanhas >R$ 1k sem venda.
- **[x] Coluna do comparativo virou "% gasto dentro do teto 1,5"** (era teto 2,0
  sem dizer; recalculada das unidades: teto1,5 = teto2 × 4/3).
- **[x] "(prov.)" honesto:** provisório = carrinho aberto OU ingestão de vendas
  atrás do fim do carrinho. LF64 foi RE-RODADO (contrato era de 26/08, carrinho
  ainda aberto) e agora é final: ROAS 1,62, lucro +R$ 55k, frio lift 2,98x.
- Fonte dos números do comparativo: contrato.json de cada LF (corrida 27/08 para
  LF56→DEV21; LF64 e LF65 re-gerados em 31/08).

## Terceira rodada de notas (31/08, print do painel) — status

1. **[x] Comparativo ganhou o bloco "O que mudou"** (% verba no criativo nº 1 e
   top 3, % leads D9-D10, CPL, teto 1,5 médio, folga) + coluna Teto 1,5 médio ao
   lado do CPL na 1ª tabela + **top 3 ROAS SEM o DEV21** (quente, outlier) +
   anterior detectado dinamicamente (nada de LF64 cravado).
2. **[x] Botão atualiza o ANTERIOR sozinho**: painel_lancamento.sh re-roda o LF
   anterior quando o carrinho dele fechou e o contrato ficou defasado
   (PAINEL_SEM_ANTERIOR corta a recursão). Botão também roda o comparativo.
3. **[x] Texto expandível**: caps de 74ch removidos do template (prose e h2sub
   acompanham a largura da coluna/tabela).
4. **[x] Narrativa da tabela de campanhas** agora abre respondendo "por que uma
   campanha de ML lucra e a outra dá prejuízo" (criativo dominante + preço vs teto).
5. **[x] Época do mês virou SÓ conclusão** (sem tabelas), sem DEV21, na voz dele.
6. **[x] Ações re-escritas no molde do plano do grupo** (70/15/15, semáforo 7d/3d
   contra teto 1,5, funil de teste em 3 etapas, AD0424 prioritário com status real).
7. **[x] Aderência do LF66 medida** (janela assumida 25-30/08, LF66 AINDA SEM
   linha na planilha PC FORMULÁRIOS → pendência do Ramon): ver
   `../lf66_resultado/ADERENCIA_PLANO.md`. Resumo: AD0160 70,3% da verba; ML
   68,6% (alvo 70); funil de teste abaixo do plano (R$ 5,7k de R$ 9k, 2 de 5-6
   criativos com verba cheia); Lead padrão 31% (alvo 15).
8. **[x] Respondida + implementada (PR #253):** a tabela de campanhas casa venda
   SÓ com cadastro da captação DESTE LF; quem vem de captação anterior cai em
   "Não está na base". Nova seção 9 no fundo racha essas vendas: cadastro dos
   90d anteriores vs sem cadastro nos 90d.

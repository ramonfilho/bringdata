# LF64 — relatório do lançamento (rodada 1, 24/08/2026)

Primeiro lançamento relatado pela MÁQUINA (não por scripts soltos). A metodologia
inteira mora em código versionado; esta pasta guarda só parâmetro e saída congelada.

## Reproduzir / atualizar (o mesmo par de comandos para qualquer lançamento)

```bash
cd V2
python3 scripts/relatorio_lancamento.py --lf LF64      # gera/atualiza contrato.json
python3 scripts/render_painel_lancamento.py docs/relatorios/lf64_resultado  # contrato → painel HTML
```

Quando as vendas caírem (coleta das 06:30, ou sob demanda com
`python3 -m src.validation.etl_sales --start 2026-08-24 --end 2026-08-24`),
re-rodar os DOIS comandos: as células de venda/faturamento/ROAS/lucro preenchem
sozinhas. O único delta legítimo entre os contratos das duas rodadas é a receita.

## Onde a metodologia mora

| Peça | Código |
|---|---|
| Tabela-fato da unidade + julgamentos | `src/validation/lancamento_unidades.py` |
| Casamento lead→venda, dinheiro, haircut | `src/validation/model_performance.py` |
| Teto por unidade (composição com histórico) | `src/monitoring/teto_por_chave.py` + `teto.py` |
| Gasto por anúncio | `src/data/ad_insights_reader.py` |
| Referência point-in-time + fator | `src/data/reference_reader.py` |
| Histórico de criativo com corte | `src/data/criativo_historico.py` |
| CLI e renderizador | `scripts/relatorio_lancamento.py`, `scripts/render_painel_lancamento.py` |

## Decisões desta rodada (todas do Ramon, 24/08)

- **Âncora do teto = produção atual** (referência 2026-08-24T06:32, window_end
  03/08): é o que a produção serve E não enxerga o LF64 (janela fecha 03/08,
  captação começou 07/08). Payload inteiro congelado dentro do `contrato.json`.
- **Histórico de criativo com corte na captação** (07/08): o DEV21 (vendas até
  16/08) fica FORA do teto do LF64.
- **Sai com receita zero**: estado `venda_aberta`, dinheiro `—` (None), preenche
  na re-rodada. Traço = "ainda não medido", nunca zero.
- **Meta com tolerância de 2%** (ROAS 1,97 conta como meta batida) + dois cortes
  novos no teto: lucro > R$ 1.000 e lucro > 0.
- **Devolvidos**: nenhum (debriefing ainda não existe). Cortes do julgamento:
  os literais do DEV21 (≥100 leads, ≥R$ 300).
- **NÃO comparável ao 1,73x do DEV21**: aquele número foi certificado com
  crédito 1,00; esta rodada usa a régua de produção (crédito 0,4102).

## Saídas

- `contrato.json` — tudo: tabelas, julgamento, referência congelada, coberturas.
- `painel_lf64.html` — o painel (artefato publicado:
  https://claude.ai/code/artifact/e356fb72-1de6-457d-89c4-e644f04c0d4d).

## Rodada 1, números de conferência

10.193 cadastros · R$ 89.371,02 investidos (Meta ×1,13 + Google) · CPL R$ 8,77 ·
143 unidades · 41 campanhas · 96,9% do gasto Meta casado por anúncio ·
0 ids de criativo sem nome · teto em PREVISÃO: 22 julgáveis, 1 dentro / 21 acima.

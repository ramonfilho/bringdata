# Perfil de audiência — DEV20 (em captação)

**Atualizado:** 2026-05-04
**Janela DEV20:** captação 2026-04-21 → 2026-05-04 (29.298 leads); vendas 11/05 → 17/05.

Comparação do perfil de leads do DEV20 (em curso) contra duas referências:
- **Top 5 ROAS histórico:** LF40, LF41, LF44, LF45, LF47 (39.771 leads pooled)
- **DEV19** (último DEV anterior, 15.153 leads): cap 16/12/2025 → 14/01/2026

Fonte: pesquisa de captação (Google Sheets para Top5 e DEV19; tabela `Lead` do Railway para DEV20).
Teste estatístico: chi-quadrado por característica categórica.

---

## DEV20 vs Top 5 ROAS

| Característica | Top 5 | DEV20 | Δ |
|---|---:|---:|---:|
| Gênero — Masculino | 81,7% | 76,1% | **−5,6** ⚠⚠ |
| Gênero — Feminino | 18,3% | 23,8% | **+5,6** ⚠⚠ |
| Cartão de crédito — Não | 58,2% | 62,4% | +4,2 ⚠ |
| Já estudou programação — Não | 63,2% | 67,7% | +4,5 ⚠ |
| **Tem computador — NÃO** | **9,5%** | **18,5%** | **+9,0** ⚠⚠ |
| Não trabalho/nem estudo | 9,3% | 11,6% | +2,3 ⚠ |
| Sou autônomo | 23,9% | 26,3% | +2,4 ⚠ |
| Não tenho renda | 25,1% | 26,3% | +1,1 |
| Idade 18–24 | 21,6% | 19,5% | −2,1 ⚠ |
| Idade 45–54 | 11,7% | 13,9% | +2,1 ⚠ |

Todos os campos comparados retornaram chi² com p < 0,001 (SHIFT estatisticamente significativo).

## DEV20 vs DEV19

| Característica | DEV19 | DEV20 | Δ |
|---|---:|---:|---:|
| Gênero — Masculino | 81,8% | 76,1% | **−5,7** ⚠⚠ |
| Gênero — Feminino | 18,1% | 23,8% | **+5,7** ⚠⚠ |
| Idade 18–24 | 22,7% | 19,5% | −3,3 ⚠ |
| Idade 25–34 | 32,4% | 29,9% | −2,5 ⚠ |
| Idade 45–54 | 10,4% | 13,9% | **+3,5** ⚠ |
| Já estudou programação — Sim | 28,3% | 32,2% | **+3,9** ⚠ |
| Faixa salarial > R$5k | 7,3% | 9,4% | +2,0 ⚠ |
| **Tem computador — NÃO** | **11,3%** | **18,5%** | **+7,2** ⚠⚠ |
| Cartão de crédito — Não | 62,8% | 62,4% | −0,5 (igual) |
| Não tenho renda | 27,4% | 26,3% | −1,1 (igual) |
| Sou CLT | 44,7% | 42,3% | −2,4 ⚠ |

---

## Leitura

### Mudanças DEV19 → DEV20 (novas)
- **Mais feminino:** +5,7 pp.
- **Mais maduro:** 45–54 anos +3,5 pp; 18–24 e 25–34 caem.
- **Mais sem computador:** +7,2 pp na resposta NÃO.
- **Levemente mais entendido em programação:** +3,9 pp Sim.
- **Renda levemente mais alta:** +2 pp na faixa > R$5k.

### Shifts vs Top5 que JÁ vinham do DEV19 (não são novidade do DEV20)
- Cartão de crédito: ~62% sem cartão em DEV19 e DEV20 — vs 58% no top5.
- Faixa salarial: distribuição de renda igual entre DEV19 e DEV20.
- Ocupação: distribuição parecida.

Ou seja, a base ficou mais "fria" (sem cartão, sem renda alta) já em DEV19 e o DEV20 apenas mantém esse patamar. As novidades exclusivas do DEV20 são gênero, idade, computador e nível de programação.

### Risco operacional
O segmento **sem computador** (18,5% no DEV20) é o sinal mais alarmante: curso de programação exige máquina, então leads dessa fatia tendem a converter pior na vida real, mesmo se classificados D8–D10 pelo modelo. Vale rodar o monitoramento de feature/decil mais cedo do que o normal pra DEV20 e checar se a distribuição do scoring está estável apesar do drift de input.

---

## Caveats metodológicos
1. **DEV19 e Tem computador:** 47,4% nulo na pesquisa do DEV19 (formulário antigo provavelmente não tinha a pergunta nesse formato). O delta DEV19→DEV20 nessa linha é menos confiável. O delta DEV20 vs Top5 (+9 pp) é robusto.
2. **Mudança de formulário** ao longo de 2026: alguns valores antigos aparecem com en-dash ("25 – 34") no Top5 e o atual usa hífen + sufixo ("25 - 34 anos"). Inflam levemente alguns deltas, sem inverter a direção dos shifts.
3. **Top 5 ROAS** inclui LF40 e LF41 (dez/2025), com volume baixo (~4k leads cada). Optamos por usar o ranking de ROAS como pedido, mesmo sabendo da instabilidade desses dois LFs específicos.

## Reprodutibilidade
Script ad-hoc em `/tmp/compare_perfil_3way.py` (não versionado; rodado via `python /tmp/compare_perfil_3way.py` com `cwd = V2/`). Constantes:
- `TOP5 = ['LF41', 'LF45', 'LF44', 'LF40', 'LF47']`
- `RECENT = 'DEV19'` (Sheets)
- `ACTIVE = 'DEV20'` (Lead Railway)

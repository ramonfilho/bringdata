# DEV21: análise de modelo, criativo e teto. Metodologia completa e reprodução

**Relatório técnico de 20/08/2026** · Artefato publicado: https://claude.ai/code/artifact/291806d2-c224-4715-adeb-3861f0628d86 (snapshot congelado em `painel_dev21_snapshot.html` nesta pasta) · 23 seções, 31 tabelas, 4 gráficos.

Este documento existe para que **qualquer número do relatório seja reproduzível por uma sessão futura**: fonte de dados, universo, script, fórmula e decisão metodológica de cada bloco. Os scripts estão em `scripts/` nesta pasta, copiados byte a byte da sessão que gerou os números.

---

## 1. Como reproduzir

```bash
cd /Users/ramonmoreira/Desktop/bring_data/V2      # os scripts assumem V2 como cwd
# .env do V2 carregado via load_dotenv (NUNCA `source .env`: mutila credenciais com espaço/pipe)
# LAUNCHES_SOURCE=table já é setado dentro de cada script
```

- Os scripts gravam/leem intermediários (`.pkl`/`.json`) num diretório de trabalho: a constante `S` no topo de cada um aponta para o scratchpad da sessão original. **Para reproduzir, troque `S` por um diretório seu** (é a única edição necessária).
- **Ordem de execução** (setas = dependência por arquivo intermediário):

```
painel_dev21.py ............. seções 1-6 (negócio por campanha) -> painel_dev21.pkl
modelo_dev21.py ............. base modelo -> modelo_dev21.pkl
resolve_google.py ........... nomes de criativo do Google -> google_ads_nomes.json
google_custo.py ............. custo por anúncio do Google -> google_custo.json
criativo_dev21.py ........... base criativo (precisa dos 2 json acima)
                              -> criativo_leads.pkl, criativo_unidades.pkl
criativo_parte2.py, complementos.py -> criativo_fixo.json, lucro_por_campanha.pkl
separacao.py ................ régua de separação (precisa modelo+criativo pkl) -> separacao.json
teto_v2.py .................. backtest do teto (precisa criativo_*.pkl) -> teto_v2.pkl, teto_v2_res.json
lacunas.py -> lacunas2.py ... dinheiro por decil, Lead vs ML, corrida v1, 2x2, mérito -> lacunas.json, corrida.pkl
corrida2.py ................. corrida com teto plano (precisa corrida.pkl) -> atualiza lacunas.json
historico_frio2.py .......... série fria LF56->DEV21 -> historico_frio2.json/.pkl, abr28_leads.pkl
corte7.py, corte8.py ........ cortes D7+/D8+ na série fria (precisam abr28_leads.pkl)
```

- **Montagem do HTML**: o painel NÃO é gerado do zero. A cadeia é
  `painel_dev21.bak.html` (base: cabeçalho, tiles, seções de negócio) → `add_secoes.py` (blocos modelo+criativo) → `add_teto.py` (bloco do teto) = `painel_dev21.pre_lacunas.html` → **`add_lacunas.py`** (as 6 seções de 20/08 + limitações + renomeia "Como ler"). Cada `add_*.py` insere por âncora de texto e **só grava se o JavaScript da página passar em `node --check`** (gate instalado depois de uma chave sobrando deixar o painel em branco). O template visual é o da skill `/painel-dados` (`V2/.claude/skills/painel-dados/template.html`); gráfico de barras usa `data:[{label, mean}]`, **não** `points:`.
- Republicação: ferramenta Artifact com o MESMO url para manter o link.

## 2. Fontes de dados

| Fonte | O que fornece | Acesso |
|---|---|---|
| Railway `Client` × `UTMTracking` | A base de NEGÓCIO: todos os cadastros (27.317) com UTM | `src.data.cadastro_records.open_railway_connection`; join por `clientEmail`; janela por `("trackedAt" - INTERVAL '3 hours')::date`; **last-touch por email** |
| `public.registros_ml` (Cloud SQL) | Respondentes + decil dos 2 modelos | `created_at` é **UTC sem tz declarada**: sempre `((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'America/Sao_Paulo')`; telefone é coluna `phone` |
| `analytics.sales` | Vendas dos 5 gateways | leitor `_open_real_readers()` de `src.validation.model_performance` |
| `analytics.ad_spend` | Gasto por campanha/dia | coluna de data é `spend_date` (não `date`) |
| `analytics.ad_insights` | Gasto POR ANÚNCIO da Meta (`ad_name`) | usado para verba por criativo; `insight_date` na janela de captação |
| Google Ads API | Nome e custo por anúncio do Google | `resolve_google.py`/`google_custo.py` (somente leitura); id numérico do `utm_content` → nome com prefixo `[G] ` |
| `analytics.captacoes` | Histórico por criativo (26 LFs, 314.752 leads) | usado em `teto_v2.py` para reconstruir a gaveta point-in-time |
| `analytics.launch_calendar` | Janelas canônicas de cada LF | `LAUNCHES_SOURCE=table` |
| `analytics.reference_rolling` | A referência congelada do teto | linha `client_id='devclub' AND window_end='2026-07-13'` (as_of 03/08): mapa de decis, `value_per_sale` 1.349,61, fator 1,2105, conv geral 0,8126% |
| Memória do projeto | Números NÃO recalculados nesta sessão (ver §7) | `projeto_score_criativo`, `reference_metricas_relatorio_transcricao`, `projeto_sendflow_entrou_no_grupo` |

## 3. Janela, universos e régua de negócio

**Janela**: captação 21/07 a 03/08/2026 (BRT), vendas 10 a 16/08/2026; casamento lead→venda aceita venda até `(V1-CAP0).days + 3` dias após a captura do lead.

**Régua do cliente** (idêntica ao debriefing): só produto principal (exclui produto com `opera`/`50k`/`mba` no nome); **3 compradores devolvidos** removidos por email (4 transações Guru, R$ 8.788,48; lista `REEMB` nos scripts); combos/vitalício/anual à parte; **boleto a 50%** no faturamento (`_load_boleto_haircut`); **gasto Meta ×1,13** de imposto (`_load_meta_gross_up`), Google sem.

| Universo | N | Onde nasce |
|---|---:|---|
| Cadastros (negócio) | 27.317 | Railway, last-touch |
| Respondentes com score | 24.158 | `registros_ml` na janela, dedup por email (last) |
| Com decil abr_28 | 24.047 | run `5d158f0a...` em qualquer uma das 2 colunas |
| Com decil jul_24 | 16.509 | run `b085b636...` (entrou 25/07) |
| Leads pagos custeados | 25.562 (93,6%) | custo = CPL da unidade criativo×campanha |
| Unidades do backtest do teto | 25 | cortes: ≥100 leads, ≥R$ 300 de gasto, ≥30 com decil |
| Série fria histórica | 60.712 (9 LFs) | `abr28_leads.pkl`, rótulo FRIO na campanha |
| Histórico por criativo (teto) | 314.752 · 2.366 compradores | `captacoes` com `cap_end < 21/07` |

**Casamento lead→venda**: nos scripts de painel/modelo/criativo, `match_leads_to_sales_unified` (`src/core/matching.py`, email → telefone completo → últimos 6, `mode='validation'`). Nos scripts de série histórica e teto, casamento direto por **email + últimos 8 dígitos do telefone** contra `analytics.sales` (mais simples, janela por LF do calendário).

**Classificação de campanha**: `campaign_id` extraído do lead (Google: `^(\d{6,})` do `utm_term`; Meta: `(\d{10,})\s*$` do `utm_campaign`) → cruza com `ad_spend` → categoria pelo NOME da campanha normalizado NFKD sem acento: `HQLB`/`JUL24_TOP10|30|50`/`Lead` × `QUENTE|FRIO`; Google é categoria própria. Lead sem cid pago = "Outro / Orgânico". Rótulo de temperatura da série histórica aceita também `ABERTO` como FRIO.

**Criativo**: `utm_content` normalizado (NFC + espaços colapsados); no Google o `utm_content` é id numérico → resolvido a nome via `google_ads_nomes.json`/`google_custo.json` com prefixo `[G] `. **Chave canônica** (pós PR #237): remove `^\[G\]\s*`, NFC, colapsa espaço, `casefold()`. Verba por criativo: Meta de `ad_insights` (×1,13), Google de `google_custo.json`.

## 4. Metodologia por bloco do painel

| Seções | Conteúdo | Script | Método |
|---|---|---|---|
| 1-6 | Negócio por campanha | `painel_dev21.py` | `_load_matched` + `_bucket_metrics` (a MESMA máquina do relatório canônico de LF); gasto por cid; comparação com o debriefing do cliente |
| 7-9 | Separação do modelo | `modelo_dev21.py` + `separacao.py` | ver §5: lift vs resto (Katz), lift vs fundo (regra de 3), Cochran-Armitage como juiz; Mantel-Haenszel para agregar campanhas |
| 10 | Dinheiro por balde de decil | `lacunas.py` (bloco A) | custo do lead = CPL da unidade em que caiu; 5 baldes = `BALDES_DE_DECIL` da produção; ROAS = fat/custo do balde |
| 11 | Separar ≠ lucro + série histórica fria | `lacunas2.py` (mérito) + `historico_frio2.py` | decil do abr_28 lido de QUALQUER coluna (`CASE WHEN champion... WHEN challenger...`); papel real: principal a partir de 22/06 (verba na Meta), NÃO o carimbo (§6-armadilha); MH por LF |
| 12-14 | Criativo: verba, por campanha, mexeu a conversão? | `criativo_dev21.py`, `criativo_parte2.py`, `complementos.py` | unidade = criativo×campanha; qui-quadrado de homogeneidade dentro da campanha (scipy) |
| 15 | Lead recebeu os melhores criativos | `lacunas.py` (bloco B) + `teto_v2.pkl` | "currículo" = `n_hist` do criativo; nota do baralho = lift histórico ponderado por gasto, só criativos com ≥500 leads de história (Lead 1,06 vs ML 0,64) |
| 16 | As duas variáveis juntas | `separacao.py` (por_criativo) | mesma régua de separação com criativo fixo (≥300 leads) |
| 17-19 | Backtest do teto | `teto_v2.py` | ver §5-teto; referência congelada 13/07; histórico fechado 20/07; lift Google 1,31 aplicado; Fisher + Mann-Whitney; ROAS ponderado por gasto |
| 20 | CPL barato prevê lucro? | `corrida2.py` + `lacunas2.py` (2x2) | 3 regras aninhadas (teto plano R$ 6,64 / teto modelo / teto final); veredito em CAPTURA DE LUCRO (90% vs 68%); Spearman da folga; quadrantes CPL×teto |
| 21 | Score composto (a aplicar) | NÃO recalculado: memória `projeto_score_criativo` (05/08) | 4 braços, 63.544 leads, 314 compradores; bootstrap agrupado por criativo |
| 22 | Alavancas: texto, ritmo, grupo, página | memória (`reference_metricas_relatorio_transcricao`, `projeto_sendflow_entrou_no_grupo`) | texto 1,95x (unidade = VÍDEO, 3 guardas), ritmo 1,94x, juntos 2,70x; grupo 3,2x e ~3x dentro do decil; página = teórica, sem dado |
| 23 | Como ler + 10 limitações | régua §3 + achados da sessão | platô D7-D8=D9-D10 checado contra `reference_rolling.by_decile` (degrau 1,5x na referência: é só do DEV21) |
| Ponto de atenção | frio: vigiar, não desligar | `historico_frio2.py`, `corte7.py`, `corte8.py` | IC do DEV21 0,69-1,83 (Katz); jul_24 empata no frio (1,26x vs 1,23x nos mesmos 4.995 leads); corte D8-10 mantido (pureza 1,47x vs 1,41x do D7-10) |

## 5. Fórmulas e testes (todas implementadas nos scripts, não em libs próprias)

- **Lift vs resto** = conv(D9-D10) ÷ conv(D1-D8), grupos disjuntos. IC95 de **Katz**: `exp(ln RR ± 1,96·√(1/a − 1/na + 1/b − 1/nb))`.
- **Lift vs fundo** = conv(D9-D10) ÷ conv(D1-D2). Fundo com 0 compradores → reporta o **PISO** `conv_topo ÷ (3/n_fundo)` (regra de três a 95%), nunca infinito.
- **Cochran-Armitage** (o juiz): tendência sobre os 10 decis em ordem; estatística `T = Σ t·(x − n·p̂)`, variância `p̂(1−p̂)·[Σn·t² − (Σn·t)²/N]`. Implementado em `separacao.py`; p bicaudal via normal.
- **Mantel-Haenszel** (agrega estratos segurando campanha/LF fixo): `RR = Σ(a·n0/N) ÷ Σ(b·n1/N)`, variância de **Greenland-Robins**. Em `modelo_dev21.py` e `historico_frio2.py`.
- **Teto** (produção, `src/monitoring/teto.py`): `conv_unidade = conv_modelo × (peso × lift_criativo + (1−peso))`, `peso = n/(n+2000)`; `teto = conv × value_per_sale × fator ÷ ROAS_alvo(2,0)`. No backtest, `conv_modelo` sai da mistura de decis da unidade via `CalculadoraDeTeto.por_mistura_de_decis` (des-fatorada e re-fatorada para não aplicar o fator 2x), Google ×1,31 de lift de plataforma.
- **Teto plano** (corte de "CPL barato" da corrida): a MESMA fórmula com a conversão geral da referência: `0,8126% × 1.349,61 × 1,2105 ÷ 2 = R$ 6,64`. Equivalência: CPL ≤ teto ⟺ custo por venda esperada ≤ R$ 817.
- **Mérito** (decomposição exata): `ROAS_camp/ROAS_lanç = (conv_camp/conv_lanç) × (CPL_lanç/CPL_camp)` = qualidade × preço.
- Fisher exato, Mann-Whitney (unilateral), qui-quadrado de homogeneidade e Spearman: `scipy.stats`.

## 6. Decisões e armadilhas (o que uma sessão futura PRECISA saber)

1. **ARMADILHA `champion_run_id`** (2 sessões erraram): a coluna só reflete o papel real a partir do fix de 25/07/2026. O abr_28 assumiu ~22/06 **pela verba na Meta**. O decil histórico dele vive na coluna de **challenger** (66.354 leads, 25/05 a 27/07). Ler sempre com `CASE WHEN` nas duas colunas. Ver memória `reference_champion_run_id_janela`.
2. **jan_30 foi DESCARTADO da análise**: score gravado ≠ campanha ativa; zero gasto em LEADQUALIFIED no DEV21.
3. **Chave canônica de criativo é obrigatória** (PR #237, e9ba4a2): NFC/NFD + carimbo `[G] ` criavam 3 chaves para 1 criativo; sem ela o maior criativo parecia estreante (331 vs 23.179 leads de história) e o backtest do teto sai errado (1,54x em vez de 1,73x).
4. **Custo por lead** no bloco de dinheiro = CPL da unidade criativo×campanha (não o CPL da campanha): segura o preço e deixa só a receita variar.
5. **Corte real do evento enviado à Meta é D8-D10** (D9-D10 é só régua de relatório). Medido em 20/08: manter D8-10 (pureza 1,47x vs 1,41x do D7-10; D7 sozinho = 1,22x a média).
6. **O platô D7-D8 ≈ D9-D10 é só do DEV21**: na referência congelada o degrau é 1,5x (0,934% vs 1,407%).
7. Nada do DEV21 entra no cálculo do próprio DEV21 no backtest do teto: referência congelada em 13/07, histórico de criativo fechado em 20/07. `reference_rolling` já é point-in-time: **não** varrer 27 lançamentos.
8. `pg8000.native` usa placeholders `:nome`; conexões analytics com `timeout` ≥ 300 para scans; tz-naive vs tz-aware: `pd.to_datetime(..., utc=True).dt.tz_localize(None)`.
9. Proibido em qualquer saída: o caractere em dash (regra permanente do Ramon); os construtores de HTML checam.
10. **Não projetar ganho de vendas por realocação de verba de criativo**: medição sim, projeção não (retirado 2x pelo Ramon).
11. **"Bateram a meta de retorno" conta o ROAS 1,97 como tendo batido** (decisão do Ramon, 20/08). O critério mecânico `ROAS >= 2,0` dá 9 de 14 unidades dentro do teto = **64%**, que é o que o painel técnico publica. O painel não técnico ("O que deu lucro no DEV21?") publica **71%** (10 de 14) porque o AD0160-AD08 no público quente, com ROAS 1,968, foi contado como tendo batido: a diferença para a meta é 1,6%, dentro da margem de erro de uma unidade com esse volume. **Os dois números estão certos, com critérios diferentes, e a diferença é uma unidade.** O recorte "sem o público quente" não muda (60% nos dois), porque a unidade em questão é do quente. Qualquer recontagem futura tem que escolher o critério explicitamente.
12. **O CPL do backtest é por CADASTRO, não por respondente** (24.704 cadastros contra 21.764 respondentes nas 25 unidades, taxa de resposta 88,1%). Isso significa que a régua certificada aqui precifica o cadastro que não respondeu a pesquisa como valendo **um respondente inteiro — crédito 1,00**. A produção nunca rodou assim: rodou crédito 0 (numerador só respondentes) até 20/08 e crédito 0,38 (Decisão 12) a partir de 21/08, o que deixa o teto publicado **7,4% mais apertado** do que o certificado neste documento. Refazendo o backtest com a régua de produção: razão de ROAS cai de 1,73x (p 0,012) para 1,50x (p 0,087), e o lucro preservado cai de 90% para 66%. Ver §9.

## 7. Números que vêm da memória do projeto (não recalculados aqui)

| Número no painel | Registro de origem | Scripts originais (sessões anteriores) |
|---|---|---|
| Score composto: AUC 0,640→0,677, lift D10 1,69x→2,42x, top10% 67→76 (92 c/ texto) | `projeto_score_criativo` (05/08, "OS QUATRO BRAÇOS") | `score_composto.py`, `composto_boot.py` |
| Texto 1,95x · ρ +0,40 · p 0,31% (65 vídeos, 4.126 compradores) | `reference_metricas_relatorio_transcricao` (05/08) | `teste_transcricao_dedup.py` (3 guardas obrigatórias) |
| Ritmo 1,94x · juntos 2,70x | `projeto_score_criativo` | `gancho_duracao.py` |
| Grupo WhatsApp 3,2x · ~3x dentro do decil · ~65% prevalência | `projeto_sendflow_entrou_no_grupo` (09-10/06) | `_spike_sendflow_lift.py`; coleta viva em `whatsapp_group_joins` (Railway) |
| Alavanca 2,1x do criativo em 26 LFs / nota leave-one-launch-out 1,83x | `projeto_score_criativo` | `nota_criativo.py` |

## 8. Saídas da sessão (além do painel)

- `criativos_dev21_ids_para_nomes.xlsx` (Desktop/bring_data): 33 ids Google → nomes, 2 abas (gerado por `nomes_ids.py`).
- `dev21_41_recuperados_por_telefone.csv`: os 41 compradores que só o telefone recupera (análise do gap de atribuição vs o gestor: ele casa só por email; nós email+fone+últimos 6; memória `projeto_atribuicao_gestor_email_vs_telefone`).
- PR #237 (chave canônica do histórico de criativo) mergeada na main; **deploy pendente** à data deste documento.

## 9. Reprodução conferida em 21/08 e o que ela mostrou

`teto_v2.py` foi rodado de novo contra a `main` de 21/08 e devolveu resultado **idêntico até a última casa decimal** (14 dentro / 11 acima, ROAS 2,19 vs 1,26, razão 1,7323583307292578, Fisher 0,011875757167855702). Os PRs #237, #238, #239 e #240 não o afetam: o script tem a própria função de chave canônica, não importa o publicador do painel e lê uma linha congelada da referência.

**Risco de reprodutibilidade identificado:** `analytics.reference_rolling` é upsert por `(client_id, window_end, source)`. Rodar o refresh de novo com `window_end=2026-07-13` sobrescreveria a âncora deste relatório. Não aconteceu (o carimbo continua `2026-08-03 19:15:53`), mas nada impede.

**Sensibilidade à régua de produção** (mesmos dados, só o teto escalado; ver §6-12):

| régua | dentro | verba dentro | ROAS dentro | ROAS acima | razão | Fisher | lucro preservado |
|---|---:|---:|---:|---:|---:|---:|---:|
| deste documento (crédito 1,00) | 14 | R$ 107.541 | 2,19 | 1,26 | 1,73x | 0,012 | 90% |
| produção até 20/08 (respondentes) | 8 | R$ 61.476 | 2,26 | 1,65 | 1,37x | 0,194 | 55% |
| produção desde 21/08 (crédito 0,38) | 9 | R$ 70.528 | 2,32 | 1,54 | 1,50x | 0,087 | 66% |

**Calibração medida:** o grupo aprovado cruza ROAS exatamente 2,00 no multiplicador **1,18** do teto deste documento, ou seja **27% acima** do teto de produção de 21/08. No DEV21 o teto é sistematicamente apertado, e cinco unidades trocam de lado entre as duas réguas: três com ROAS >= 2 (R$ 36.944 de lucro reprovado a mais) e duas com ROAS < 1 (acerto da régua nova). **R$ 29.898 desses R$ 36.944 são uma unidade só**, o AD0150-AD07 no HQLB frio, maior gasto do lançamento, que ficou R$ 0,04 dentro do teto e entregou ROAS 2,03. Conclusão com a justa medida: a certificação de 1,73x vale para a régua deste documento, não para a que está publicada, e um único ponto de fronteira domina a diferença.

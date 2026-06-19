# Análise — entrar no grupo de WhatsApp prevê compra? (lift, sem artefato de match)

**Data:** 2026-06-10
**Pergunta:** leads que **entram no grupo de WhatsApp** do lançamento compram mais do que os que não entram? E esse efeito é **real** ou é só **artefato da forma como casamos os dados** (match por telefone)?

**Resposta curta:** entrar no grupo está associado a **~2,5x** mais conversão (0,70% vs 0,28%). O efeito **não é artefato de match por telefone** — porque "comprou" é detectado **100% por e-mail** e "entrou" **100% por telefone**, chaves disjuntas. Sobra apenas o confounder de **seleção/causalidade** (quem entra pode já ser mais interessado), que é outra questão.

---

## Por que o desenho é assim (a parte que importa)

O risco metodológico levantado: se eu rotulo "entrou" casando lead × grupo **por telefone**, e também rotulo "comprou" **por telefone**, então leads com telefone limpo/casável ganham os dois rótulos com mais frequência → lift inflado por **mecânica de match**, não por efeito real.

Para neutralizar, as duas chaves são **propositalmente diferentes**:

| rótulo | chave de match | por quê |
|---|---|---|
| **Entrou no grupo** | **telefone** (DDD + últimos 8, `core.utils.telefone_chave_grupo`) | é a **única** chave que o SendFlow fornece (não há e-mail no evento de grupo) |
| **Comprou** | **e-mail** (normalizado) | chave **neutra** — não depende da qualidade do telefone, então não favorece o grupo "entrou" |

Como as chaves são disjuntas, o status "entrou" (telefone) **não interfere** mecanicamente na detecção de "comprou" (e-mail). Todo lead da base tem e-mail (é a chave da tabela), então os dois grupos (entrou / não entrou) são avaliados em pé de igualdade para conversão.

**Verificação empírica do ponto:** ao recontar a conversão de duas formas — (a) qualquer match e (b) só match por e-mail — o resultado foi **idêntico (2,52x)**. Motivo: **100% das conversões já casavam por e-mail** (`match_method='email'` em todos os LFs, zero por telefone). Então não havia conversão por telefone para inflar nada.

## Base de dados (e o que NÃO é a base)

- **Universo = todos os leads** que preencheram o formulário, da tabela **`Lead`** do Railway (via `SalesDataLoader.load_railway_leads`, por janela de captação de cada LF). Email + telefone.
- **NÃO é a tabela de pesquisa.** Um lead pode entrar no grupo sem responder a pesquisa; a taxa de conversão tem que ser sobre **todos os leads**, não condicionada a ter respondido. `load_railway_leads` traz as perguntas da pesquisa apenas como **colunas** (nulas se não respondeu), sem filtrar por isso.
- **Entradas no grupo:** os 9 exports "Histórico de atividades" do SendFlow (`data/devclub/SendFlow*.csv`), evento "Entrou no grupo", LF48–LF56 (~10/03–30/05). 97.760 telefones únicos.
- **Vendas (compras):** pipeline validado `validation.backtest_data.load_match_spend_for_lf` → `_load_sales` (Guru API + Hotmart API + Asaas + TMB local) → `combine_sales` → `match_leads_to_sales`. É a mesma fonte/lógica da validação de produção.

## Resultado

Pool: **110.106 leads** (LF48–55 + DEV20; LF56 vazio pós-migração), **69% entraram** no grupo.

| grupo | conversão (por e-mail) | n |
|---|---|---|
| Entrou no grupo | **0,70%** | 533 / 76.009 |
| Não entrou | **0,28%** | 95 / 34.097 |
| **Lift** | **2,52x** | — |

- Idêntico usando "toda conversão" vs "só conversão por e-mail" (porque conversão já era 100% e-mail).
- Spike anterior dera 3,2x — a diferença é universo (lá, pool condicionado a pesquisa/decil; aqui, **todos os leads**) e o "não entrou" converter um pouco mais aqui (0,28% vs 0,22%). **2,52x é o número mais honesto/geral.**

## Caveats

1. **Cobertura pós-migração:** `Lead` afina depois de ~17/05 (schema migrou); LF55/56 ficam sub-cobertos. O grosso (LF48–54) é sólido.
2. **LF52 anômalo:** só 14% entrou (vs ~70–77% nos outros) — cobertura de grupo esparsa nesse lançamento; puxa o lift agregado pra baixo (conservador).
3. **Confounder de seleção ≠ artefato de match.** O artefato de match (telefone) está **descartado**. Mas a **causalidade** não está provada: quem entra no grupo pode já ser um lead mais engajado/interessado, que compraria mais de qualquer jeito. O teste de redundância do spike (controlando pelo decil de produção) mostrou ~3x **dentro de cada decil** → o sinal não é só "o modelo já sabe", mas isolar causa vs seleção exigiria desenho experimental (ex.: grupo de controle).
4. **Offline mede "entrou em qualquer momento".** Em produção, com o atraso de scoring, a feature usa "entrou até o ponto de predição" — prevalência/lift podem diferir (medição live em [[projeto_sendflow_entrou_no_grupo]]).

## Como reproduzir

```
cd V2 && [carregar .env]
PYTHONPATH=. python3 -c "..."  # script em scripts/_spike_sendflow_lift.py (variante) — ver sessão 2026-06-10
```
Passos: (1) telefones do grupo dos CSVs (canon DDD+8); (2) `load_match_spend_for_lf` por LF → leads + `converted` + `match_method`; (3) `entrou` = telefone canônico ∈ grupo; `comprou` = `converted` com `match_method` por e-mail; (4) conversão entrou vs não.

---
*Análise ad-hoc da sessão de 2026-06-10, no contexto da feature "entrou no grupo" ([[projeto_sendflow_entrou_no_grupo]]). Read-only; não altera treino/produção.*

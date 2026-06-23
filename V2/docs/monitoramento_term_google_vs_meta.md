# Monitoramento do `utm_term`: separar Google legítimo do macro Meta quebrado

**Criado:** 2026-06-23
**Frente:** `feat/monitoring-term-source-aware` (só monitoramento — sem retreino)
**Relacionado:** [analise_valor_decil_por_canal_google_vs_meta.md](analise_valor_decil_por_canal_google_vs_meta.md)

> **Em uma frase:** o bucket "outros" do `utm_term` estava inflado por dois motivos que o alerta confundia — placeholder do Meta que não renderizou (problema real, pequeno) e ID de campanha do Google Ads (legítimo, crescente) — e esta frente ensina o monitoramento a separar os dois; o conserto definitivo (dar ao Google categoria própria) fica para o próximo retreino.

---

## 1. O problema

O campo `utm_term` deveria conter só o sub-source do Meta — `ig` (Instagram) ou `fb` (Facebook). Qualquer outra coisa cai no balde **"outros"** depois da unificação (`core/utm.py`). Dois conteúdos muito diferentes estavam caindo nesse mesmo balde e sendo somados como se fossem o mesmo problema:

| Conteúdo no `utm_term` | O que é | Volume | É problema? |
|---|---|---|---|
| `{{site_source_name}}`, `{{ad.name}}` etc. (literal) | **Macro do Meta não-substituído** — o anúncio manda o placeholder cru porque os parâmetros de URL estão URL-encoded no destino e o Meta não troca por `ig`/`fb`. Tráfego in-app. | ~1-3% dos leads de Meta | Sim, mas **operacional** (descodificar o macro no anúncio), não de modelo. Cai em `Term_outros`, que é categoria treinada — o modelo não quebra. |
| `23731741326--203657325788--8043819` (IDs com `--`) | **ID de campanha/conjunto/anúncio do Google Ads.** O Google põe isso no `utm_term` por padrão — ele **não tem** sub-source IG/FB. | ~23% do volume total (e crescendo) | **Não.** É legítimo. Cai em "outros" por design. |

### Por que aparecia "32% de drift" assustador

O alerta de **drift de distribuição** (`check_distribution_drift`, o que compara a proporção de cada categoria hoje contra a proporção no treino) media a população de produção **inteira, todas as fontes**, contra um baseline de treino que era **predominantemente Meta** (quando o Google era ~10% do mix). Como o Google cresceu para ~23%, a proporção de "outros" subiu de ~10,7% (treino) para ~32% (hoje) — **um artefato de mudança de mix de canal, não corrupção de dado.** A pista que entrega isso: Champion e Challenger mostravam o **mesmo** 32%, porque é um único número global comparado contra dois baselines diferentes.

Enquanto isso, o alerta-irmão de **bucket inflado** (`_check_outros_buckets`) já restringe o `utm_term` a `facebook-ads` e mostrava o número honesto (~1,7%) — o macro Meta de verdade.

---

## 2. O que mudou no monitoramento (esta frente, sem retreino)

### Item A — separar "categoria-nova" de "macro Meta" no alerta de bucket inflado

`_check_outros_buckets` (em `src/monitoring/data_quality.py`) agora classifica o conteúdo de "outros" em dois sub-tipos e aplica **gatilhos diferentes**:

- **categoria-nova** (valor de UTM nunca visto no treino — o sinal valioso, porque o modelo não tem feature pra ele): alerta no nível normal, **>2%**.
- **macro Meta não-resolvido** (`{{...}}` — artefato de tracking conhecido): **só alerta se estourar, >10%**. No nível normal de ~1-3% fica silencioso.

A separação vive na função de breakdown (`_query_railway_outros_breakdown_enriched`, que agora devolve `macro_count`/`novel_count` além de `outros_count`). Os thresholds e os marcadores de macro (`['{', '%7b']`) ficam em `src/monitoring/config.py` → `THRESHOLDS['outros_buckets']` (`min_pct_threshold`, `macro_spike_threshold`, `macro_markers`).

### Item B — silenciar o drift (Term, outros), porque o Google o domina

A medida de drift de "outros" no `utm_term` é cega de fonte (mistura Google), então foi **silenciada** via o mecanismo que já existia para isso: `silenced_drift_changes` no `configs/clients/devclub.yaml` (a mesma lista que já silencia `Term/facebook` e públicos do Medium). Com isso o alerta de **bucket inflado** (restrito a `facebook-ads`) passa a ser a **autoridade única** de "Term outros inflado" — eliminando a medida duplicada e cega-de-fonte, e resolvendo a inconsistência "produção all-sources × baseline Meta" sem precisar recomputar artefato nem retreinar.

**Cobertura preservada:** se o macro Meta realmente estourar, o Item A dispara (>10%, restrito a Meta). O silêncio do Item B só apaga o ruído do Google, não o sinal acionável do Meta.

---

## 3. Nota de retreino (frente futura — NÃO feita aqui)

No próximo retreino, **dar ao Google uma categoria própria no espaço de feature do `utm_term`** (ex.: `Term_google`) em vez de jogar todo o tráfego Google em `Term_outros`. Motivo: o volume de Google subiu de ~10% para ~23% e tende a crescer; misturá-lo com "outros" (que também contém o macro Meta quebrado e qualquer categoria genuinamente nova) desperdiça sinal e deixa o baseline de drift estruturalmente errado.

Pontos a considerar quando essa frente for executada:

1. **A discriminação Google × Meta já é parcialmente capturada pela feature `Source`** (`Source_google-ads` vs `Source_facebook-ads`). O ganho de uma categoria de `Term` própria é incremental — vale medir antes de assumir.
2. **O valor do lead Google já foi analisado** (ver [analise_valor_decil_por_canal_google_vs_meta.md](analise_valor_decil_por_canal_google_vs_meta.md)): o ranqueamento de decil do Challenger transfere pro Google e o valor (componente de conversão) é ≈ igual ao do Meta. Ou seja, o Google não é um público "pior" — só é um canal sem sub-source IG/FB.
3. **Ao recomputar o baseline de drift do treino** (`capture_training_distributions`), capturar a distribuição do `utm_term` de forma consistente com a feature nova (Google com rótulo próprio), pra o drift voltar a ser comparável.
4. **Quando o retreino entrar, o silêncio do Item B sai:** remover a entrada `Term/outros` de `silenced_drift_changes` e reavaliar o drift com o novo espaço de feature.

---

## 4. Como reverter / quando reavaliar

- **Item A:** ajustar/zerar `macro_spike_threshold` em `THRESHOLDS['outros_buckets']`; voltar a `min_pct_threshold` sozinho replica o comportamento antigo (todo "outros" conta junto).
- **Item B:** remover a entrada `Term/outros` de `silenced_drift_changes` no `devclub.yaml` reativa o drift cego-de-fonte.
- **Gatilho de reavaliação:** próximo retreino (item 3 acima), ou se a fatia de Google mudar bruscamente o suficiente pra distorcer também as proporções de `ig`/`fb` no drift (dilui​ção de Meta) — nesse caso o ideal passa a ser baseline Meta-only nos dois lados, não só silêncio.

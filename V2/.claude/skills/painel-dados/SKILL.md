---
name: painel-dados
description: Gera um painel visual polido e compartilhável (artefato HTML) a partir de QUALQUER conjunto de métricas. Mesma identidade visual sempre — eyebrow + título + stat tiles + gráficos (barras com desvio, barras agrupadas, linha) + tabela-mapa (heatmap) + seção "como ler". Use quando o usuário pedir "um painel / apresentação visual", "gráficos bonitos pra mostrar", "o mesmo estilo daquele painel", "transforma essa análise/tabela num visual", ou quiser comparar/mostrar estabilidade de métricas. Generaliza para outros dados — não é preso a um problema específico.
---

# painel-dados — painel visual reutilizável

Uma **identidade visual única** para apresentar dados no projeto, entregue como **artefato HTML compartilhável**. Você não redesenha nada: descreve um objeto `SPEC` (o quê mostrar) e o runtime monta o painel inteiro, já responsivo, com light/dark, hover, e paleta validada para daltonismo.

**O que a skill entrega de reprodutível:** a *habilidade* de produzir o painel, não um relatório específico. Dados novos, métricas novas → mesmo `SPEC`, mesmo visual.

## Quando usar
- Pediram "um painel / gráficos pra mostrar / apresentar" a partir de números.
- "Faz igual àquele painel" (qualidade por LF, ou qualquer outro).
- Transformar uma tabela/análise em algo visual e compartilhável.

## Quando NÃO usar
- Uma resposta curta em texto resolve (não force gráfico).
- Um só número → é um stat tile, não um painel (mas o painel aceita tiles).
- Edição de planilha/XLSX → isso é outra tarefa (openpyxl), não esta skill.

## Fluxo (5 passos)

1. **Descubra o job de cada métrica** e escolha a forma (regra do `/dataviz`):
   - magnitude / comparação entre categorias → `bars`
   - comparação de 2-3 séries por categoria → `grouped`
   - evolução no tempo/ordem → `line`
   - estabilidade / consistência → `bars`/`grouped` **com `std`** (a haste é ±1 desvio) e/ou `heat` de coeficiente de variação
   - um número-manchete → `tile`
2. **Copie o template** `template.html` (mesma pasta desta skill) para o scratchpad e **edite só o objeto `SPEC`** no topo do `<script>`. O schema completo está comentado no topo do arquivo. NÃO mexa no runtime abaixo do SPEC.
3. **Escreva a copy do lado do leitor** — título e subtítulos em linguagem natural, sem jargão de coluna/banco. Traga a conclusão nos `tiles` (a manchete) antes do detalhe.
4. **Paleta:** o template já vem com um ramo categórico **validado em light e dark** (`c1` azul, `c2` laranja, `c3` teal, `accent` violeta + status verde/amarelo/vermelho). Se trocar cor ou usar 4+ séries, **rode o validador** do `/dataviz` (`node scripts/validate_palette.js "<hex,hex>" --mode light|dark`) antes de publicar. Hues categóricas em ordem fixa, nunca cicladas.
5. **Publique** com a ferramenta **Artifact** (`favicon: 📊`, título curto, `description` de uma linha). Devolva a URL ao usuário. Se ele quiser PNG pra slide, exporte depois.

## Componentes do SPEC (o que o runtime sabe desenhar)
- `tiles`: cartões-manchete (rótulo + valor + nota). Cor por token (`accent`/`c1`/`c2`/`c3`).
- `chart.type:"bars"`: 1 série, barras; passe `std` por ponto → ganha haste de desvio + auto-escala + hover.
- `chart.type:"grouped"`: 2-3 séries lado a lado por grupo; legenda automática; `std` opcional.
- `chart.type:"line"`: 1+ séries sobre `xlabels`; marcadores com hover.
- `chart.type:"heat"`: tabela-mapa; cada célula colorida por `buckets` (`s`/`m`/`v` = verde/amarelo/vermelho). Ideal para CV/estabilidade.
- seção `{title, sub, html}`: prosa livre (ex.: "como ler", metodologia).

## Regras (herdadas de /dataviz e /artifact-design)
- **1 eixo por gráfico** — nunca dois eixos y. Escalas diferentes → dois gráficos.
- **Haste = ±1 desvio padrão** sempre que a mensagem for estabilidade; haste curta = estável.
- **Legenda quando ≥2 séries**; rótulo direto de valor em cada barra (não em todo ponto de linha).
- **Tema duplo** já resolvido no template (media query + `data-theme`). Não quebre.
- **Números com `tabular-nums`** (já no CSS).
- **Sem em dash (—)** em nenhum texto (regra global do Ramon): use vírgula, parênteses ou hífen simples.

## Métricas de estabilidade úteis (todas saem de um `groupby`)
Desvio padrão (σ, a haste) · Coeficiente de variação (CV=σ/média, o heatmap, adimensional) · Amplitude máx−mín · Tendência intra-período (inclinação: ruído vs deriva) · Variação entre grupos (σ das médias).

## Exemplo de referência
O `template.html` já vem com um `SPEC` preenchido (qualidade e custo por lançamento DevClub) que serve de exemplo vivo do schema. Publicá-lo direto renderiza esse painel; para um caso novo, troque o `SPEC`.

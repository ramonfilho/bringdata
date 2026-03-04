# src/nlp/ — NLP Module (Fase 5, futuro)

Reservado para extração de features de texto livre a partir de respostas de formulário.

## Interface planejada

```python
from src.nlp import extract_nlp_features
from src.core.client_config import FeatureConfig

df = extract_nlp_features(df, config.feature)
```

## Colunas de entrada

Definidas em `FeatureConfig.nlp_columns` — atualmente sempre vazio (`[]`).
Quando implementado, o campo receberá os nomes das colunas de texto livre
do formulário de cada cliente.

## Features de saída esperadas

- Sentimento (positivo/negativo/neutro)
- Intenção de compra
- Nível de maturidade técnica

## Dependências

Não implementar antes da Fase 5. Ver plano de refatoração:
`V2/docs/PLANO_REFACTOR_MLOPS.md`, Seção 4.4.

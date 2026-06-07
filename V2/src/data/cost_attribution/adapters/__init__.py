"""Adaptadores de custo por adset — uma implementação por fonte.

Cada adaptador sabe falar com uma fonte específica e traduzir o vocabulário
físico dela pro formato interno (`CplRecord`, `AdMapping`).

Hoje:
  - `railway`   — tabelas `cpl_adset` e `ad_to_adset_map` no Railway (fonte
                  de verdade, escrita pelo refresh job, lida por scripts e
                  pelo snapshot do scoring no startup).
  - `in_memory` — cache em RAM populado por snapshot do railway, pro hot
                  path do scoring container. Lookup μs.
"""

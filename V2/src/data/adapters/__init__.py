"""Adaptadores — uma implementação por fonte física dos leads.

Cada adaptador sabe falar com uma fonte específica (tabela do banco, API
externa, arquivo) e traduzir o vocabulário físico dela pro formato interno
`LeadRecord`. Trocar de fonte = trocar adaptador em 1 lugar (a função
`compose_repository`).
"""

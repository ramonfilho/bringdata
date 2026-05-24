"""Camada de acesso a leads.

Isola os consumidores (monitores, regras, endpoints) da fonte física dos dados.
Consumidor pede leads através do `LeadRepository` e recebe `LeadRecord`s — não
sabe se vieram do ledger novo (`registros_ml`), das tabelas antigas, ou de
fonte futura.

Estrutura:
- `lead_record.LeadRecord` — formato interno (DTO), contrato estável.
- `lead_repository.LeadRepository` — interface que cada adaptador implementa.
- `lead_repository.compose_repository()` — ponto único de composição: quem
  entra em produção (endpoint, scheduler) decide qual fonte usar.
- `adapters/` — uma implementação por fonte física.
"""
from .lead_record import LeadRecord
from .lead_repository import LeadRepository, compose_repository

__all__ = ['LeadRecord', 'LeadRepository', 'compose_repository']

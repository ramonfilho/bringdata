# Purchase Events CAPI — Status

## Feito
- `POST /capi/send_purchase_events` implementado em `api/app.py`
- Lookup de FBP/FBC no Railway em batch por email
- Envio com timestamp real da compra e valor real da venda
- Anomalias (sem FBP/FBC) registradas no retorno, não bloqueiam envio
- `dry_run` e `test_event_code` suportados

## Pendente
- [ ] Verificar se evento `Purchase` existe no Gerenciador de Eventos do DevClub
- [ ] Testar com `test_event_code` antes de soltar em produção
- [ ] Adicionar 3ª fonte de vendas ao `SalesDataLoader` (nova ferramenta implementada na semana de 09/03/2026)
- [ ] Criar caller script que usa `SalesDataLoader` + chama o endpoint (unifica com monitoramento)
- [ ] Corrigir bugs em `send_purchase_event()` em `capi_integration.py` (código legado morto — baixa prioridade)

# Google Ads — Pendências antes de implementar

> Criado: 14/04/2026

O cliente solicitou envio de eventos ao Google Ads analogamente ao que já fazemos com Meta CAPI.
A feature foi postergada até que os pré-requisitos abaixo estejam resolvidos.

## Pré-requisitos técnicos

1. **Captura de `gclid` na landing page.**
   Sem o `gclid` (Google Click ID) sendo capturado no formulário e enviado ao webhook, os eventos não são atribuídos a nenhuma campanha — a feature não tem valor nenhum. Verificar com a equipe de frontend/tráfego se o parâmetro `gclid` está sendo passado como UTM ou hidden field.

2. **Decisão: Enhanced Conversions vs Offline Conversion Import.**
   - Enhanced Conversions: envia no momento da captura (como o CAPI). Requer SHA-256 de email + telefone. Mais próximo do que já temos.
   - Offline Conversion Import: envia lote de conversões após confirmação de venda. Mais preciso mas mais tardio.

3. **Credenciais Google Ads API.**
   A API usa OAuth2 (Developer Token + Customer ID), diferente do token Bearer do Meta. Precisa ser provisionado antes de qualquer implementação.

## Ordem de execução sugerida

Implementar **após** o onboarding do segundo cliente estar estabilizado — o refactor `src/core/` multi-cliente é o bloqueante. Google Ads deve entrar na arquitetura multi-cliente desde o início, não como patch paralelo.

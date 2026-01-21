# Especificação do Sumário Crítico de Monitoramento

## Objetivo
Verificar as partes críticas da pipeline de produção e seu funcionamento de forma concisa, sem duplicação de informações.

**IMPORTANTE**: Este é o ÚNICO output do monitoramento. Todos os checks detalhados devem ser removidos. Apenas o sumário crítico deve ser impresso.

## Informações Obrigatórias (em ordem)

### 1. Categorias não vistas no treino
- **Formato**: Sim / Não
- **Se Sim**: Listar quais categorias e em quais colunas
- **Sem threshold aparecendo**

### 2. Mudanças drásticas nas proporções de colunas
- **Formato**: Sem threshold aparecendo
- **Mostrar apenas**: Nome das colunas com mudança drástica e quantificação da mudança
- **Somente se estiver acima do threshold**

### 3. Colunas com dados faltantes
- **Formato**: Sim / Não
- **Se Sim**: Listar quais colunas
- **Sem threshold aparecendo**

### 4. Features (características) faltantes
- **Formato**: Sim / Não
- **Se Sim**: Listar quais features
- **Observação**: Features esperadas pelo modelo mas não encontradas nos dados

### 5. Mudança significativa nas proporções de score e decil
- **Formato**: Sim / Não
- **Se Sim**: Especificar qual (score ou decil) e a mudança observada
- **Sem threshold aparecendo**

### 6. Recebimento regular de leads
- **Formato**: Sim / Não
- **Quantidade**: Leads nas últimas 24h (banco CAPI, não pesquisa)

### 7. Envio de Conversion API para Meta
- **Formato**: Sim / Não
- **Quantidade**: Eventos enviados nas últimas 24h

### 8. Preenchimento de cookies (FBP e FBC)
- **Formato**: Sim / Não
- **Percentuais**: % de preenchimento de FBP e FBC

### 9. Recebimento de eventos pela Meta
- **Formato**: Sim / Não
- **Percentual**: % de eventos recebidos nas últimas 24h

### 10. Relatório do Funil
**Formato sequencial**:
```
Leads CAPI → Respostas Pesquisa → Eventos Enviados → Eventos Recebidos
```

### 11. Porcentagens do Funil
- **% de resposta na pesquisa** (respostas / leads CAPI)
- **% de eventos enviados** (eventos enviados / respostas pesquisa)
- **% de eventos recebidos** (eventos recebidos / eventos enviados)

## Regras de Apresentação

1. **Sem duplicação**: Cada informação deve aparecer apenas uma vez
2. **Sem thresholds**: Não mostrar valores de threshold configurados
3. **Conciso**: Apenas informação crítica para verificar funcionamento
4. **Formato claro**: Sim/Não primeiro, depois detalhes se necessário
5. **Ordem fixa**: Sempre na ordem especificada acima

## Exemplo de Output Esperado

```
========================================================================
📊 SUMÁRIO CRÍTICO DO SISTEMA
========================================================================

1. Categorias não vistas no treino: Não

2. Mudanças drásticas nas proporções:
   - utm_medium: Variação de 45.2% (esperado: 30%, observado: 13.5%)
   - interesse_programacao: Variação de 32.1% (esperado: 25%, observado: 16.9%)

3. Colunas com dados faltantes: Sim
   - email_valido: 98.5% preenchido
   - telefone_valido: 97.2% preenchido

4. Features faltantes: Não

5. Mudança significativa em score/decil: Sim
   - Decil D10: Variação de 18.5% (esperado: 30%, observado: 35.5%)

6. Recebimento regular de leads: Sim (1,389 leads nas últimas 24h)

7. Envio CAPI para Meta: Sim (623 eventos enviados nas últimas 24h)

8. Cookies FBP/FBC preenchidos: Sim
   - FBP: 98.9%
   - FBC: 98.6%

9. Eventos recebidos pela Meta: Sim (86.7% de aceitação)

10. Funil de Conversão:
    Capturados: 1,389 → Respostas: 1,135 → Enviados: 623 → Aceitos: 540

11. Taxas de Conversão:
    - Resposta pesquisa: 81.7%
    - Envio CAPI: 54.9%
    - Aceitação Meta: 86.7%

========================================================================
```

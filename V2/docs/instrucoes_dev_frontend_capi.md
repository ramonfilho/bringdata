# 📋 Instruções 

**Dados capturados:**
- `_fbp` (Facebook Browser ID) - sempre presente
- `_fbc` (Facebook Click ID) - presente quando usuário clica em anúncio Meta
- Metadados: user agent, URL da página, event_id (para deduplicação)

---

## O que NÃO muda:

✅ **Envio para ActiveCampaign permanece inalterado**
- Dados de lead (nome, email, telefone) continuam indo para ActiveCampaign normalmente
- Fluxo de email marketing não é afetado
- Redirecionamento para página de obrigado mantido

## O que MUDA:

✅ **Adiciona captura de cookies Meta (_fbp, _fbc)**
- Cookies são capturados e enviados junto com dados do lead
- **Não bloqueia ou interfere** no envio para ActiveCampaign

---

## 📦 Opção 1: Substituição Completa (RECOMENDADO)

### Abra crie uma cópia da página e substitua o código do formulário por completo.

**Por que essa opção é melhor?**
- ✅ Menos chance de erro
- ✅ Mais rápido de implementar

### Passo a passo:

1. **Baixar arquivo:** `codigo_formulario_completo_com_capi.js`

2. **Criar cópia da página:** `https://lp5.rodolfomori.com.br/inscricao-lf-v2-crt/`
   - ⚠️ **IMPORTANTE:** Não alterar a página principal diretamente (tráfego ativo com valor alto diário)
   - Criar uma cópia/duplicata da página para testes
   - Exemplo: `https://lp5.rodolfomori.com.br/inscricao-lf-v2-crt-teste/`

3. **Localizar código JavaScript atual** na cópia da página
   - Procure por `submitToActiveCampaign` ou `addEventListener("click"`
   - Selecione TODO o bloco JavaScript relacionado ao formulário

4. **Substituir** código antigo pelo conteúdo do arquivo `codigo_formulario_completo_com_capi.js`

5. **Testar** (ver seção "Como Testar" abaixo)

### O que foi modificado?

| Linhas | Descrição | Status |
|--------|-----------|--------|
| 16-81 | Funções CAPI (getCookie, generateEventID, sendToCapiAPI) | **NOVO** ✨ |
| 83-132 | Função submitToActiveCampaign | Mantida |
| 134-227 | Setup de formulário, máscaras, validação | Mantido |
| 229-287 | Event listener do botão submit | Mantido |
| 274-287 | **Captura e envio de dados CAPI** | **NOVO** ✨ |
| 289-346 | Envio ActiveCampaign + redirecionamento | Mantido |

**Resumo:** Apenas **2 blocos novos** foram adicionados (funções CAPI + captura de cookies). Todo o resto permanece igual.

---

## 🛠️ Opção 2: Adicionar Código Manualmente

### Quando usar?
- Se substituição completa não for viável
- Se houver customizações específicas na página

### Passo 1: Adicionar funções CAPI

**Localização:** Logo após abertura da tag `<script>` do formulário

**Código a adicionar:**

```javascript
// ========================================================================
// FUNÇÕES CAPI (NOVO)
// ========================================================================

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
}

function generateEventID() {
  return `lead_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

async function sendToCapiAPI(name, email, phone, hasComputer, utm, fbp, fbc, eventID, userAgent, eventSourceUrl) {
  const payload = {
    name: name,
    email: email,
    phone: phone,
    tem_comp: hasComputer,
    fbp: fbp,
    fbc: fbc,
    event_id: eventID,
    user_agent: userAgent,
    event_source_url: eventSourceUrl,
    utm_source: utm.utm_source || null,
    utm_medium: utm.utm_medium || null,
    utm_campaign: utm.utm_campaign || null,
    utm_term: utm.utm_term || null,
    utm_content: utm.utm_content || null
  };

  try {
    const response = await fetch('https://bring-data-api-12955519745.us-central1.run.app/webhook/lead_capture', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const result = await response.json();
    console.log('✅ CAPI enviado:', result);
    return result;
  } catch (error) {
    console.error('❌ Erro CAPI:', error);
    return null;
  }
}
```

### Passo 2: Adicionar captura CAPI no event listener

**Localização:** Dentro do `submitButton.addEventListener("click", ...)`, APÓS a captura de dados do formulário (fullname, email, phone, etc) e ANTES do envio para ActiveCampaign

**Procure por algo assim:**
```javascript
const hasComputer = radioSim && radioSim.checked ? "SIM" : "Não";
const utmParams = getUTMParameters();

// <-- ADICIONAR CÓDIGO AQUI
```

**Código a adicionar:**

```javascript
// ========================================================================
// CAPTURA DE DADOS CAPI (NOVO)
// ========================================================================
const fbp = getCookie('_fbp');
const fbc = getCookie('_fbc');
const eventID = generateEventID();
const userAgent = navigator.userAgent;
const eventSourceUrl = window.location.href;

console.log('📊 CAPI - FBP:', fbp || '❌ ausente', '| FBC:', fbc || '⚠️ ausente (normal se não clicou em anúncio)');

// Enviar para CAPI API (não bloqueia o fluxo)
sendToCapiAPI(fullname, email, phone, hasComputer, utmParams, fbp, fbc, eventID, userAgent, eventSourceUrl);
// ========================================================================
```

⚠️ **ATENÇÃO:** Certifique-se de que as variáveis `fullname`, `email`, `phone`, `hasComputer`, `utmParams` já foram definidas ANTES deste código.

---

## 🧪 Como Testar

### 1. Abrir Console do Navegador

**Mac:** `Cmd + Option + I` → aba "Console"
**Windows:** `F12` ou `Ctrl + Shift + I` → aba "Console"

### 2. Preencher Formulário de Teste

- Nome: Teste CAPI
- Email: teste.capi@devclub.com.br
- Telefone: (11) 96123-4567
- Tem computador: Sim

### 3. Clicar em "Enviar"

### 4. Verificar mensagens no Console

**Deve aparecer:**

```
📊 CAPI - FBP: fb.1.1234567890123.987654321 | FBC: ⚠️ ausente (normal se não clicou em anúncio)
✅ CAPI enviado: {status: "success", message: "Lead capturado com sucesso", lead_id: 1, event_id: "lead_..."}
```

**Explicação:**
- `FBP` presente = ✅ Tudo funcionando!
- `FBC` ausente = ⚠️ Normal (só existe quando clica em anúncio Meta)
- `CAPI enviado` = ✅ Dados chegaram na API!

### 5. Verificar redirecionamento

Após ver mensagem de sucesso, você deve ser redirecionado para:
```
https://lp5.rodolfomori.com.br/parabens-psq-devf/?nome=...&email=...
```

Se redirecionamento aconteceu = ✅ **Tudo funcionando corretamente!**

---

## 🚀 Aplicar na Página Principal

Após testar na cópia e confirmar que **TUDO está funcionando corretamente** (Console mostra CAPI enviado + redirecionamento funciona):

1. **Aplicar na página principal:** `https://lp5.rodolfomori.com.br/inscricao-lf-v2-crt/`
   - Repetir os mesmos passos de substituição do código
   - Localizar código JavaScript atual
   - Substituir pelo conteúdo de `codigo_formulario_completo_com_capi.js`

2. **Testar novamente** na página principal
   - Abrir Console (Cmd + Option + I)
   - Preencher formulário de teste
   - Confirmar que Console mostra `✅ CAPI enviado`
   - Confirmar redirecionamento

3. ✅ **Pronto!** A página principal agora está capturando dados CAPI

---

## ❌ Possíveis Erros e Soluções

### Erro: "getCookie is not defined"
**Causa:** Funções CAPI não foram adicionadas
**Solução:** Adicionar funções CAPI (Opção 2 - Passo 1) ou usar substituição completa (Opção 1)

### Erro: "Cannot read property 'value' of null"
**Causa:** IDs dos campos estão diferentes
**Solução:** Verificar se IDs são `#fullname`, `#email`, `#phone-input`, `#field_144SIM`, `#field_144Não`

### Não redireciona para página de obrigado
**Causa:** Erro no envio para ActiveCampaign (não relacionado a CAPI)
**Solução:** Verificar logs no Console, testar sem modificações CAPI primeiro

### Console não mostra mensagem CAPI
**Causa:** Código CAPI não foi adicionado ou está em local errado
**Solução:** Verificar se código está ANTES do envio ActiveCampaign

---

## 📞 Suporte

**Em caso de dúvidas:**
1. Verificar mensagens de erro no Console (F12 → aba Console)
2. Confirmar que ActiveCampaign continua funcionando normalmente
3. Contactar o autor deste arquivo.
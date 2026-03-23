/**
 * CÓDIGO MODIFICADO PARA PÁGINA 2 - Pesquisa DevClub
 *
 * ⚠️ SHADOW DEPLOY - DUAL WRITE
 *
 * Este código implementa migração gradual do Google Sheets para PostgreSQL:
 * 1. MANTÉM o envio atual para Google Sheets (via form.action original)
 * 2. ADICIONA envio paralelo para PostgreSQL (novo endpoint /webhook/update_survey)
 * 3. Ambos os sistemas recebem dados simultaneamente
 * 4. Se qualquer um falhar, usuário ainda vê tela de sucesso
 *
 * IMPORTANTE: A landing page possui 12 steps de perguntas (0-11),
 * mas apenas 10 campos são enviados para o PostgreSQL:
 * - Step 7 ("Qual é sua urgência?") - IGNORADO (coluna indevida)
 * - Step 10 ("Qual é sua maior barreira?") - IGNORADO (coluna indevida)
 *
 * Campos fbp, fbc e UTMs NÃO são enviados na Página 2 pois já foram
 * capturados na Página 1 e estão salvos no PostgreSQL.
 *
 * ============================================================================
 * COMO TESTAR (Front-End)
 * ============================================================================
 *
 * 1. Console do Navegador (F12 → Console):
 *    ✅ Deve aparecer: "[SHADOW DEPLOY] Iniciando dual write..."
 *    ✅ Deve aparecer: "[1/2] Google Sheets: sucesso"
 *    ✅ Deve aparecer: "[2/2] PostgreSQL: sucesso"
 *
 * 2. Network Tab (F12 → Network → Filtro XHR/Fetch):
 *    ✅ Deve ter 2 requests simultâneos
 *    ✅ Request para "webhook/update_survey" → Status 200
 *
 * 3. UX:
 *    ✅ Loading aparece
 *    ✅ Loading desaparece (~1-2 segundos)
 *    ✅ Tela final aparece normalmente
 *
 * Se os 3 itens acima funcionarem, deploy está OK.
 */

// ============================================================================
// FUNÇÃO PARA COLETAR RESPOSTA SELECIONADA DE UM STEP
// ============================================================================
function getSelectedAnswer(stepIndex) {
  const step = document.querySelectorAll('.step')[stepIndex];
  if (!step) return null;

  const selectedRadio = step.querySelector('input[type="radio"]:checked');
  if (!selectedRadio) return null;

  // Pegar o texto da label associada ao radio
  const label = selectedRadio.closest('label') || selectedRadio.nextElementSibling;
  return label ? label.textContent.trim() : null;
}

// ============================================================================
// FUNÇÃO PARA PEGAR PARÂMETROS DA URL
// ============================================================================
function getURLParameter(name) {
  const urlParams = new URLSearchParams(window.location.search);
  return urlParams.get(name);
}

// ============================================================================
// FUNÇÃO PRINCIPAL - SHADOW DEPLOY (DUAL WRITE)
// ============================================================================
function submitFormData() {
  console.log('📤 [SHADOW DEPLOY] Iniciando dual write...');

  // Mostrar loading
  const loadingOverlay = document.getElementById('loading-overlay');
  if (loadingOverlay) {
    loadingOverlay.style.display = 'flex';
  }

  // Controle de finalização: esconder loading quando XHR completar
  // (mantém comportamento original)
  function finalizarSubmissao() {
    setTimeout(function() {
      console.log('✅ [SHADOW DEPLOY] Dual write concluído, mostrando tela final');
      if (loadingOverlay) {
        loadingOverlay.style.display = 'none';
      }
      showFinalStep();
    }, 1000);
  }

  // ============================================================================
  // SISTEMA ATUAL: Envio para Google Sheets (via form.action)
  // ============================================================================
  console.log('📊 [1/2] Enviando para Google Sheets (sistema atual)...');

  const form = document.getElementById('multi-step-form');
  const formData = new FormData(form);

  const xhr = new XMLHttpRequest();
  xhr.open('POST', form.action, true);
  xhr.onreadystatechange = function() {
    if (xhr.readyState === 4) {
      if (xhr.status === 200) {
        console.log('✅ [1/2] Google Sheets: sucesso');
      } else {
        console.warn('⚠️ [1/2] Google Sheets: falha (status ' + xhr.status + ')');
      }
      // IMPORTANTE: Esconder loading e mostrar tela final quando XHR completar
      // (mantém comportamento original - código legado)
      finalizarSubmissao();
    }
  };
  xhr.send(formData);

  // ============================================================================
  // NOVO SISTEMA: Envio paralelo para PostgreSQL
  // ============================================================================
  console.log('🗄️ [2/2] Enviando para PostgreSQL (novo sistema)...');

  // 1. Coletar dados básicos da URL (vindos da Página 1)
  const nome = getURLParameter('nome');
  const email = getURLParameter('email');
  const telefone = getURLParameter('telefone');
  const computador = getURLParameter('computador');

  // 2. Coletar respostas da pesquisa (10 campos enviados de 12 steps)
  // ATENÇÃO: Steps 7 e 10 são IGNORADOS (colunas indevidas no formulário)
  const respostas = {
    genero: getSelectedAnswer(0),                // Step 0: O seu gênero
    idade: getSelectedAnswer(1),                 // Step 1: Qual a sua idade?
    ocupacao: getSelectedAnswer(2),              // Step 2: Situação profissional
    faixa_salarial: getSelectedAnswer(3),        // Step 3: Quanto você ganha
    cartao_credito: getSelectedAnswer(4),        // Step 4: Tem cartão de crédito
    investiu_curso_online: getSelectedAnswer(5), // Step 5: Já comprou curso online
    estudou_programacao: getSelectedAnswer(6),   // Step 6: Já estudou programação
    // Step 7: "Urgência" - IGNORADO (não existe coluna no PostgreSQL)
    interesse_programacao: getSelectedAnswer(8), // Step 8: Maior motivo
    interesse_evento: getSelectedAnswer(9),      // Step 9: O que quer ver no evento
    // Step 10: "Barreira" - IGNORADO (não existe coluna no PostgreSQL)
    pretende_faculdade: getSelectedAnswer(11)    // Step 11: Investiria na formação
  };

  // 3. Gerar event_id único para CAPI da Página 2
  // NOTA: fbp, fbc e UTMs já foram capturados na Página 1 e estão salvos no banco
  const event_id = `lead_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

  // 4. Montar payload para PostgreSQL
  const payload = {
    // Dados básicos (vindos da URL da Página 1)
    name: nome,
    first_name: nome ? nome.split(' ')[0] : null,
    last_name: nome ? nome.split(' ').slice(1).join(' ') : null,
    email: email,
    phone: telefone,
    tem_comp: computador,

    // Event ID único para CAPI da Página 2
    // NOTA: fbp, fbc, UTMs já estão no banco (capturados na Página 1)
    event_id: event_id,

    // Dados da pesquisa
    genero: respostas.genero,
    idade: respostas.idade,
    ocupacao: respostas.ocupacao,
    faixa_salarial: respostas.faixa_salarial,
    cartao_credito: respostas.cartao_credito,
    interesse_evento: respostas.interesse_evento,
    estudou_programacao: respostas.estudou_programacao,
    pretende_faculdade: respostas.pretende_faculdade,
    investiu_curso_online: respostas.investiu_curso_online,
    interesse_programacao: respostas.interesse_programacao,
    cidade: null  // Não coletado neste formulário
  };

  console.log('📦 Payload PostgreSQL montado:', payload);

  // 5. Enviar para webhook do Cloud Run (PostgreSQL)
  const webhookURL = 'https://smart-ads-api-12955519745.us-central1.run.app/webhook/update_survey';

  fetch(webhookURL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  })
  .then(response => response.json())
  .then(data => {
    console.log('✅ [2/2] PostgreSQL: sucesso', data);

    // Verificar se scoring foi executado
    if (data.scored) {
      console.log('🎯 Score ML gerado:', data.lead_score);
      console.log('📊 Decil:', data.decil);
    }
  })
  .catch(error => {
    console.error('❌ [2/2] PostgreSQL: erro', error);
    // Continuar mesmo com erro - não bloquear UX
  });

  // NOTA: A finalização (loading + tela final) é controlada pelo callback do XHR
  // quando ele completar (readyState === 4), mantendo comportamento original
}

// ============================================================================
// MAPEAMENTO DE CAMPOS (Referência)
// ============================================================================
/*
MAPEAMENTO PostgreSQL → Google Sheets:

PostgreSQL          → Google Sheets Original
-------------------   ----------------------------------------
genero              → "O seu gênero:"
idade               → "Qual a sua idade?"
ocupacao            → "O que você faz atualmente?"
faixa_salarial      → "Atualmente, qual a sua faixa salarial?"
cartao_credito      → "Você possui cartão de crédito?"
interesse_evento    → "O que mais você quer ver no evento?"
estudou_programacao → "Já estudou programação?"
pretende_faculdade  → "Você já fez/faz/pretende fazer faculdade?"
investiu_curso_online → "Já investiu em algum curso online..."
interesse_programacao → "O que mais te chama atenção na profissão de Programador?"

CAMPOS IGNORADOS (existem na página mas NÃO são enviados ao PostgreSQL):
Step 7: "Qual é sua urgência para entrar na área?" - Coluna indevida
Step 10: "Qual é sua maior barreira hoje?" - Coluna indevida

Esses campos não possuem colunas correspondentes no PostgreSQL e causariam
erro 422 (Unprocessable Entity) se enviados ao backend.
*/

// ============================================================================
// NOTAS DE IMPLEMENTAÇÃO - SHADOW DEPLOY
// ============================================================================
/*
ESTRATÉGIA DE MIGRAÇÃO:

1. FASE ATUAL (Shadow Deploy):
   - Google Sheets: continua recebendo dados via form.action (sistema legado)
   - PostgreSQL: recebe dados em paralelo via /webhook/update_survey (novo sistema)
   - Ambos executam simultaneamente (dual write)
   - Falhas são logadas mas não bloqueiam UX

2. VALIDAÇÃO:
   - Comparar dados entre Google Sheets e PostgreSQL
   - Monitorar logs para identificar discrepâncias
   - Validar scoring ML e envio CAPI
   - Período recomendado: 1-2 semanas

3. CUTOVER (Fase Final):
   - Após validação, remover código de envio para Google Sheets (linhas 63-77)
   - Manter apenas envio para PostgreSQL
   - Desativar Google Sheets como fonte primária

CAMPOS ENVIADOS:

Para PostgreSQL (novo sistema):
- 10 campos de pesquisa (steps 7 e 10 ignorados)
- event_id único para CAPI
- Dados básicos da URL (nome, email, telefone, computador)
- NÃO envia: fbp, fbc, UTMs (já capturados na Página 1)

Para Google Sheets (sistema atual):
- FormData automático (todos os inputs com atributo "name")
- Mantém comportamento existente inalterado

BACKEND:

O endpoint /webhook/update_survey fará:
1. Buscar lead por email (criado na Página 1)
2. OU criar novo se não existir
3. Atualizar com dados da pesquisa
4. Gerar score ML (~500ms)
5. Enviar para CAPI com fbp/fbc/UTMs do banco (~300ms)
6. Total: ~1-2 segundos

Se backend PostgreSQL falhar, usuário ainda vê tela de sucesso (UX preserved).
Google Sheets continua recebendo dados normalmente como fallback.
*/

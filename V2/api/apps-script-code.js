/**
 * ========================================
 * SMART ADS - LEAD SCORING ML AUTOMATION
 * ========================================
 *
 * Sistema automatizado de predições ML e análise UTM
 * - Polling 5min: Predições ML + CAPI
 * - Relatórios diários: 00:00 (análises UTM 1D, 3D, 7D)
 * - Monitoramento: 01:00 e 13:00 (drift, qualidade, alertas Slack)
 */

// =============================================================================
// CONFIGURAÇÕES
// =============================================================================

const API_URL = 'https://smart-ads-api-12955519745.us-central1.run.app';
const SERVICE_ACCOUNT_EMAIL = 'smart-ads-451319@appspot.gserviceaccount.com';
const META_ACCOUNT_ID = 'act_188005769808959';  // Los Angeles Producciones LTDA (PRODUÇÃO)
const SLACK_WEBHOOK_URL = 'https://hooks.slack.com/services/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';

// =============================================================================
// MENU
// =============================================================================

/**
 * Função executada automaticamente quando a planilha é aberta
 * Trigger padrão do Google Sheets
 */
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('Smart Ads')
    .addItem('Ativar Polling 5min', 'agendarGatilho5Min')
    .addSeparator()
    .addItem('Testar Conexão', 'testConnection')
    .addItem('Testar Monitoramento', 'executarMonitoramentoDiario')
    .addToUi();
}

/**
 * Alias para compatibilidade
 */
function aoAbrir() {
  onOpen();
}

// =============================================================================
// FUNÇÕES PRINCIPAIS - NOVA ARQUITETURA (CAPI 1H + RELATÓRIOS DIÁRIOS)
// =============================================================================

/**
 * Encontra a linha dos cabeçalhos na planilha
 * Procura pela linha que contém "Data" E "E-mail" (colunas obrigatórias)
 * Retorna: { headerRow: número da linha (0-indexed), headers: array }
 */
function encontrarLinhaDosCabecalhos(values) {
  if (!values || values.length === 0) {
    throw new Error('Planilha vazia');
  }

  // Procurar linha que contém "Data" E "E-mail"
  for (let i = 0; i < values.length; i++) {
    const row = values[i];
    const hasData = row.some(cell => cell === 'Data');
    const hasEmail = row.some(cell => cell === 'E-mail');

    if (hasData && hasEmail) {
      Logger.log(`✅ Cabeçalho encontrado na linha ${i + 1}`);
      return {
        headerRow: i,
        headers: row
      };
    }
  }

  throw new Error('Cabeçalho não encontrado. Procurando por colunas "Data" e "E-mail"');
}

/**
 * Busca leads pendentes de processamento (sem score, após o último processado)
 * Retorna: { leads: [...], lastProcessedDate: Date }
 */
function buscarLeadsPendentes() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('[LF] Pesquisa');
  if (!sheet) throw new Error('Aba "[LF] Pesquisa" não encontrada');

  const values = sheet.getDataRange().getValues();
  if (values.length <= 1) {
    return { leads: [], lastProcessedDate: null };
  }

  // Buscar cabeçalho dinamicamente
  const { headerRow, headers } = encontrarLinhaDosCabecalhos(values);
  const dataColIndex = headers.indexOf('Data');
  const scoreColIndex = headers.indexOf('lead_score');

  if (dataColIndex === -1) {
    throw new Error('Coluna "Data" não encontrada');
  }

  // ====================================================================
  // ETAPA 1: Encontrar a data MAIS RECENTE entre leads COM score
  // (não importa a posição na planilha, apenas o timestamp)
  // ====================================================================
  let lastProcessedDate = null;
  const firstDataRow = headerRow + 1;

  Logger.log('🔍 Procurando data mais recente de lead COM score...');

  for (let i = firstDataRow; i < values.length; i++) {
    const row = values[i];

    // Ignorar cabeçalhos duplicados
    if (row[dataColIndex] === 'Data' && row[headers.indexOf('E-mail')] === 'E-mail') {
      continue;
    }

    const hasScore = scoreColIndex !== -1 && row[scoreColIndex];

    if (hasScore) {
      try {
        const leadDate = new Date(row[dataColIndex]);

        // Validar se é uma data válida
        if (!isNaN(leadDate.getTime())) {
          // Se não há data processada ainda, ou esta é mais recente
          if (!lastProcessedDate || leadDate > lastProcessedDate) {
            lastProcessedDate = leadDate;
          }
        }
      } catch (e) {
        // Ignorar datas inválidas
        Logger.log(`⚠️ Data inválida na linha ${i + 1}: ${row[dataColIndex]}`);
      }
    }
  }

  if (lastProcessedDate) {
    Logger.log(`✅ Última data processada encontrada: ${lastProcessedDate.toISOString()}`);
  } else {
    Logger.log('⚠️ Nenhum lead com score encontrado (primeira execução)');
  }

  // ====================================================================
  // ETAPA 2: Buscar TODOS os leads SEM score com data POSTERIOR
  // (varrer toda a planilha, não importa a ordem das linhas)
  // ====================================================================
  const pendingLeads = [];
  let skippedCount = 0;

  Logger.log('🔍 Buscando leads SEM score com data posterior...');

  for (let i = firstDataRow; i < values.length; i++) {
    const row = values[i];

    // Ignorar cabeçalhos duplicados
    if (row[dataColIndex] === 'Data' && row[headers.indexOf('E-mail')] === 'E-mail') {
      Logger.log(`⚠️ Cabeçalho duplicado detectado na linha ${i + 1}, ignorando...`);
      continue;
    }

    try {
      const leadDate = new Date(row[dataColIndex]);

      // Validar se é uma data válida
      if (isNaN(leadDate.getTime())) {
        skippedCount++;
        continue;
      }

      const hasScore = scoreColIndex !== -1 && row[scoreColIndex];

      // Lead não tem score E é após o último processado (ou não há último)
      if (!hasScore && (!lastProcessedDate || leadDate > lastProcessedDate)) {
        const leadData = {};
        headers.forEach((header, index) => {
          leadData[header] = row[index];
        });

        const emailValue = row[headers.indexOf('E-mail')];
        const email = emailValue ? String(emailValue) : null;

        // Validar que tem email
        if (email && email.trim() !== '') {
          pendingLeads.push({
            data: leadData,
            email: email,
            row_id: (i + 1).toString(),
            leadDate: leadDate  // Guardar data para debug
          });
        } else {
          skippedCount++;
        }
      }
    } catch (e) {
      // Ignorar linhas com erro
      Logger.log(`⚠️ Erro ao processar linha ${i + 1}: ${e.message}`);
      skippedCount++;
    }
  }

  // Ordenar leads pendentes por data (do mais antigo para o mais novo)
  // Isso garante processamento em ordem cronológica
  pendingLeads.sort((a, b) => a.leadDate - b.leadDate);

  if (pendingLeads.length > 0) {
    Logger.log(`✅ ${pendingLeads.length} leads pendentes encontrados`);
    Logger.log(`   Data mais antiga: ${pendingLeads[0].leadDate.toISOString()}`);
    Logger.log(`   Data mais recente: ${pendingLeads[pendingLeads.length - 1].leadDate.toISOString()}`);
  }

  if (skippedCount > 0) {
    Logger.log(`⚠️ ${skippedCount} linhas ignoradas (data inválida ou sem email)`);
  }

  return {
    leads: pendingLeads,
    lastProcessedDate: lastProcessedDate
  };
}

/**
 * Gera predições para leads pendentes
 */
function gerarPredicoesLeadsPendentes(leads) {
  if (leads.length === 0) {
    Logger.log('✅ Nenhum lead para gerar predições');
    return;
  }

  Logger.log(`📊 Processando ${leads.length} leads pendentes`);

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('[LF] Pesquisa');
  const values = sheet.getDataRange().getValues();

  // Buscar cabeçalho dinamicamente
  const { headerRow, headers } = encontrarLinhaDosCabecalhos(values);
  const scoreColIndex = headers.indexOf('lead_score');

  // Processar em lotes de 600
  const MAX_BATCH_SIZE = 600;
  const batches = [];
  for (let i = 0; i < leads.length; i += MAX_BATCH_SIZE) {
    batches.push(leads.slice(i, i + MAX_BATCH_SIZE));
  }

  Logger.log(`📦 Dividindo em ${batches.length} lotes`);

  let allPredictions = [];

  for (let batchIndex = 0; batchIndex < batches.length; batchIndex++) {
    const batch = batches[batchIndex];
    Logger.log(`📤 Enviando lote ${batchIndex + 1}/${batches.length} (${batch.length} leads)`);

    const payload = JSON.stringify({ leads: batch });
    const options = {
      method: 'post',
      contentType: 'application/json',
      payload: payload,
      muteHttpExceptions: true
    };

    const response = UrlFetchApp.fetch(`${API_URL}/predict/batch`, options);
    const responseCode = response.getResponseCode();

    if (responseCode !== 200) {
      throw new Error(`API retornou erro ${responseCode}: ${response.getContentText()}`);
    }

    const result = JSON.parse(response.getContentText());
    allPredictions = allPredictions.concat(result.predictions);

    Logger.log(`✅ Lote ${batchIndex + 1} processado: ${result.predictions.length} predições`);

    // Delay entre lotes
    if (batchIndex < batches.length - 1) {
      Utilities.sleep(1000);
    }
  }

  // Escrever predições na planilha
  Logger.log(`💾 Escrevendo ${allPredictions.length} predições na planilha...`);

  // Verificar/criar coluna lead_score
  if (scoreColIndex === -1) {
    sheet.getRange(headerRow + 1, headers.length + 1).setValue('lead_score');
  }

  const scoreCol = scoreColIndex !== -1 ? scoreColIndex + 1 : headers.length + 1;

  // Verificar/criar coluna decil (ao lado de lead_score)
  const decilColIndex = headers.indexOf('decil');
  let decilCol;

  if (decilColIndex === -1) {
    // Coluna decil não existe, criar ao lado de lead_score
    decilCol = scoreCol + 1;
    sheet.getRange(headerRow + 1, decilCol).setValue('decil');
  } else {
    decilCol = decilColIndex + 1;
  }

  // Escrever score e decil
  for (const pred of allPredictions) {
    const rowNum = parseInt(pred.row_id);
    sheet.getRange(rowNum, scoreCol).setValue(pred.lead_score);
    sheet.getRange(rowNum, decilCol).setValue(pred.decil);
  }

  SpreadsheetApp.flush();
  Logger.log(`✅ Predições (score + decil) escritas com sucesso`);
}

/**
 * Envia CAPI para leads pendentes (após receber score)
 */
function enviarLoteCapiLeadsPendentes(leads) {
  if (leads.length === 0) {
    Logger.log('✅ Nenhum lead para enviar CAPI');
    return;
  }

  try {
    Logger.log(`📤 Enviando ${leads.length} leads para CAPI...`);

    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('[LF] Pesquisa');
    const values = sheet.getDataRange().getValues();

    // Buscar cabeçalho dinamicamente
    const { headerRow, headers } = encontrarLinhaDosCabecalhos(values);

    const phoneColIndex = headers.indexOf('Telefone');
    const scoreColIndex = headers.indexOf('lead_score');

    // Preparar leads com scores atualizados
    const leadsWithScores = [];

    for (const lead of leads) {
      const rowNum = parseInt(lead.row_id);
      const row = values[rowNum - 1];
      const leadScore = row[scoreColIndex];

      if (!leadScore) {
        Logger.log(`⚠️ Lead ${lead.email} sem score, pulando CAPI`);
        continue;
      }

      const leadData = {
        email: lead.email,
        phone: row[phoneColIndex],
        lead_score: leadScore,
        data: Utilities.formatDate(new Date(lead.data['Data']), Session.getScriptTimeZone(), "yyyy-MM-dd'T'HH:mm:ss")
      };

      // Adicionar todos os campos da pesquisa
      headers.forEach((header, index) => {
        if (header !== 'email' && header !== 'phone' && header !== 'lead_score' && header !== 'decil' && header !== 'data') {
          leadData[header] = row[index];
        }
      });

      leadsWithScores.push(leadData);
    }

    if (leadsWithScores.length === 0) {
      Logger.log('⚠️ Nenhum lead com score para enviar CAPI');
      return;
    }

    // Enviar para API
    const payload = {
      leads: leadsWithScores
    };

    const options = {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    const response = UrlFetchApp.fetch(`${API_URL}/capi/process_daily_batch`, options);
    const responseCode = response.getResponseCode();
    const responseBody = response.getContentText();

    if (responseCode === 200) {
      const result = JSON.parse(responseBody);
      Logger.log(`✅ Batch CAPI enviado: ${result.success}/${result.total} eventos com sucesso`);
      Logger.log(`   Leads com dados CAPI: ${result.leads_with_capi_data}`);
    } else {
      Logger.log(`❌ Erro no batch CAPI: ${responseCode} - ${responseBody}`);
    }

  } catch (error) {
    Logger.log(`❌ Erro ao enviar batch CAPI: ${error.message}`);
    Logger.log(error.stack);
  }
}

/**
 * Execução 1x/dia às 00:00
 * PESADA: ~3-5 min
 *
 * Atualiza relatórios UTM (análise completa de TODOS os dados históricos)
 * e informações do modelo ativo
 */
function executarRelatoriosDiarios() {
  try {
    Logger.log('🌙 Executando relatórios diários - ' + new Date().toISOString());

    // Etapa 1: Atualizar análises UTM (PESADO - 3-5 min)
    // DESABILITADO: Geração de abas de análise UTM
    // Logger.log('📊 Atualizando análises UTM completas...');
    // atualizarAnaliseUTM();

    // Etapa 2: Atualizar Info do Modelo (se mudou)
    // DESABILITADO: Geração da aba Info do Modelo
    // Logger.log('ℹ️ Verificando info do modelo...');
    // atualizarInfoModeloSeAlterado();

    Logger.log('✅ Relatórios diários concluídos com sucesso');

  } catch (error) {
    Logger.log(`❌ Erro nos relatórios diários: ${error.message}`);
    Logger.log(error.stack);

    // Enviar email de erro
    const email = Session.getEffectiveUser().getEmail();
    MailApp.sendEmail({
      to: email,
      subject: '❌ Erro Smart Ads ML - Relatórios Diários',
      body: `Erro nos relatórios de ${new Date().toLocaleString()}:\n\n${error.message}\n\n${error.stack}`
    });
  }
}

// =============================================================================
// FUNÇÕES AUXILIARES: ANÁLISE UTM
// =============================================================================

/**
 * Atualiza análises UTM (1D, 3D, 7D) com custos do Meta Ads
 * OTIMIZADO: Processa apenas últimos 7 dias para evitar erro 413
 */
function atualizarAnaliseUTM() {
  try {
    Logger.log('📊 Atualizando análises UTM (últimos 7 dias)...');

    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('[LF] Pesquisa');
    if (!sheet) throw new Error('Aba "[LF] Pesquisa" não encontrada');

    // Ler dados da planilha
    const values = sheet.getDataRange().getValues();
    if (values.length <= 1) {
      Logger.log('⚠️ Nenhum dado na planilha');
      return;
    }

    // Buscar cabeçalho dinamicamente
    const { headerRow, headers } = encontrarLinhaDosCabecalhos(values);

    // ====================================================================
    // FILTRO TEMPORAL: Apenas últimos 7 dias (evita payload > 32 MB)
    // ====================================================================
    const sevenDaysAgo = new Date();
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
    sevenDaysAgo.setHours(0, 0, 0, 0);

    Logger.log(`📅 Filtrando leads desde: ${sevenDaysAgo.toLocaleString()}`);

    // Encontrar índice da coluna "Data"
    const dataColumnIndex = headers.indexOf('Data');
    if (dataColumnIndex === -1) {
      throw new Error('Coluna "Data" não encontrada na planilha');
    }

    // Preparar leads para análise (APENAS ÚLTIMOS 7 DIAS)
    const leads = [];
    let totalLeads = 0;
    let filteredLeads = 0;
    const firstDataRow = headerRow + 1;

    for (let i = firstDataRow; i < values.length; i++) {
      totalLeads++;
      const row = values[i];

      // Obter data do lead
      const leadDate = new Date(row[dataColumnIndex]);

      // Filtrar apenas últimos 7 dias
      if (leadDate >= sevenDaysAgo) {
        filteredLeads++;
        const leadData = {};

        headers.forEach((header, index) => {
          leadData[header] = row[index];
        });

        // Formato esperado pela API: {data: {...}}
        leads.push({
          data: leadData
        });
      }
    }

    Logger.log(`📋 Total de leads na planilha: ${totalLeads}`);
    Logger.log(`📋 Leads dos últimos 7 dias: ${filteredLeads}`);
    Logger.log(`📋 Enviando ${leads.length} leads para análise...`);

    if (leads.length === 0) {
      Logger.log('⚠️ Nenhum lead nos últimos 7 dias para análise');
      return;
    }

    // Chamar API de análise UTM
    const payload = JSON.stringify({
      leads: leads,
      account_id: META_ACCOUNT_ID
    });

    // Monitoramento: Logar tamanho do payload
    const payloadSizeMB = (payload.length / 1024 / 1024).toFixed(2);
    Logger.log(`📦 Tamanho do payload: ${payloadSizeMB} MB`);

    // Alerta se payload estiver muito grande
    if (payload.length / 1024 / 1024 > 25) {
      Logger.log(`⚠️ ATENÇÃO: Payload > 25 MB (${payloadSizeMB} MB). Próximo ao limite de 32 MB!`);
    }

    const options = {
      method: 'post',
      contentType: 'application/json',
      payload: payload,
      muteHttpExceptions: true
    };

    const response = UrlFetchApp.fetch(`${API_URL}/analyze_utms_with_costs`, options);
    const responseCode = response.getResponseCode();

    if (responseCode !== 200) {
      throw new Error(`API retornou erro: ${responseCode} - ${response.getContentText()}`);
    }

    const result = JSON.parse(response.getContentText());

    Logger.log(`✅ Análise recebida: ${result.processing_time_seconds}s`);
    Logger.log(`   Períodos: ${Object.keys(result.periods).join(', ')}`);

    // Criar abas para períodos 1D, 3D, 7D (sem Total)
    const periods = ['1D', '3D', '7D'];

    // IMPORTANTE: Processar cada aba separadamente com tratamento de erro individual
    // Se uma aba falhar, as outras ainda serão criadas
    for (const period of periods) {
      if (result.periods[period]) {
        try {
          Logger.log(`📝 Processando aba ${period}...`);
          escreverAbaAnalise(period, result.periods[period], result.config);
          Logger.log(`✅ Aba ${period} criada com sucesso`);
        } catch (periodError) {
          Logger.log(`❌ Erro ao criar aba ${period}: ${periodError.message}`);
          // Não throw - continuar processando outras abas
        }
      }
    }

    Logger.log('✅ Análises UTM atualizadas');

  } catch (error) {
    Logger.log(`❌ Erro ao atualizar análises UTM: ${error.message}`);
    throw error;
  }
}

/**
 * Atualiza aba "Info do Modelo" apenas se metadados mudaram
 */
function atualizarInfoModeloSeAlterado() {
  try {
    Logger.log('📊 Verificando atualização da Info do Modelo...');

    // Buscar metadados atuais da API
    const response = UrlFetchApp.fetch(`${API_URL}/model/info`, {
      method: 'get',
      muteHttpExceptions: true
    });

    if (response.getResponseCode() !== 200) {
      Logger.log('⚠️ Não foi possível obter informações do modelo');
      return;
    }

    const modelInfo = JSON.parse(response.getContentText());
    const currentModelName = modelInfo.model_info.model_name;
    const currentTrainedAt = modelInfo.model_info.trained_at;

    // Verificar se aba existe e tem metadados salvos
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let infoSheet = ss.getSheetByName('Info do Modelo');

    if (!infoSheet) {
      // Aba não existe, criar
      Logger.log('📋 Aba "Info do Modelo" não existe, criando...');
      escreverAbaInfoModelo(modelInfo);

      // Salvar metadados na aba (hidden row)
      infoSheet = ss.getSheetByName('Info do Modelo');
      infoSheet.getRange('Z1').setValue(currentModelName);
      infoSheet.getRange('Z2').setValue(currentTrainedAt);
      infoSheet.hideRows(1, 1);

      Logger.log('✅ Aba "Info do Modelo" criada');
      return;
    }

    // Verificar se metadados mudaram
    const savedModelName = infoSheet.getRange('Z1').getValue();
    const savedTrainedAt = infoSheet.getRange('Z2').getValue();

    if (savedModelName === currentModelName && savedTrainedAt === currentTrainedAt) {
      Logger.log('✅ Metadados do modelo não mudaram, aba não precisa atualização');
      return;
    }

    // Metadados mudaram, recriar aba
    Logger.log(`🔄 Metadados mudaram: ${savedModelName} → ${currentModelName}`);
    escreverAbaInfoModelo(modelInfo);

    // Atualizar metadados salvos
    infoSheet = ss.getSheetByName('Info do Modelo');
    infoSheet.getRange('Z1').setValue(currentModelName);
    infoSheet.getRange('Z2').setValue(currentTrainedAt);

    Logger.log('✅ Aba "Info do Modelo" atualizada');

  } catch (error) {
    Logger.log(`⚠️ Erro ao verificar Info do Modelo: ${error.message}`);
    // Não lançar erro, apenas logar
  }
}

// =============================================================================
// FUNÇÕES AUXILIARES: TRIGGERS
// =============================================================================

/**
 * Remove apenas triggers obsoletos da arquitetura antiga
 * Preserva: executeDailyReports (relatórios às 00:00)
 */
function removerGatilhosObsoletos() {
  const triggers = ScriptApp.getProjectTriggers();
  let removedCount = 0;

  for (const trigger of triggers) {
    const funcName = trigger.getHandlerFunction();

    // Remover APENAS triggers obsoletos (arquitetura antiga)
    if (funcName === 'executeDailyMLUpdate' ||
        funcName === 'execute3HourUpdate' ||
        funcName === 'execute1HourUpdate') {
      ScriptApp.deleteTrigger(trigger);
      removedCount++;
      Logger.log(`🗑️ Trigger obsoleto removido: ${funcName}`);
    }
  }

  if (removedCount > 0) {
    Logger.log(`✅ ${removedCount} trigger(s) obsoleto(s) removido(s)`);
  } else {
    Logger.log('✅ Nenhum trigger obsoleto encontrado');
  }
}

// =============================================================================
// FUNÇÕES AUXILIARES: VISUALIZAÇÃO
// =============================================================================

/**
 * Escreve aba de análise UTM para um período
 */
function escreverAbaAnalise(period, periodData, config) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetName = `Análise UTM - ${period}`;

  // Deletar aba se já existir (com tratamento robusto)
  try {
    let sheet = ss.getSheetByName(sheetName);
    if (sheet) {
      Logger.log(`🗑️ Deletando aba existente: ${sheetName}`);
      ss.deleteSheet(sheet);
      SpreadsheetApp.flush();  // Garantir que deleção foi aplicada
      Utilities.sleep(500);     // Pequeno delay para evitar conflito
    }
  } catch (deleteError) {
    Logger.log(`⚠️ Erro ao deletar aba ${sheetName}: ${deleteError.message}`);
    // Continuar mesmo se não conseguir deletar
  }

  // Criar nova aba
  const sheet = ss.insertSheet(sheetName);
  Logger.log(`📝 Criando aba: ${sheetName}`);

  // =============================================================================
  // SEÇÃO DE METADADOS DO PERÍODO
  // =============================================================================
  let headerRow = 1;

  // Linha 1: Período analisado
  if (periodData.period_start && periodData.period_end) {
    const periodStart = new Date(periodData.period_start);
    const periodEnd = new Date(periodData.period_end);

    // Formatar datas no formato brasileiro
    const formatDate = (date) => {
      const day = String(date.getDate()).padStart(2, '0');
      const month = String(date.getMonth() + 1).padStart(2, '0');
      const year = date.getFullYear();
      const hours = String(date.getHours()).padStart(2, '0');
      const minutes = String(date.getMinutes()).padStart(2, '0');
      return `${day}/${month}/${year} ${hours}:${minutes}`;
    };

    const periodCell = sheet.getRange(headerRow, 1, 1, 12);
    periodCell.merge();
    periodCell.setValue(`📅 Período: ${formatDate(periodStart)} até ${formatDate(periodEnd)}`);
    periodCell.setFontWeight('bold');
    periodCell.setFontSize(11);
    periodCell.setBackground('#E8F0FE');
    periodCell.setHorizontalAlignment('center');
    headerRow++;
  }

  // Linha 2: Contadores de leads
  if (periodData.total_leads !== undefined) {
    const metaLeads = periodData.meta_leads || 0;
    const googleLeads = periodData.google_leads || 0;
    const totalLeads = periodData.total_leads || 0;

    const countersCell = sheet.getRange(headerRow, 1, 1, 12);
    countersCell.merge();
    countersCell.setValue(`📊 Leads analisados: ${totalLeads} (Meta: ${metaLeads}, Google: ${googleLeads})`);
    countersCell.setFontWeight('bold');
    countersCell.setFontSize(10);
    countersCell.setBackground('#F1F3F4');
    countersCell.setHorizontalAlignment('center');
    headerRow++;
  }

  // Linha 3: Espaço em branco
  headerRow++;

  // =============================================================================
  // CABEÇALHOS DA TABELA
  // =============================================================================
  const headers = [
    'Campaign', 'Adset', 'Ad', 'Leads', 'Gasto (R$)', 'CPL (R$)',
    'Taxa Proj. (%)', 'Receita Proj. (R$)', 'Margem Contrib (R$)', 'ROAS Proj.',
    'Orç. Atual (R$)', 'Orç. Alvo (R$)', 'Ação'
  ];

  sheet.getRange(headerRow, 1, 1, headers.length).setValues([headers]);

  // Formatação do cabeçalho
  const headerRange = sheet.getRange(headerRow, 1, 1, headers.length);
  headerRange.setFontWeight('bold');
  headerRange.setBackground('#4285F4');
  headerRange.setFontColor('#FFFFFF');
  headerRange.setHorizontalAlignment('center');

  let currentRow = headerRow + 1;

  // =============================================================================
  // OTIMIZAÇÃO: Coletar todos os dados primeiro, depois escrever em LOTE
  // =============================================================================

  const allRowsData = [];        // Dados das células
  const rowBackgrounds = [];     // Cores de fundo por linha
  const acaoFormatting = [];     // Formatação especial da coluna Ação

  // Dimensões (ordem: campaign, medium, ad, google_ads)
  const dimensions = ['campaign', 'medium', 'ad', 'google_ads'];

  for (const dimension of dimensions) {
    const metrics = periodData[dimension];

    if (!metrics || metrics.length === 0) {
      continue;
    }

    // Adicionar título destacado para Google Ads
    if (dimension === 'google_ads' && metrics.length > 0) {
      // Linha vazia antes do título
      allRowsData.push(Array(13).fill(''));
      rowBackgrounds.push(Array(13).fill('#FFFFFF'));
      acaoFormatting.push(null);

      // Título Google Ads (será mesclado depois)
      allRowsData.push(['🔍 GOOGLE ADS (sem custos Meta - plataforma diferente)', ...Array(12).fill('')]);
      rowBackgrounds.push(Array(13).fill('#FFF3E0'));
      acaoFormatting.push(null);
    }

    for (const metric of metrics) {
      // Montar row baseado na dimensão
      let row;
      let backgroundColor;  // Cor de fundo por seção

      if (dimension === 'campaign') {
        row = [
          metric.value,           // Campaign
          '',                     // Adset (vazio)
          '',                     // Ad (vazio)
          metric.leads, metric.spend, metric.cpl,
          metric.taxa_proj * 100, metric.receita_proj, metric.margem_contrib, metric.roas_proj,
          metric.budget_current, metric.budget_target,
          metric.acao
        ];
        backgroundColor = '#E8F5E9';  // Verde claro para campaigns
      } else if (dimension === 'medium') {
        row = [
          metric.campaign || '',  // Campaign
          metric.value,           // Adset
          '',                     // Ad (vazio)
          metric.leads, metric.spend, metric.cpl,
          metric.taxa_proj * 100, metric.receita_proj, metric.margem_contrib, metric.roas_proj,
          metric.budget_current, metric.budget_target,
          metric.acao
        ];
        backgroundColor = '#FFF3E0';  // Laranja claro para adsets
      } else if (dimension === 'ad') {
        row = [
          metric.campaign || '',  // Campaign
          metric.adset || '',     // Adset
          metric.value,           // Ad
          metric.leads, metric.spend, metric.cpl,
          metric.taxa_proj * 100, metric.receita_proj, metric.margem_contrib, metric.roas_proj,
          metric.budget_current, metric.budget_target,
          metric.acao
        ];
        backgroundColor = '#E3F2FD';  // Azul claro para ads
      } else { // google_ads
        row = [
          '',                     // Campaign (vazio)
          '',                     // Adset (vazio)
          metric.value,           // Keyword
          metric.leads, metric.spend, metric.cpl,
          metric.taxa_proj * 100, metric.receita_proj, metric.margem_contrib, metric.roas_proj,
          metric.budget_current, metric.budget_target,
          metric.acao
        ];
        backgroundColor = '#F3E5F5';  // Roxo claro para Google Ads
      }

      allRowsData.push(row);
      rowBackgrounds.push(Array(13).fill(backgroundColor));

      // Determinar formatação da coluna Ação
      let acaoColor = null;
      if (metric.acao === 'ABO' || metric.acao === 'Manter' || metric.acao === 'CBO - Manter' || metric.acao.includes('Aguardar dados')) {
        acaoColor = { bg: '#E0E0E0', fg: '#666666' };  // Cinza neutro
      } else if (metric.acao === 'CBO - Pausar / Alterar' || metric.acao.includes('Pausar')) {
        acaoColor = { bg: '#EA4335', fg: '#FFFFFF' };  // Vermelho para pausar
      } else if (metric.acao.includes('Aumentar')) {
        const match = metric.acao.match(/Aumentar (\d+)/);
        if (match && parseInt(match[1]) > 30) {
          acaoColor = { bg: '#34A853', fg: '#FFFFFF' };
        } else {
          acaoColor = { bg: '#FBBC04', fg: '#000000' };
        }
      } else if (metric.acao.includes('Reduzir') || metric.acao === 'Remover') {
        acaoColor = { bg: '#EA4335', fg: '#FFFFFF' };
      } else {
        acaoColor = { bg: '#E0E0E0', fg: '#666666' };
      }
      acaoFormatting.push(acaoColor);
    }

    // Linha vazia de separação entre dimensões
    allRowsData.push(Array(13).fill(''));
    rowBackgrounds.push(Array(13).fill('#FFFFFF'));
    acaoFormatting.push(null);
  }

  // Escrever TODOS os dados de uma vez (MUITO mais rápido!)
  if (allRowsData.length > 0) {
    const dataRange = sheet.getRange(currentRow, 1, allRowsData.length, 13);
    dataRange.setValues(allRowsData);
    Logger.log(`✅ Escreveu ${allRowsData.length} linhas em lote`);

    SpreadsheetApp.flush();  // Forçar aplicação

    // Aplicar formatações em lote
    dataRange.setBackgrounds(rowBackgrounds);

    // Aplicar formatação especial da coluna Ação
    for (let i = 0; i < acaoFormatting.length; i++) {
      const fmt = acaoFormatting[i];
      if (fmt) {
        const acaoCell = sheet.getRange(currentRow + i, 13);
        acaoCell.setBackground(fmt.bg);
        acaoCell.setFontColor(fmt.fg);
        acaoCell.setFontWeight('bold');
      }
    }

    currentRow += allRowsData.length;
    SpreadsheetApp.flush();  // Forçar aplicação de formatação
  }

  // Formatar colunas numéricas EM LOTE (muito mais rápido!)
  const lastRow = currentRow - 1;
  const firstDataRow = headerRow + 1;
  if (lastRow >= firstDataRow) {
    const numDataRows = lastRow - firstDataRow + 1;

    // Formato moeda: Gasto, CPL, Receita Proj, Margem Contrib, Orç. Atual, Orç. Alvo
    sheet.getRange(firstDataRow, 5, numDataRows, 1).setNumberFormat('R$ #,##0.00');  // Gasto
    sheet.getRange(firstDataRow, 6, numDataRows, 1).setNumberFormat('R$ #,##0.00');  // CPL
    sheet.getRange(firstDataRow, 8, numDataRows, 1).setNumberFormat('R$ #,##0.00');  // Receita Proj
    sheet.getRange(firstDataRow, 9, numDataRows, 1).setNumberFormat('R$ #,##0.00');  // Margem Contrib
    sheet.getRange(firstDataRow, 11, numDataRows, 1).setNumberFormat('R$ #,##0.00'); // Orç. Atual
    sheet.getRange(firstDataRow, 12, numDataRows, 1).setNumberFormat('R$ #,##0.00'); // Orç. Alvo

    // Percentual: Taxa Proj
    sheet.getRange(firstDataRow, 7, numDataRows, 1).setNumberFormat('0.00"%"');  // Taxa Proj

    // ROAS
    sheet.getRange(firstDataRow, 10, numDataRows, 1).setNumberFormat('0.00"x"');  // ROAS Proj

    SpreadsheetApp.flush();  // Forçar aplicação dos formatos numéricos

    // Destacar Margem Contrib (coluna 9) com cores - EM LOTE
    const margemValues = sheet.getRange(firstDataRow, 9, numDataRows, 1).getValues();
    const margemBackgrounds = [];
    const margemFontWeights = [];

    for (let i = 0; i < margemValues.length; i++) {
      const margemValue = margemValues[i][0];
      if (margemValue > 0) {
        margemBackgrounds.push(['#D4EDDA']);  // Verde claro (lucrativa)
        margemFontWeights.push(['bold']);
      } else if (margemValue < 0) {
        margemBackgrounds.push(['#F8D7DA']);  // Vermelho claro (prejuízo)
        margemFontWeights.push(['bold']);
      } else {
        margemBackgrounds.push(['#FFFFFF']);  // Branco (neutro)
        margemFontWeights.push(['normal']);
      }
    }

    sheet.getRange(firstDataRow, 9, numDataRows, 1).setBackgrounds(margemBackgrounds);
    sheet.getRange(firstDataRow, 9, numDataRows, 1).setFontWeights(margemFontWeights);

    SpreadsheetApp.flush();  // Forçar aplicação da formatação de margem
  }

  // Ajustar largura das colunas
  for (let i = 1; i <= headers.length; i++) {
    sheet.autoResizeColumn(i);
  }

  // Adicionar nota com configuração
  sheet.getRange(lastRow + 2, 1).setValue(`Configuração: Product Value = R$ ${config.product_value.toFixed(2)} | ROAS Mínimo de Segurança = 2.5x | CAP Variação Máxima = 80%`);
  sheet.getRange(lastRow + 2, 1).setFontStyle('italic');
  sheet.getRange(lastRow + 2, 1).setFontColor('#666666');

  Logger.log(`✅ Aba ${sheetName} criada com ${lastRow - 1} registros`);
}

/**
 * Escreve aba "Info do Modelo" com metadados e feature importances
 */
function escreverAbaInfoModelo(modelInfo) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetName = 'Info do Modelo';

  // Deletar aba se já existir
  let sheet = ss.getSheetByName(sheetName);
  if (sheet) {
    ss.deleteSheet(sheet);
  }

  // Criar nova aba
  sheet = ss.insertSheet(sheetName);

  Logger.log('📊 Criando aba: Info do Modelo');

  let currentRow = 1;

  // === SEÇÃO 1: INFORMAÇÕES DO MODELO ===
  sheet.getRange(currentRow, 1).setValue('📋 INFORMAÇÕES DO MODELO');
  sheet.getRange(currentRow, 1).setFontWeight('bold');
  sheet.getRange(currentRow, 1).setFontSize(14);
  sheet.getRange(currentRow, 1).setBackground('#4285F4');
  sheet.getRange(currentRow, 1).setFontColor('#FFFFFF');
  currentRow += 2;

  const modelInfo_data = modelInfo.model_info || {};
  const infoRows = [
    ['Nome do Modelo:', modelInfo_data.model_name || 'N/A'],
    ['Tipo:', modelInfo_data.model_type || 'N/A'],
    ['Biblioteca:', `${modelInfo_data.library || 'N/A'} ${modelInfo_data.library_version || ''}`],
    ['Data de Treinamento:', modelInfo_data.trained_at ? new Date(modelInfo_data.trained_at).toLocaleString('pt-BR') : 'N/A'],
    ['Split:', modelInfo_data.split_type || 'N/A']
  ];

  for (const [label, value] of infoRows) {
    sheet.getRange(currentRow, 1).setValue(label);
    sheet.getRange(currentRow, 1).setFontWeight('bold');
    sheet.getRange(currentRow, 2).setValue(value);
    currentRow++;
  }

  currentRow += 2;

  // === SEÇÃO 2: DADOS DE TREINAMENTO ===
  sheet.getRange(currentRow, 1).setValue('📊 DADOS DE TREINAMENTO');
  sheet.getRange(currentRow, 1).setFontWeight('bold');
  sheet.getRange(currentRow, 1).setFontSize(14);
  sheet.getRange(currentRow, 1).setBackground('#34A853');
  sheet.getRange(currentRow, 1).setFontColor('#FFFFFF');
  currentRow += 2;

  const trainingData = modelInfo.training_data || {};
  const temporalSplit = trainingData.temporal_split || {};
  const targetDist = trainingData.target_distribution || {};

  const trainingRows = [
    ['Total de Registros:', trainingData.total_records || 'N/A'],
    ['Registros de Treino:', trainingData.training_records || 'N/A'],
    ['Registros de Teste:', trainingData.test_records || 'N/A'],
    ['Número de Features:', trainingData.features_count || 'N/A'],
    ['Período:', `${temporalSplit.period_start || 'N/A'} a ${temporalSplit.period_end || 'N/A'}`],
    ['Data de Corte:', temporalSplit.cut_date || 'N/A'],
    ['Taxa de Conversão (Treino):', targetDist.training_positive_rate ? (targetDist.training_positive_rate * 100).toFixed(2) + '%' : 'N/A'],
    ['Taxa de Conversão (Teste):', targetDist.test_positive_rate ? (targetDist.test_positive_rate * 100).toFixed(2) + '%' : 'N/A']
  ];

  for (const [label, value] of trainingRows) {
    sheet.getRange(currentRow, 1).setValue(label);
    sheet.getRange(currentRow, 1).setFontWeight('bold');
    sheet.getRange(currentRow, 2).setValue(value);
    currentRow++;
  }

  currentRow += 2;

  // === SEÇÃO 3: MÉTRICAS DE PERFORMANCE ===
  sheet.getRange(currentRow, 1).setValue('🎯 MÉTRICAS DE PERFORMANCE');
  sheet.getRange(currentRow, 1).setFontWeight('bold');
  sheet.getRange(currentRow, 1).setFontSize(14);
  sheet.getRange(currentRow, 1).setBackground('#FBBC04');
  sheet.getRange(currentRow, 1).setFontColor('#000000');
  currentRow += 2;

  const performance = modelInfo.performance_metrics || {};
  const perfRows = [
    ['AUC:', performance.auc ? performance.auc.toFixed(4) : 'N/A'],
    ['Lift Máximo:', performance.lift_maximum ? performance.lift_maximum.toFixed(2) + 'x' : 'N/A'],
    ['Concentração Top 3 Decis:', performance.top3_decil_concentration ? performance.top3_decil_concentration.toFixed(2) + '%' : 'N/A'],
    ['Concentração Top 5 Decis:', performance.top5_decil_concentration ? performance.top5_decil_concentration.toFixed(2) + '%' : 'N/A'],
    ['Monotonia:', performance.monotonia_percentage ? performance.monotonia_percentage.toFixed(1) + '%' : 'N/A']
  ];

  for (const [label, value] of perfRows) {
    sheet.getRange(currentRow, 1).setValue(label);
    sheet.getRange(currentRow, 1).setFontWeight('bold');
    sheet.getRange(currentRow, 2).setValue(value);
    currentRow++;
  }

  currentRow += 2;

  // === SEÇÃO 4: ANÁLISE POR DECIL ===
  sheet.getRange(currentRow, 1).setValue('📈 ANÁLISE POR DECIL');
  sheet.getRange(currentRow, 1).setFontWeight('bold');
  sheet.getRange(currentRow, 1).setFontSize(14);
  sheet.getRange(currentRow, 1).setBackground('#EA4335');
  sheet.getRange(currentRow, 1).setFontColor('#FFFFFF');
  currentRow += 2;

  const decilHeaders = ['Decil', 'Leads', 'Conversões', 'Taxa Conv.', '% Total Conv.', 'Lift'];
  sheet.getRange(currentRow, 1, 1, decilHeaders.length).setValues([decilHeaders]);
  sheet.getRange(currentRow, 1, 1, decilHeaders.length).setFontWeight('bold');
  sheet.getRange(currentRow, 1, 1, decilHeaders.length).setBackground('#666666');
  sheet.getRange(currentRow, 1, 1, decilHeaders.length).setFontColor('#FFFFFF');
  currentRow++;

  const decilAnalysis = modelInfo.decil_analysis || {};
  for (let i = 1; i <= 10; i++) {
    const decilKey = `decil_${i}`;
    const decilData = decilAnalysis[decilKey] || {};

    const row = [
      `D${i}`,
      decilData.total_leads || 0,
      decilData.conversions || 0,
      decilData.conversion_rate ? (decilData.conversion_rate * 100).toFixed(2) + '%' : '0.00%',
      decilData.pct_total_conversions ? decilData.pct_total_conversions.toFixed(2) + '%' : '0.00%',
      decilData.lift ? decilData.lift.toFixed(2) + 'x' : '0.00x'
    ];

    sheet.getRange(currentRow, 1, 1, row.length).setValues([row]);
    currentRow++;
  }

  currentRow += 2;

  // === SEÇÃO 5: FEATURE IMPORTANCES ===
  sheet.getRange(currentRow, 1).setValue('🔍 IMPORTÂNCIA DAS FEATURES');
  sheet.getRange(currentRow, 1).setFontWeight('bold');
  sheet.getRange(currentRow, 1).setFontSize(14);
  sheet.getRange(currentRow, 1).setBackground('#9C27B0');
  sheet.getRange(currentRow, 1).setFontColor('#FFFFFF');
  currentRow += 2;

  const featureHeaders = ['Rank', 'Feature', 'Importância'];
  sheet.getRange(currentRow, 1, 1, featureHeaders.length).setValues([featureHeaders]);
  sheet.getRange(currentRow, 1, 1, featureHeaders.length).setFontWeight('bold');
  sheet.getRange(currentRow, 1, 1, featureHeaders.length).setBackground('#666666');
  sheet.getRange(currentRow, 1, 1, featureHeaders.length).setFontColor('#FFFFFF');
  currentRow++;

  const featureImportances = modelInfo.feature_importances || [];
  for (let i = 0; i < featureImportances.length; i++) {
    const feature = featureImportances[i];
    const row = [
      i + 1,
      feature.feature || 'N/A',
      feature.importance ? (feature.importance * 100).toFixed(2) + '%' : '0.00%'
    ];

    sheet.getRange(currentRow, 1, 1, row.length).setValues([row]);
    currentRow++;
  }

  // Ajustar largura das colunas
  for (let i = 1; i <= 6; i++) {
    sheet.autoResizeColumn(i);
  }

  Logger.log('✅ Aba "Info do Modelo" criada com sucesso');
}

// =============================================================================
// POLLING: PROCESSAMENTO A CADA 5 MINUTOS
// =============================================================================

/**
 * Polling executado a cada 5 minutos
 * Verifica leads sem score desde a última execução e processa
 *
 * Usa lock para evitar execuções simultâneas
 */
function executarPolling5Min() {
  // Obter lock para evitar execuções simultâneas
  const lock = LockService.getScriptLock();

  // Tentar obter lock por 10 segundos, se não conseguir, sair
  const hasLock = lock.tryLock(10000);
  if (!hasLock) {
    Logger.log('⚠️ Polling já em execução, ignorando');
    return;
  }

  try {
    Logger.log('🔄 Polling 5min - ' + new Date().toISOString());

    // Buscar leads pendentes (sem score, após o último processado)
    const pendingLeads = buscarLeadsPendentes();

    if (pendingLeads.leads.length === 0) {
      Logger.log('✅ Nenhum lead pendente');
      return;
    }

    Logger.log(`📊 ${pendingLeads.leads.length} leads pendentes encontrados`);

    // Etapa 1: Gerar predições para leads pendentes
    Logger.log('🔮 Gerando predições...');
    gerarPredicoesLeadsPendentes(pendingLeads.leads);

    // Etapa 2: Enviar CAPI para leads processados
    Logger.log('📤 Enviando batch CAPI...');
    enviarLoteCapiLeadsPendentes(pendingLeads.leads);

    Logger.log('✅ Polling 5min concluído com sucesso');

  } catch (error) {
    Logger.log(`❌ Erro no polling 5min: ${error.message}`);
    Logger.log(error.stack);
  } finally {
    // Sempre liberar o lock
    lock.releaseLock();
  }
}

/**
 * Cria triggers de polling (5min) e relatórios diários (00:00)
 * Deve ser executado manualmente uma vez
 */
function agendarGatilho5Min() {
  // Remover triggers existentes (antigos e novos)
  const triggers = ScriptApp.getProjectTriggers();
  for (const trigger of triggers) {
    const funcName = trigger.getHandlerFunction();
    // Remover triggers antigos E novos (para recriar)
    if (funcName === 'executarPolling5Min' ||
        funcName === 'executePolling5Min' ||
        funcName === 'executarRelatoriosDiarios' ||
        funcName === 'executeDailyReports' ||
        funcName === 'executarMonitoramentoDiario' ||
        funcName === 'execute1HourUpdate' ||
        funcName === 'executeDailyMLUpdate' ||
        funcName === 'execute3HourUpdate' ||
        funcName === 'onSheetChange' ||
        funcName === 'onFormSubmit') {
      ScriptApp.deleteTrigger(trigger);
      Logger.log(`🗑️ Trigger ${funcName} removido`);
    }
  }

  // 1️⃣ Criar trigger de polling a cada 5 minutos
  ScriptApp.newTrigger('executarPolling5Min')
    .timeBased()
    .everyMinutes(5)
    .create();

  Logger.log('✅ Trigger polling 5min criado: executarPolling5Min()');

  // 2️⃣ Criar trigger diário às 00:00 para relatórios
  ScriptApp.newTrigger('executarRelatoriosDiarios')
    .timeBased()
    .atHour(0)
    .everyDays(1)
    .create();

  Logger.log('✅ Trigger diário criado: executarRelatoriosDiarios() às 00:00');

  // 3️⃣ Criar triggers de monitoramento 2x por dia (01:00 e 13:00)
  ScriptApp.newTrigger('executarMonitoramentoDiario')
    .timeBased()
    .atHour(1)
    .everyDays(1)
    .create();

  ScriptApp.newTrigger('executarMonitoramentoDiario')
    .timeBased()
    .atHour(13)
    .everyDays(1)
    .create();

  Logger.log('✅ Triggers monitoramento criados: executarMonitoramentoDiario() às 01:00 e 13:00');

  SpreadsheetApp.getUi().alert(
    'Gatilhos Ativados',
    'Sistema configurado com sucesso!\n\n' +
    '✅ Polling 5min: executarPolling5Min()\n' +
    '   → Verifica leads sem score\n' +
    '   → Gera predições ML\n' +
    '   → Envia eventos CAPI\n\n' +
    '✅ Relatórios Diários: executarRelatoriosDiarios()\n' +
    '   → Executa às 00:00\n' +
    '   → Atualiza análises UTM (1D, 3D, 7D)\n' +
    '   → Atualiza Info do Modelo\n\n' +
    '✅ Monitoramento 12h: executarMonitoramentoDiario()\n' +
    '   → Executa às 01:00 e 13:00\n' +
    '   → Verifica drift de categorias e distribuições\n' +
    '   → Monitora qualidade de dados CAPI\n' +
    '   → Detecta problemas operacionais\n' +
    '   → Envia sumário para Slack',
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}

// =============================================================================
// MONITORAMENTO DIÁRIO DE QUALIDADE E DRIFT
// =============================================================================

/**
 * Executa check diário de monitoramento:
 * - Category drift (novas categorias não vistas no treino)
 * - Distribution drift (mudanças nas proporções)
 * - Missing rate (colunas com muitos valores vazios)
 * - Score distribution (mudanças nos decis)
 * - Problemas operacionais (sem leads, sem CAPI)
 * - Qualidade CAPI (missing fbp/fbc)
 *
 * Executado automaticamente às 01:00 via trigger.
 */
function executarMonitoramentoDiario() {
  Logger.log('🔍 Iniciando monitoramento diário...');

  try {
    // 1. Buscar dados das últimas 24h do Sheets
    const leadsData = buscarLeadsUltimas24h();

    if (!leadsData || leadsData.length === 0) {
      Logger.log('⚠️ Nenhum lead encontrado nas últimas 24h');
      return;
    }

    Logger.log(`📊 Enviando ${leadsData.length} leads para análise...`);

    // 2. Chamar endpoint de monitoramento
    const response = UrlFetchApp.fetch(`${API_URL}/monitoring/daily-check`, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({ leads: leadsData }),
      muteHttpExceptions: true
    });

    const statusCode = response.getResponseCode();
    const result = JSON.parse(response.getContentText());

    if (statusCode !== 200) {
      Logger.log(`❌ Erro no monitoramento: ${statusCode}`);
      Logger.log(response.getContentText());
      return;
    }

    // 3. Processar resultados
    Logger.log(`\n📊 RESULTADOS DO MONITORAMENTO:`);
    Logger.log(`   Total de alertas: ${result.total_alerts}`);
    Logger.log(`   Por severidade: HIGH=${result.alerts_by_severity.HIGH}, MEDIUM=${result.alerts_by_severity.MEDIUM}, LOW=${result.alerts_by_severity.LOW}`);
    Logger.log(`   Por categoria: DATA=${result.alerts_by_category.data_quality}, OPS=${result.alerts_by_category.operational}, CAPI=${result.alerts_by_category.capi_quality}`);

    if (result.total_alerts > 0) {
      Logger.log(`\n🚨 ALERTAS DETECTADOS (${result.total_alerts}):`);

      // Mostrar os 10 primeiros alertas no log
      const maxAlertsToLog = Math.min(10, result.alerts.length);
      for (let i = 0; i < maxAlertsToLog; i++) {
        const alert = result.alerts[i];
        Logger.log(`\n${i + 1}. [${alert.severity}] ${alert.type}`);
        Logger.log(`   ${alert.message}`);
        if (alert.metric_value) {
          Logger.log(`   Valor: ${alert.metric_value}${alert.threshold ? ` (threshold: ${alert.threshold})` : ''}`);
        }
      }

      if (result.total_alerts > maxAlertsToLog) {
        Logger.log(`\n   ... e mais ${result.total_alerts - maxAlertsToLog} alertas`);
      }
    } else {
      Logger.log('\n✅ Nenhum alerta detectado - sistema operando normalmente');
    }

    // 4. Enviar sumário crítico para Slack
    Logger.log(`\n🔍 DEBUG: critical_summary existe? ${!!result.critical_summary}`);
    Logger.log(`🔍 DEBUG: Tamanho do summary: ${result.critical_summary ? result.critical_summary.length : 0} chars`);

    if (result.critical_summary) {
      Logger.log('📤 Tentando enviar sumário para Slack...');
      enviarSumarioParaSlack(result.critical_summary, result.total_alerts);
      Logger.log('✅ Sumário enviado para Slack');
    } else {
      Logger.log('⚠️ critical_summary não encontrado na resposta da API');
    }

    Logger.log('\n✅ Monitoramento concluído com sucesso!');

  } catch (error) {
    Logger.log(`❌ Erro no monitoramento diário: ${error.message}`);
    Logger.log(error.stack);
  }
}

/**
 * Envia sumário crítico de monitoramento para Slack
 */
function enviarSumarioParaSlack(summaryText, totalAlerts) {
  try {
    Logger.log(`\n🔍 DEBUG enviarSumarioParaSlack:`);
    Logger.log(`   - summaryText recebido: ${summaryText ? 'SIM' : 'NÃO'}`);
    Logger.log(`   - totalAlerts: ${totalAlerts}`);
    Logger.log(`   - SLACK_WEBHOOK_URL: ${SLACK_WEBHOOK_URL ? 'CONFIGURADO' : 'NÃO CONFIGURADO'}`);

    // Determinar cor do alerta baseado na quantidade
    let color = '#36a64f'; // Verde
    if (totalAlerts > 0) {
      color = '#ff0000'; // Vermelho
    }

    // Formatar mensagem para Slack
    const payload = {
      text: '🔍 *Relatório de Monitoramento Smart Ads*',
      attachments: [{
        color: color,
        text: '```\n' + summaryText + '\n```',
        footer: 'Smart Ads Monitoring System',
        footer_icon: 'https://platform.slack-edge.com/img/default_application_icon.png',
        ts: Math.floor(Date.now() / 1000)
      }]
    };

    Logger.log(`🔍 DEBUG: Payload criado com ${JSON.stringify(payload).length} chars`);

    // Enviar para Slack
    const options = {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    Logger.log('📤 Chamando UrlFetchApp.fetch...');
    const response = UrlFetchApp.fetch(SLACK_WEBHOOK_URL, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    Logger.log(`📥 Resposta do Slack: ${responseCode}`);
    Logger.log(`📥 Body: ${responseText}`);

    if (responseCode !== 200) {
      Logger.log(`⚠️ Erro ao enviar para Slack: ${responseCode}`);
      Logger.log(responseText);
    } else {
      Logger.log('✅ Slack retornou 200 OK');
    }

  } catch (error) {
    Logger.log(`❌ Erro ao enviar para Slack: ${error.message}`);
    Logger.log(`❌ Stack: ${error.stack}`);
  }
}

/**
 * Busca leads das últimas 24 horas da aba [LF] Pesquisa
 * Retorna array de objetos com todos os campos
 */
function buscarLeadsUltimas24h() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('[LF] Pesquisa');
  if (!sheet) {
    throw new Error('Aba "[LF] Pesquisa" não encontrada');
  }

  const values = sheet.getDataRange().getValues();
  if (values.length <= 1) {
    return [];
  }

  // Buscar cabeçalho dinamicamente
  const { headerRow, headers } = encontrarLinhaDosCabecalhos(values);
  const dataColIndex = headers.indexOf('Data');

  if (dataColIndex === -1) {
    throw new Error('Coluna "Data" não encontrada');
  }

  // Calcular threshold de 24h atrás
  const now = new Date();
  const threshold24h = new Date(now.getTime() - (24 * 60 * 60 * 1000));

  const recentLeads = [];
  const firstDataRow = headerRow + 1;

  for (let i = firstDataRow; i < values.length; i++) {
    const row = values[i];

    // Ignorar cabeçalhos duplicados
    if (row[dataColIndex] === 'Data' && row[headers.indexOf('E-mail')] === 'E-mail') {
      continue;
    }

    const leadDate = new Date(row[dataColIndex]);

    // Incluir apenas leads das últimas 24h
    if (leadDate >= threshold24h) {
      const leadObj = {};
      for (let j = 0; j < headers.length; j++) {
        // Usar nome exato da coluna do Sheets
        leadObj[headers[j]] = row[j];
      }
      recentLeads.push(leadObj);
    }
  }

  return recentLeads;
}

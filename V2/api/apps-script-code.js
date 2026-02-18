/**
 * ========================================
 * SMART ADS - LEAD SCORING ML AUTOMATION
 * ========================================
 *
 * Sistema automatizado de predições ML e envio de eventos CAPI
 * - Polling 5min: Predições ML + CAPI
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
 */
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('Smart Ads')
    .addItem('Ativar Polling 5min', 'agendarGatilho5Min')
    .addSeparator()
    .addItem('Reprocessar leads sem score', 'reprocessarLeadsSemScore')
    .addSeparator()
    .addItem('Testar Monitoramento', 'executarMonitoramentoDiario')
    .addToUi();
}

// =============================================================================
// FUNÇÕES PRINCIPAIS
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

  for (let i = 0; i < values.length; i++) {
    const row = values[i];
    if (row.some(cell => cell === 'Data') && row.some(cell => cell === 'E-mail')) {
      Logger.log(`✅ Cabeçalho encontrado na linha ${i + 1}`);
      return { headerRow: i, headers: row };
    }
  }

  throw new Error('Cabeçalho não encontrado. Procurando por colunas "Data" e "E-mail"');
}

/**
 * Coleta leads sem score a partir de uma posição inicial na planilha
 * Compartilhado por buscarLeadsPendentes (a partir do último scored) e
 * reprocessarLeadsSemScore (desde o início)
 */
function _lerLeadsSemScore(values, headers, startRow) {
  const dataColIndex  = headers.indexOf('Data');
  const emailColIndex = headers.indexOf('E-mail');
  const scoreColIndex = headers.indexOf('lead_score');
  const leads = [];
  let skippedCount = 0;

  for (let i = startRow; i < values.length; i++) {
    const row = values[i];
    if (row[dataColIndex] === 'Data' && row[emailColIndex] === 'E-mail') continue;
    if (scoreColIndex !== -1 && row[scoreColIndex]) continue;

    const email = row[emailColIndex] ? String(row[emailColIndex]).trim() : null;
    if (!email) { skippedCount++; continue; }

    const leadData = {};
    headers.forEach((header, index) => { leadData[header] = row[index]; });
    leads.push({ data: leadData, email, row_id: (i + 1).toString() });
  }

  if (skippedCount > 0) Logger.log(`⚠️ ${skippedCount} linhas ignoradas (sem email)`);
  return leads;
}

/**
 * Busca leads pendentes de processamento (sem score, após a última POSIÇÃO com score)
 * Usa posição na planilha como âncora — imune a diferenças de fuso horário (UTC vs BRT)
 * Retorna: { leads: [...] }
 */
function buscarLeadsPendentes() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('[LF] Pesquisa');
  if (!sheet) throw new Error('Aba "[LF] Pesquisa" não encontrada');

  const values = sheet.getDataRange().getValues();
  if (values.length <= 1) return { leads: [] };

  const { headerRow, headers } = encontrarLinhaDosCabecalhos(values);
  const dataColIndex  = headers.indexOf('Data');
  const emailColIndex = headers.indexOf('E-mail');
  const scoreColIndex = headers.indexOf('lead_score');
  const firstDataRow  = headerRow + 1;

  // Encontrar a ÚLTIMA POSIÇÃO (linha) com score
  // Não compara timestamps — usa posição física na planilha
  // Resolve o bug de fuso horário: leads UTC e BRT são intercalados
  // na planilha, mas a posição é absoluta e não depende do timestamp
  let lastScoredRowIndex = -1;
  for (let i = firstDataRow; i < values.length; i++) {
    const row = values[i];
    if (row[dataColIndex] === 'Data' && row[emailColIndex] === 'E-mail') continue;
    if (scoreColIndex !== -1 && row[scoreColIndex]) lastScoredRowIndex = i;
  }

  if (lastScoredRowIndex !== -1) {
    Logger.log(`✅ Última linha com score: ${lastScoredRowIndex + 1} (${values[lastScoredRowIndex][dataColIndex]})`);
  } else {
    Logger.log('⚠️ Nenhum lead com score (primeira execução)');
  }

  const startRow = lastScoredRowIndex === -1 ? firstDataRow : lastScoredRowIndex + 1;
  const leads = _lerLeadsSemScore(values, headers, startRow);
  Logger.log(`✅ ${leads.length} leads pendentes encontrados`);
  return { leads };
}

/**
 * Gera predições ML e envia eventos CAPI para uma lista de leads
 * Pipeline: /predict/batch → escrever scores na planilha → /capi/process_daily_batch
 */
function processarLeads(leads) {
  if (leads.length === 0) {
    Logger.log('✅ Nenhum lead para processar');
    return;
  }

  Logger.log(`📊 Processando ${leads.length} leads`);

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('[LF] Pesquisa');
  const values = sheet.getDataRange().getValues();
  const { headerRow, headers } = encontrarLinhaDosCabecalhos(values);
  const scoreColIndex = headers.indexOf('lead_score');
  const decilColIndex = headers.indexOf('decil');

  // ── ETAPA 1: Gerar predições ──────────────────────────────────────────
  const MAX_BATCH_SIZE = 600;
  let allPredictions = [];
  const batches = [];
  for (let i = 0; i < leads.length; i += MAX_BATCH_SIZE) {
    batches.push(leads.slice(i, i + MAX_BATCH_SIZE));
  }

  Logger.log(`📦 ${batches.length} lote(s) para predição`);

  for (let batchIndex = 0; batchIndex < batches.length; batchIndex++) {
    const batch = batches[batchIndex];
    Logger.log(`📤 Lote predição ${batchIndex + 1}/${batches.length} (${batch.length} leads)`);

    const response = UrlFetchApp.fetch(`${API_URL}/predict/batch`, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({ leads: batch }),
      muteHttpExceptions: true
    });

    if (response.getResponseCode() !== 200) {
      throw new Error(`API retornou erro ${response.getResponseCode()}: ${response.getContentText()}`);
    }

    const result = JSON.parse(response.getContentText());
    allPredictions = allPredictions.concat(result.predictions);
    Logger.log(`✅ Lote ${batchIndex + 1}: ${result.predictions.length} predições`);

    if (batchIndex < batches.length - 1) Utilities.sleep(1000);
  }

  // ── ETAPA 2: Escrever scores na planilha ─────────────────────────────
  Logger.log(`💾 Escrevendo ${allPredictions.length} scores...`);

  if (scoreColIndex === -1) {
    sheet.getRange(headerRow + 1, headers.length + 1).setValue('lead_score');
  }
  const scoreCol = scoreColIndex !== -1 ? scoreColIndex + 1 : headers.length + 1;
  const decilCol = decilColIndex !== -1 ? decilColIndex + 1 : scoreCol + 1;
  if (decilColIndex === -1) {
    sheet.getRange(headerRow + 1, decilCol).setValue('decil');
  }

  if (allPredictions.length > 0) {
    allPredictions.sort((a, b) => parseInt(a.row_id) - parseInt(b.row_id));
    const minRow = parseInt(allPredictions[0].row_id);
    const maxRow = parseInt(allPredictions[allPredictions.length - 1].row_id);
    const numRows = maxRow - minRow + 1;
    const existingValues = sheet.getRange(minRow, scoreCol, numRows, 2).getValues();
    for (const pred of allPredictions) {
      const rowOffset = parseInt(pred.row_id) - minRow;
      existingValues[rowOffset][0] = pred.lead_score;
      existingValues[rowOffset][1] = pred.decil;
    }
    sheet.getRange(minRow, scoreCol, numRows, 2).setValues(existingValues);
    SpreadsheetApp.flush();
  }

  Logger.log('✅ Scores escritos');

  // ── ETAPA 3: Enviar CAPI ──────────────────────────────────────────────
  // Usar allPredictions + leads originais — sem re-ler o Sheets
  const leadByRowId = {};
  for (const lead of leads) leadByRowId[lead.row_id] = lead;

  const leadsWithScores = [];
  for (const pred of allPredictions) {
    if (!pred.lead_score) continue;
    const lead = leadByRowId[pred.row_id];
    if (!lead) continue;

    const leadData = {
      email: lead.email,
      phone: lead.data['Telefone'] || '',
      lead_score: pred.lead_score,
      data: Utilities.formatDate(new Date(lead.data['Data']), Session.getScriptTimeZone(), "yyyy-MM-dd'T'HH:mm:ss")
    };

    for (const [key, value] of Object.entries(lead.data)) {
      if (key !== 'email' && key !== 'phone' && key !== 'lead_score' && key !== 'decil' && key !== 'data') {
        leadData[key] = value;
      }
    }

    leadsWithScores.push(leadData);
  }

  if (leadsWithScores.length === 0) {
    Logger.log('⚠️ Nenhum lead com score para CAPI');
    return;
  }

  const CAPI_BATCH_SIZE = 500;
  const capiBatches = [];
  for (let i = 0; i < leadsWithScores.length; i += CAPI_BATCH_SIZE) {
    capiBatches.push(leadsWithScores.slice(i, i + CAPI_BATCH_SIZE));
  }

  Logger.log(`📦 ${capiBatches.length} lote(s) CAPI`);
  let totalSuccess = 0, totalFailed = 0, totalWithCapi = 0;

  for (let batchIndex = 0; batchIndex < capiBatches.length; batchIndex++) {
    const batch = capiBatches[batchIndex];
    Logger.log(`📤 Lote CAPI ${batchIndex + 1}/${capiBatches.length} (${batch.length} leads)`);

    const response = UrlFetchApp.fetch(`${API_URL}/capi/process_daily_batch`, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({ leads: batch }),
      muteHttpExceptions: true
    });

    const responseCode = response.getResponseCode();
    if (responseCode === 200) {
      const result = JSON.parse(response.getContentText());
      totalSuccess  += result.success || 0;
      totalFailed   += (result.total || 0) - (result.success || 0);
      totalWithCapi += result.leads_with_capi_data || 0;
      Logger.log(`✅ Lote ${batchIndex + 1}: ${result.success}/${result.total} enviados`);
    } else {
      Logger.log(`❌ Erro lote CAPI ${batchIndex + 1}: ${responseCode} - ${response.getContentText()}`);
    }

    if (batchIndex < capiBatches.length - 1) Utilities.sleep(1000);
  }

  Logger.log(`✅ CAPI concluído: ${totalSuccess} enviados, ${totalFailed} falhas, ${totalWithCapi} com dados CAPI`);
}

// =============================================================================
// POLLING: PROCESSAMENTO A CADA 5 MINUTOS
// =============================================================================

/**
 * Polling executado a cada 5 minutos
 * Verifica leads sem score desde a última execução e processa
 * Usa lock para evitar execuções simultâneas
 */
function executarPolling5Min() {
  const lock = LockService.getScriptLock();
  const hasLock = lock.tryLock(10000);
  if (!hasLock) {
    Logger.log('⚠️ Polling já em execução, ignorando');
    return;
  }

  try {
    Logger.log('🔄 Polling 5min - ' + new Date().toISOString());

    const { leads } = buscarLeadsPendentes();

    if (leads.length === 0) {
      Logger.log('✅ Nenhum lead pendente');
      return;
    }

    Logger.log(`📊 ${leads.length} leads pendentes encontrados`);
    processarLeads(leads);

    Logger.log('✅ Polling 5min concluído com sucesso');

  } catch (error) {
    Logger.log(`❌ Erro no polling 5min: ${error.message}`);
    Logger.log(error.stack);
  } finally {
    lock.releaseLock();
  }
}

/**
 * Reprocessa leads sem score na planilha, independente de posição.
 * Processa até 500 leads por execução (limite de 6min do Apps Script).
 * Execute novamente até zerar os pendentes — cada run pula automaticamente
 * os leads que já ganharam score na execução anterior.
 * Executar pelo menu: Smart Ads → Reprocessar leads sem score
 */
function reprocessarLeadsSemScore() {
  const CHUNK_SIZE = 500;

  const ui = SpreadsheetApp.getUi();
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('[LF] Pesquisa');
  if (!sheet) {
    ui.alert('Erro', 'Aba "[LF] Pesquisa" não encontrada.', ui.ButtonSet.OK);
    return;
  }

  const values = sheet.getDataRange().getValues();
  const { headerRow, headers } = encontrarLinhaDosCabecalhos(values);
  const semScore = _lerLeadsSemScore(values, headers, headerRow + 1);

  if (semScore.length === 0) {
    ui.alert('Concluído', 'Nenhum lead sem score encontrado.', ui.ButtonSet.OK);
    return;
  }

  const chunk = semScore.slice(0, CHUNK_SIZE);
  const restantes = semScore.length - chunk.length;

  const confirm = ui.alert(
    'Reprocessar leads sem score',
    `${semScore.length} leads sem score encontrados.\n\n` +
    `Esta execução processará: ${chunk.length} leads\n` +
    (restantes > 0 ? `Restará após esta execução: ${restantes} leads (execute novamente)\n` : '') +
    '\nDeseja prosseguir?',
    ui.ButtonSet.YES_NO
  );
  if (confirm !== ui.Button.YES) return;

  Logger.log(`🔁 Reprocessando ${chunk.length} de ${semScore.length} leads sem score...`);
  processarLeads(chunk);
  Logger.log('✅ Lote concluído.');

  if (restantes > 0) {
    ui.alert(
      'Lote concluído',
      `✅ ${chunk.length} leads processados.\n⏳ ${restantes} leads restantes — execute novamente para continuar.`,
      ui.ButtonSet.OK
    );
  } else {
    ui.alert('Concluído', `✅ Todos os ${chunk.length} leads foram processados.`, ui.ButtonSet.OK);
  }
}

/**
 * Cria triggers de polling (5min) e monitoramento (01:00 e 13:00)
 * Deve ser executado manualmente uma vez
 */
function agendarGatilho5Min() {
  const triggers = ScriptApp.getProjectTriggers();
  for (const trigger of triggers) {
    const funcName = trigger.getHandlerFunction();
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

  // 1️⃣ Polling a cada 5 minutos
  ScriptApp.newTrigger('executarPolling5Min')
    .timeBased()
    .everyMinutes(5)
    .create();
  Logger.log('✅ Trigger polling 5min criado: executarPolling5Min()');

  // 2️⃣ Monitoramento 2x por dia (01:00 e 13:00)
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
 * Check de monitoramento executado às 01:00 e 13:00 via trigger
 * Verifica: category drift, distribution drift, missing rate, score distribution,
 * problemas operacionais, qualidade CAPI
 */
function executarMonitoramentoDiario() {
  Logger.log('🔍 Iniciando monitoramento diário...');

  try {
    const leadsData = buscarLeadsUltimas24h();

    if (!leadsData || leadsData.length === 0) {
      Logger.log('⚠️ Nenhum lead encontrado nas últimas 12h');
      return;
    }

    Logger.log(`📊 Enviando ${leadsData.length} leads para análise...`);

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

    Logger.log(`\n📊 RESULTADOS DO MONITORAMENTO:`);
    Logger.log(`   Total de alertas: ${result.total_alerts}`);
    Logger.log(`   Por severidade: HIGH=${result.alerts_by_severity.HIGH}, MEDIUM=${result.alerts_by_severity.MEDIUM}, LOW=${result.alerts_by_severity.LOW}`);
    Logger.log(`   Por categoria: DATA=${result.alerts_by_category.data_quality}, OPS=${result.alerts_by_category.operational}, CAPI=${result.alerts_by_category.capi_quality}`);

    if (result.total_alerts > 0) {
      Logger.log(`\n🚨 ALERTAS DETECTADOS (${result.total_alerts}):`);
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

    const color = totalAlerts > 0 ? '#ff0000' : '#36a64f';

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
    Logger.log('📤 Chamando UrlFetchApp.fetch...');

    const response = UrlFetchApp.fetch(SLACK_WEBHOOK_URL, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });

    const responseCode = response.getResponseCode();
    Logger.log(`📥 Resposta do Slack: ${responseCode}`);
    Logger.log(`📥 Body: ${response.getContentText()}`);

    if (responseCode !== 200) {
      Logger.log(`⚠️ Erro ao enviar para Slack: ${responseCode}`);
    } else {
      Logger.log('✅ Slack retornou 200 OK');
    }

  } catch (error) {
    Logger.log(`❌ Erro ao enviar para Slack: ${error.message}`);
    Logger.log(`❌ Stack: ${error.stack}`);
  }
}

/**
 * Busca leads das últimas 12 horas para análise de monitoramento
 * Retorna array de objetos com todos os campos (formato para /monitoring/daily-check)
 */
function buscarLeadsUltimas24h() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('[LF] Pesquisa');
  if (!sheet) throw new Error('Aba "[LF] Pesquisa" não encontrada');

  const values = sheet.getDataRange().getValues();
  if (values.length <= 1) return [];

  const { headerRow, headers } = encontrarLinhaDosCabecalhos(values);
  const dataColIndex  = headers.indexOf('Data');
  const emailColIndex = headers.indexOf('E-mail');

  if (dataColIndex === -1) throw new Error('Coluna "Data" não encontrada');

  // Triggers rodam a cada 12h (01:00 e 13:00) — buscar janela de 12h
  const threshold = new Date(Date.now() - 12 * 60 * 60 * 1000);
  const recentLeads = [];
  const firstDataRow = headerRow + 1;

  for (let i = firstDataRow; i < values.length; i++) {
    const row = values[i];
    if (row[dataColIndex] === 'Data' && row[emailColIndex] === 'E-mail') continue;

    if (new Date(row[dataColIndex]) >= threshold) {
      const leadObj = {};
      for (let j = 0; j < headers.length; j++) {
        leadObj[headers[j]] = row[j];
      }
      recentLeads.push(leadObj);
    }
  }

  return recentLeads;
}

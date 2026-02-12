"""
Módulo para upload de relatórios Excel para Google Sheets.

Faz upload de arquivos Excel diretamente via Google Drive API,
preservando toda a formatação original (cores, negrito, bordas, etc.).
"""

import pandas as pd
import gspread
from google.auth import default as gauth_default
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from pathlib import Path
from typing import Optional
import logging
import time

logger = logging.getLogger(__name__)


class ValidationSheetsUploader:
    """
    Faz upload de relatórios de validação Excel para Google Sheets.

    Utiliza Google Drive API para converter Excel preservando formatação.
    Autenticação via Application Default Credentials (ADC) do Google Cloud.
    """

    def __init__(self):
        """Inicializa o uploader com autenticação ADC."""
        try:
            credentials, project = gauth_default()
            self.credentials = credentials
            self.gc = gspread.authorize(credentials)
            self.drive_service = build('drive', 'v3', credentials=credentials)
            self.project = project
            logger.info(f"    Autenticado no Google Cloud: {project}")
        except Exception as e:
            logger.error(f"    Erro na autenticação Google Cloud: {e}")
            raise

    def upload_excel_via_drive(
        self,
        excel_path: str,
        spreadsheet_title: Optional[str] = None,
        share_with_emails: Optional[list] = None
    ) -> str:
        """
        Faz upload de Excel via Google Drive API preservando formatação.

        Este método faz upload direto do arquivo .xlsx, permitindo que
        o Google Drive converta automaticamente para Sheets mantendo
        toda a formatação original (cores, negrito, bordas, etc.).

        Args:
            excel_path: Caminho para o arquivo Excel (.xlsx)
            spreadsheet_title: Título da planilha no Google Sheets
                             (padrão: nome do arquivo Excel)
            share_with_emails: Lista de emails para compartilhar a planilha
                              (padrão: não compartilha)

        Returns:
            URL da planilha criada no Google Sheets

        Raises:
            FileNotFoundError: Se arquivo Excel não existe
            Exception: Erros no upload
        """
        excel_path = Path(excel_path)

        if not excel_path.exists():
            raise FileNotFoundError(f"Arquivo Excel não encontrado: {excel_path}")

        # Usar nome do arquivo como título se não especificado
        if spreadsheet_title is None:
            spreadsheet_title = excel_path.stem

        logger.info(f"    Fazendo upload de {excel_path.name} via Google Drive...")

        try:
            # 1. Preparar metadata do arquivo
            file_metadata = {
                'name': spreadsheet_title,
                'mimeType': 'application/vnd.google-apps.spreadsheet'  # Converte para Sheets
            }

            # 2. Preparar arquivo para upload
            media = MediaFileUpload(
                str(excel_path),
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                resumable=True
            )

            # 3. Fazer upload e conversão
            logger.info(f"    Convertendo Excel para Google Sheets...")
            file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,webViewLink'
            ).execute()

            file_id = file.get('id')
            sheets_url = file.get('webViewLink')

            logger.info(f"    Upload concluído (ID: {file_id})")

            # 4. Tornar o arquivo público (qualquer pessoa com link pode visualizar)
            try:
                logger.info(f"    Tornando arquivo público...")
                self.drive_service.permissions().create(
                    fileId=file_id,
                    body={
                        'type': 'anyone',
                        'role': 'reader'
                    },
                    fields='id'
                ).execute()
                logger.info(f"    Arquivo público: qualquer pessoa com o link pode visualizar")
            except Exception as e:
                logger.warning(f"     Erro ao tornar arquivo público: {e}")

            # 5. Compartilhar com emails específicos se fornecidos (acesso de edição)
            if share_with_emails:
                logger.info(f"    Compartilhando acesso de edição com {len(share_with_emails)} usuários...")
                for email in share_with_emails:
                    try:
                        self.drive_service.permissions().create(
                            fileId=file_id,
                            body={
                                'type': 'user',
                                'role': 'writer',
                                'emailAddress': email
                            },
                            fields='id'
                        ).execute()
                        logger.info(f"       {email}")
                    except Exception as e:
                        logger.warning(f"        Erro ao compartilhar com {email}: {e}")

            logger.info(f"    Formatação preservada do Excel original!")
            return sheets_url

        except Exception as e:
            logger.error(f"    Erro no upload para Google Sheets: {e}")
            raise

    def upload_excel_to_sheets(
        self,
        excel_path: str,
        spreadsheet_title: Optional[str] = None,
        share_with_emails: Optional[list] = None
    ) -> str:
        """
        Faz upload de um arquivo Excel para Google Sheets.

        NOVO: Usa Google Drive API para preservar formatação!
        Converte Excel  Sheets mantendo cores, negrito, bordas, etc.

        Args:
            excel_path: Caminho para o arquivo Excel (.xlsx)
            spreadsheet_title: Título da planilha no Google Sheets
                             (padrão: nome do arquivo Excel)
            share_with_emails: Lista de emails para compartilhar a planilha
                              (padrão: não compartilha)

        Returns:
            URL da planilha criada no Google Sheets

        Raises:
            FileNotFoundError: Se arquivo Excel não existe
            Exception: Erros na criação ou upload
        """
        # Usar novo método via Drive API (preserva formatação)
        return self.upload_excel_via_drive(excel_path, spreadsheet_title, share_with_emails)

    def upload_excel_to_sheets_legacy(
        self,
        excel_path: str,
        spreadsheet_title: Optional[str] = None,
        share_with_emails: Optional[list] = None
    ) -> str:
        """
        [DEPRECATED] Método antigo que fazia upload célula por célula.
        Mantido para referência. Use upload_excel_to_sheets() ao invés.
        """
        excel_path = Path(excel_path)

        if not excel_path.exists():
            raise FileNotFoundError(f"Arquivo Excel não encontrado: {excel_path}")

        # Usar nome do arquivo como título se não especificado
        if spreadsheet_title is None:
            spreadsheet_title = excel_path.stem

        logger.info(f"    Fazendo upload de {excel_path.name} para Google Sheets...")

        try:
            # 1. Criar nova planilha
            logger.info(f"    Criando planilha: {spreadsheet_title}")
            spreadsheet = self.gc.create(spreadsheet_title)

            # 2. Ler todas as abas do Excel
            logger.info(f"    Lendo abas do Excel...")
            excel_file = pd.ExcelFile(excel_path)
            sheet_names = excel_file.sheet_names
            logger.info(f"    {len(sheet_names)} abas encontradas: {', '.join(sheet_names)}")

            # 3. Processar cada aba
            for idx, sheet_name in enumerate(sheet_names):
                logger.info(f"    Processando aba {idx + 1}/{len(sheet_names)}: {sheet_name}")

                # Ler dados da aba
                df = pd.read_excel(excel_path, sheet_name=sheet_name)

                # Criar ou usar worksheet existente
                if idx == 0:
                    # Primeira aba: renomear a worksheet padrão
                    worksheet = spreadsheet.sheet1
                    worksheet.update_title(sheet_name)
                else:
                    # Demais abas: criar nova worksheet
                    worksheet = spreadsheet.add_worksheet(
                        title=sheet_name,
                        rows=len(df) + 100,  # +100 linhas extras
                        cols=len(df.columns) + 10  # +10 colunas extras
                    )

                # Converter DataFrame para lista de listas (incluindo header)
                # Substituir NaN por string vazia para evitar erros
                df_filled = df.fillna('')

                # Header
                data = [df_filled.columns.tolist()]

                # Dados (converter todos os valores para string para evitar problemas de tipo)
                for _, row in df_filled.iterrows():
                    data.append([str(val) for val in row.tolist()])

                # Upload dos dados (batch update é mais eficiente)
                logger.info(f"      Fazendo upload de {len(data)} linhas...")
                worksheet.update('A1', data, value_input_option='USER_ENTERED')

                # Aplicar formatação (com delay maior para evitar rate limits)
                logger.info(f"      Aplicando formatação...")
                time.sleep(1.0)  # Delay antes de formatar
                self._apply_formatting(worksheet, sheet_name, len(data), len(df.columns))

                # Delay para respeitar rate limits (300 requests/min)
                time.sleep(1.5)  # Aumentado para 1.5s

            # 4. Compartilhar se emails fornecidos
            if share_with_emails:
                logger.info(f"    Compartilhando com {len(share_with_emails)} usuários...")
                for email in share_with_emails:
                    try:
                        spreadsheet.share(email, perm_type='user', role='writer')
                        logger.info(f"       {email}")
                        time.sleep(0.3)  # Rate limit
                    except Exception as e:
                        logger.warning(f"        Erro ao compartilhar com {email}: {e}")

            # 5. Retornar URL
            spreadsheet_url = spreadsheet.url
            logger.info(f"    Upload concluído: {spreadsheet_url}")

            return spreadsheet_url

        except Exception as e:
            logger.error(f"    Erro no upload para Google Sheets: {e}")
            raise

    def update_existing_spreadsheet(
        self,
        spreadsheet_url: str,
        excel_path: str
    ) -> str:
        """
        Atualiza uma planilha existente com dados de um Excel.

        Args:
            spreadsheet_url: URL da planilha existente
            excel_path: Caminho para o arquivo Excel

        Returns:
            URL da planilha atualizada
        """
        excel_path = Path(excel_path)

        if not excel_path.exists():
            raise FileNotFoundError(f"Arquivo Excel não encontrado: {excel_path}")

        logger.info(f"    Atualizando planilha existente...")

        try:
            # Abrir planilha existente
            spreadsheet = self.gc.open_by_url(spreadsheet_url)

            # Ler abas do Excel
            excel_file = pd.ExcelFile(excel_path)
            sheet_names = excel_file.sheet_names

            # Processar cada aba
            for idx, sheet_name in enumerate(sheet_names):
                logger.info(f"    Atualizando aba: {sheet_name}")

                df = pd.read_excel(excel_path, sheet_name=sheet_name)

                # Verificar se worksheet existe
                try:
                    worksheet = spreadsheet.worksheet(sheet_name)
                except gspread.WorksheetNotFound:
                    # Criar se não existir
                    worksheet = spreadsheet.add_worksheet(
                        title=sheet_name,
                        rows=len(df) + 100,
                        cols=len(df.columns) + 10
                    )

                # Limpar dados existentes
                worksheet.clear()

                # Upload novos dados
                df_filled = df.fillna('')
                data = [df_filled.columns.tolist()]
                for _, row in df_filled.iterrows():
                    data.append([str(val) for val in row.tolist()])

                worksheet.update('A1', data, value_input_option='USER_ENTERED')
                time.sleep(0.5)

            logger.info(f"    Atualização concluída: {spreadsheet.url}")
            return spreadsheet.url

        except Exception as e:
            logger.error(f"    Erro ao atualizar planilha: {e}")
            raise

    def _apply_formatting(self, worksheet, sheet_name: str, num_rows: int, num_cols: int):
        """
        Aplica formatação ao worksheet baseado no tipo de aba.

        Args:
            worksheet: Worksheet do gspread
            sheet_name: Nome da aba
            num_rows: Número de linhas com dados
            num_cols: Número de colunas
        """
        try:
            # Definir cores padrão
            COLOR_HEADER_BLUE = {'red': 0.26, 'green': 0.52, 'blue': 0.96}  # Azul
            COLOR_ML_GREEN = {'red': 0.72, 'green': 0.88, 'blue': 0.80}  # Verde claro
            COLOR_CONTROLE_RED = {'red': 0.92, 'green': 0.60, 'blue': 0.60}  # Vermelho claro
            COLOR_WHITE = {'red': 1.0, 'green': 1.0, 'blue': 1.0}
            COLOR_TITLE_BG = {'red': 0.95, 'green': 0.95, 'blue': 0.95}  # Cinza claro

            # LER TODOS OS DADOS DE UMA VEZ (evitar múltiplas chamadas acell)
            all_values = worksheet.get_all_values()
            max_check_rows = min(len(all_values), 50)

            # 1. Formatar primeira linha (geralmente título)
            if num_rows > 0:
                worksheet.format('A1:Z1', {
                    'textFormat': {'bold': True, 'fontSize': 12},
                    'backgroundColor': COLOR_TITLE_BG,
                    'horizontalAlignment': 'LEFT'
                })
                time.sleep(0.3)  # Pequeno delay

            # 2. Detectar e formatar linhas de cabeçalho e títulos
            for row_idx in range(max_check_rows):
                if row_idx >= len(all_values):
                    break

                cell_value = all_values[row_idx][0] if len(all_values[row_idx]) > 0 else None
                if not cell_value:
                    continue

                cell_str = str(cell_value)
                end_col = self._col_letter(num_cols)
                actual_row_num = row_idx + 1  # Sheets usa 1-based indexing

                # Título de seção (contém emojis ou palavras-chave)
                if any(keyword in cell_str for keyword in ['COMPARAÇÃO', 'PERFORMANCE', 'ESTATÍSTICAS', 'PERÍODOS', 'MONITORING']):
                    worksheet.format(f'A{actual_row_num}:{end_col}{actual_row_num}', {
                        'textFormat': {'bold': True, 'fontSize': 11},
                        'backgroundColor': COLOR_TITLE_BG,
                        'horizontalAlignment': 'LEFT'
                    })
                    time.sleep(0.3)

                # Header de tabela (contém "Métrica")
                elif 'Métrica' in cell_str:
                    # Pegar valores da linha (já temos em all_values)
                    row_values = all_values[row_idx] if row_idx < len(all_values) else []

                    for col_idx, val in enumerate(row_values, 1):
                        if col_idx > num_cols:
                            break

                        col_letter = self._col_letter(col_idx)
                        cell_range = f'{col_letter}{actual_row_num}'

                        if not val:
                            continue

                        val_str = str(val)

                        # Coluna "Eventos ML" - fundo verde
                        if 'Eventos ML' in val_str:
                            worksheet.format(cell_range, {
                                'textFormat': {'bold': True, 'foregroundColor': {'red': 0, 'green': 0, 'blue': 0}},
                                'backgroundColor': COLOR_ML_GREEN,
                                'horizontalAlignment': 'CENTER'
                            })
                        # Coluna "Controle" - fundo vermelho
                        elif 'Controle' in val_str:
                            worksheet.format(cell_range, {
                                'textFormat': {'bold': True, 'foregroundColor': {'red': 0, 'green': 0, 'blue': 0}},
                                'backgroundColor': COLOR_CONTROLE_RED,
                                'horizontalAlignment': 'CENTER'
                            })
                        # Outras colunas do header - fundo azul
                        else:
                            worksheet.format(cell_range, {
                                'textFormat': {'bold': True, 'foregroundColor': COLOR_WHITE},
                                'backgroundColor': COLOR_HEADER_BLUE,
                                'horizontalAlignment': 'CENTER'
                            })

                    time.sleep(0.5)  # Delay após formatar linha completa

            # 3. Formatar colunas específicas baseado no nome da aba
            # Usar dados já carregados
            if ('Comparação' in sheet_name or 'ML' in sheet_name) and len(all_values) > 0:
                first_row = all_values[0] if all_values else []
                for col_idx, cell_value in enumerate(first_row, 1):
                    if col_idx > num_cols:
                        break
                    if cell_value and 'Eventos ML' in str(cell_value):
                        col_letter = self._col_letter(col_idx)
                        worksheet.format(f'{col_letter}1:{col_letter}{num_rows}', {
                            'backgroundColor': COLOR_ML_GREEN
                        })
                        time.sleep(0.3)
                    elif cell_value and 'Controle' in str(cell_value):
                        col_letter = self._col_letter(col_idx)
                        worksheet.format(f'{col_letter}1:{col_letter}{num_rows}', {
                            'backgroundColor': COLOR_CONTROLE_RED
                        })
                        time.sleep(0.3)

            # 4. Formatar números como moeda e percentual (usar dados já carregados)
            time.sleep(0.5)
            self._format_numbers(worksheet, num_rows, num_cols, all_values)

            # 5. Bordas removidas para reduzir API calls

            # 6. Ajustar largura das colunas (usar método correto do gspread)
            # Nota: set_column_width pode não existir em todas as versões
            # Usar apenas se disponível
            try:
                if hasattr(worksheet, 'set_column_width'):
                    for col_idx in range(1, min(num_cols + 1, 10)):  # Limitar a 10 colunas
                        worksheet.set_column_width(col_idx, 150)
            except:
                pass  # Ignorar se não funcionar

        except Exception as e:
            logger.warning(f"        Erro ao aplicar formatação: {e}")

    def _format_numbers(self, worksheet, num_rows: int, num_cols: int, all_values: list):
        """
        Formata colunas numéricas (moeda, percentual, decimal).

        Args:
            worksheet: Worksheet do gspread
            num_rows: Número de linhas
            num_cols: Número de colunas
            all_values: Todos os valores já carregados
        """
        try:
            # Usar header já carregado
            header_row = all_values[0] if len(all_values) > 0 else []

            for col_idx, header in enumerate(header_row, 1):
                if col_idx > num_cols or not header:
                    continue

                header_lower = str(header).lower()
                col_letter = self._col_letter(col_idx)
                range_notation = f'{col_letter}2:{col_letter}{num_rows}'

                # Moeda (R$)
                if any(keyword in header_lower for keyword in ['receita', 'gasto', 'valor', 'cpl', 'cpa', 'margem', 'r$']):
                    worksheet.format(range_notation, {
                        'numberFormat': {
                            'type': 'CURRENCY',
                            'pattern': 'R$ #,##0.00'
                        }
                    })
                    time.sleep(0.3)

                # Percentual (%)
                elif any(keyword in header_lower for keyword in ['taxa', 'diferença %', '%', 'conversão', 'trackeamento']):
                    worksheet.format(range_notation, {
                        'numberFormat': {
                            'type': 'PERCENT',
                            'pattern': '0.00%'
                        }
                    })
                    time.sleep(0.3)

                # ROAS (decimal com 2 casas)
                elif 'roas' in header_lower:
                    worksheet.format(range_notation, {
                        'numberFormat': {
                            'type': 'NUMBER',
                            'pattern': '#,##0.00'
                        }
                    })
                    time.sleep(0.3)

        except Exception as e:
            logger.warning(f"        Erro ao formatar números: {e}")

    def _col_letter(self, col_num: int) -> str:
        """
        Converte número de coluna (1-based) para letra (A, B, ..., Z, AA, AB, ...).

        Args:
            col_num: Número da coluna (1 = A, 2 = B, etc.)

        Returns:
            Letra da coluna
        """
        result = ""
        while col_num > 0:
            col_num -= 1
            result = chr(col_num % 26 + ord('A')) + result
            col_num //= 26
        return result

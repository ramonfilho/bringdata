#!/usr/bin/env python3
"""
Extrai classificações do arquivo classificacao_prints.docx para formato texto.

Captura corretamente as decisões marcadas com [X] nos checkboxes.

Uso:
    python src/extract_classificacoes.py
"""

from docx import Document
import re
import sys
from pathlib import Path


def extract_decision(text):
    """
    Extrai a decisão marcada com [X] do texto dos checkboxes.

    Args:
        text: Texto contendo os checkboxes

    Returns:
        String com a decisão marcada ou "Não marcado"
    """
    # Padrões de decisão com [X]
    decisions = [
        (r'\[X\]\s*\s*CRÍTICO', ' CRÍTICO'),
        (r'\[X\]\s*\s*ESSENCIAL', ' ESSENCIAL'),
        (r'\[X\]\s*\s*NORMAL', ' NORMAL'),
        (r'\[X\]\s*\s*DETALHADO', ' DETALHADO'),
        (r'\[X\]\s*\s*SIMPLIFICAR', ' SIMPLIFICAR'),
        (r'\[X\]\s*\s*REMOVER', ' REMOVER'),
    ]

    for pattern, decision in decisions:
        if re.search(pattern, text, re.IGNORECASE):
            return decision

    return "Não marcado"


def parse_section(paragraphs, start_idx):
    """
    Parseia uma seção completa a partir do índice inicial.

    Args:
        paragraphs: Lista de parágrafos do documento
        start_idx: Índice do parágrafo "SEÇÃO #X de 20"

    Returns:
        Dicionário com os dados da seção
    """
    section = {
        'number': '',
        'title': '',
        'decision': '',
        'annotations': []
    }

    i = start_idx

    # Extrair número da seção
    section_header = paragraphs[i].text.strip()
    match = re.search(r'SEÇÃO #(\d+) de (\d+)', section_header)
    if match:
        section['number'] = match.group(1)

    i += 1

    # Extrair título (próxima linha não vazia)
    while i < len(paragraphs) and not paragraphs[i].text.strip():
        i += 1

    if i < len(paragraphs):
        title = paragraphs[i].text.strip()
        # Remover emojis e símbolos extras no início
        section['title'] = title

    i += 1

    # Pular até encontrar os checkboxes (linha com "[")
    decision_found = False
    while i < len(paragraphs):
        text = paragraphs[i].text

        # Se encontramos checkboxes, extrair decisão
        if '[' in text and ('CRÍTICO' in text or 'ESSENCIAL' in text or 'NORMAL' in text or
                           'DETALHADO' in text or 'SIMPLIFICAR' in text or 'REMOVER' in text):
            # Pode estar em múltiplas linhas
            checkbox_text = text
            if i + 1 < len(paragraphs) and '[' in paragraphs[i + 1].text:
                checkbox_text += '\n' + paragraphs[i + 1].text

            section['decision'] = extract_decision(checkbox_text)
            decision_found = True
            break

        # Se chegamos na próxima seção sem encontrar checkboxes, parar
        if 'SEÇÃO #' in text and i != start_idx:
            break

        i += 1

    # Procurar anotações (após "ANOTAÇÕES" ou "VERSÃO SIMPLIFICADA")
    while i < len(paragraphs):
        text = paragraphs[i].text.strip()

        # Próxima seção, parar
        if 'SEÇÃO #' in text:
            break

        # Encontrou seção de anotações
        if 'ANOTAÇÕES' in text or 'VERSÃO SIMPLIFICADA' in text:
            i += 1
            # Pular linhas de separação
            while i < len(paragraphs) and ('' in paragraphs[i].text or paragraphs[i].text.strip() == ''):
                i += 1

            # Coletar anotações até próxima seção
            while i < len(paragraphs):
                text = paragraphs[i].text.strip()
                if 'SEÇÃO #' in text:
                    break
                # Ignorar linhas de separação (underscore repetido)
                if text and not re.match(r'^_+$', text):
                    section['annotations'].append(text)
                i += 1
            break

        i += 1

    return section


def extract_all_sections(doc_path):
    """
    Extrai todas as seções do documento.

    Args:
        doc_path: Caminho para o arquivo .docx

    Returns:
        Lista de dicionários com dados das seções
    """
    doc = Document(doc_path)
    paragraphs = doc.paragraphs

    sections = []

    for i, para in enumerate(paragraphs):
        if 'SEÇÃO #' in para.text and ' de 20' in para.text:
            section = parse_section(paragraphs, i)
            sections.append(section)

    return sections


def format_output(sections):
    """
    Formata as seções extraídas em texto legível.

    Args:
        sections: Lista de dicionários com dados das seções

    Returns:
        String formatada
    """
    output = []
    output.append("=" * 80)
    output.append("CLASSIFICAÇÕES E ANOTAÇÕES - PIPELINE DE TREINO")
    output.append("=" * 80)
    output.append("")
    output.append("################################################################################")
    output.append("# ESTRATÉGIA DE IMPLEMENTAÇÃO DO SISTEMA DE VERBOSIDADE")
    output.append("################################################################################")
    output.append("")
    output.append("## 1. NÍVEIS DE VERBOSIDADE")
    output.append("")
    output.append("O pipeline suporta 4 níveis de verbosidade via argumento --verbosity:")
    output.append("- silent: Apenas erros (ERROR)")
    output.append("- minimal: Avisos e erros (WARNING)")
    output.append("- normal: Informações principais + avisos + erros (INFO) [PADRÃO]")
    output.append("- debug: Todas as informações incluindo detalhes técnicos (DEBUG)")
    output.append("")
    output.append("## 2. PADRÃO DE IMPLEMENTAÇÃO")
    output.append("")
    output.append("### 2.1 MODO NORMAL (--verbosity normal)")
    output.append("- Usar logger.info() para informações principais")
    output.append("- Mostrar apenas RESUMOS e TOTAIS")
    output.append("- Exibir mensagens de progresso importantes")
    output.append("- Informar dados finais disponíveis")
    output.append("- SEM tabelas detalhadas")
    output.append("- SEM listas completas de itens processados")
    output.append("")
    output.append("### 2.2 MODO DEBUG (--verbosity debug)")
    output.append("- Usar logger.debug() para informações detalhadas")
    output.append("- Mostrar tabelas completas com todos os itens")
    output.append("- Exibir listas de arquivos/abas processados")
    output.append("- Incluir detalhes de processamento por item")
    output.append("- Manter cabeçalhos e rodapés de tabelas")
    output.append("")
    output.append("### 2.3 FORMATAÇÃO DE OUTPUT")
    output.append("")
    output.append("#### Regras de Separação:")
    output.append("1. **Cabeçalho do Pipeline**: Sem linhas de separação (====) acima/abaixo")
    output.append("2. **Entre Configuração e CÉLULA 1**: UMA linha de separação (====)")
    output.append("3. **Entre Células**: UMA linha de separação (====) entre cada célula")
    output.append("4. **Dentro das Células**: SEM linhas de separação (====)")
    output.append("")
    output.append("#### Estrutura de uma Célula:")
    output.append("```")
    output.append("logger.info(\"=\" * 80)  # Separador antes da célula")
    output.append("logger.info(\"\")")
    output.append("logger.info(\" CÉLULA X: TÍTULO DA CÉLULA\")")
    output.append("")
    output.append("# Processamento...")
    output.append("")
    output.append("logger.info(\"\")")
    output.append("logger.info(\" RESUMO:\")")
    output.append("logger.info(f\"Métrica 1: {valor1}\")")
    output.append("logger.info(f\"Métrica 2: {valor2}\")")
    output.append("logger.info(\"\")")
    output.append("")
    output.append("# Tabela detalhada (apenas em DEBUG)")
    output.append("logger.debug(\"\")")
    output.append("logger.debug(\" TABELA DETALHADA\")")
    output.append("logger.debug(\"=\" * 80)")
    output.append("logger.debug(\"CABEÇALHO DA TABELA\")")
    output.append("logger.debug(\"-\" * 80)")
    output.append("for item in items:")
    output.append("    logger.debug(f\"Linha da tabela: {item}\")")
    output.append("logger.debug(\"-\" * 80)")
    output.append("logger.debug(f\"TOTAL: {total}\")")
    output.append("logger.debug(\"=\" * 80)")
    output.append("```")
    output.append("")
    output.append("## 3. EXEMPLOS IMPLEMENTADOS")
    output.append("")
    output.append("### CÉLULA 1 - LEITURA DE ARQUIVOS")
    output.append(" NORMAL: Número de arquivos + fonte de dados")
    output.append(" DEBUG: Lista completa de arquivos carregados")
    output.append("")
    output.append("### CÉLULA 2 - FILTRAGEM E DUPLICATAS")
    output.append(" NORMAL: Resumo (arquivos, abas, linhas, duplicatas, percentual)")
    output.append(" DEBUG: Tabela com detalhes de cada arquivo/aba processado")
    output.append("")
    output.append("### CÉLULA 3 - REMOÇÃO DE COLUNAS")
    output.append(" NORMAL: Total de colunas removidas")
    output.append(" DEBUG: Tabela com colunas antes/depois por arquivo/aba")
    output.append("")
    output.append("## 4. CHECKLIST PARA IMPLEMENTAR NOVA CÉLULA")
    output.append("")
    output.append("[ ] Identificar informações essenciais (resumo) vs detalhadas (debug)")
    output.append("[ ] Usar logger.info() para resumos")
    output.append("[ ] Usar logger.debug() para tabelas/listas detalhadas")
    output.append("[ ] Adicionar separador (====) ANTES do título da célula")
    output.append("[ ] NÃO adicionar separadores dentro da célula")
    output.append("[ ] Testar com --verbosity normal e --verbosity debug")
    output.append("[ ] Verificar que output NORMAL é limpo e conciso")
    output.append("[ ] Verificar que output DEBUG tem todos os detalhes")
    output.append("")
    output.append("## 5. SUBSTITUIÇÕES GLOBAIS REALIZADAS")
    output.append("")
    output.append("- Todos print()  logger.info() ou logger.debug()")
    output.append("- Removidas todas linhas \"print(f'=' * N)\" de separação")
    output.append("- Removidos \"\\n\" do início de logger.info()")
    output.append("- Adicionados logger.info(\"\") para linhas em branco")
    output.append("- Padronizado espaçamento entre seções")
    output.append("")

    for section in sections:
        output.append("=" * 80)
        output.append(f"SEÇÃO #{section['number']} de 20")
        output.append("=" * 80)
        output.append(f"Título: {section['title']}")
        output.append(f"Decisão: {section['decision']}")
        output.append("")
        output.append("ANOTAÇÕES:")
        output.append("-" * 80)
        output.append("")

        if section['annotations']:
            for annotation in section['annotations']:
                if annotation:
                    output.append(annotation)

        output.append("_" * 90)
        output.append("")
        output.append("_" * 90)
        output.append("")
        output.append("_" * 90)
        output.append("")
        output.append("")
        output.append("")
        output.append("-" * 80)
        output.append("")

    return '\n'.join(output)


def update_decisions_in_existing_file(existing_file_path, sections):
    """
    Atualiza apenas as decisões no arquivo existente, preservando todas as anotações.

    Args:
        existing_file_path: Path para o arquivo existente
        sections: Lista de seções com decisões extraídas do docx

    Returns:
        String com o conteúdo atualizado
    """
    if not existing_file_path.exists():
        print(f"  Arquivo existente não encontrado: {existing_file_path}")
        print(" Criando arquivo novo...")
        return format_output(sections)

    # Ler arquivo existente
    existing_content = existing_file_path.read_text(encoding='utf-8')

    # Criar mapa de decisões por número de seção
    decision_map = {section['number']: section['decision'] for section in sections}

    # Atualizar as linhas de decisão
    lines = existing_content.split('\n')
    updated_lines = []

    for line in lines:
        # Se a linha é uma decisão, atualizar
        if line.startswith('Decisão:'):
            # Procurar qual seção estamos (olhar para trás)
            section_num = None
            for prev_line in reversed(updated_lines[-20:]):  # Olhar últimas 20 linhas
                match = re.search(r'SEÇÃO #(\d+) de', prev_line)
                if match:
                    section_num = match.group(1)
                    break

            if section_num and section_num in decision_map:
                updated_lines.append(f'Decisão: {decision_map[section_num]}')
            else:
                updated_lines.append(line)
        else:
            updated_lines.append(line)

    return '\n'.join(updated_lines)


def main():
    """Função principal."""
    # Caminhos
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    docx_path = project_root / 'docs' / 'classificacao_prints.docx'
    existing_file_path = project_root / 'docs' / 'classificacoes_extraidas.txt'
    backup_path = project_root / 'docs' / 'classificacoes_extraidas.txt.bak'

    print(f" Lendo documento: {docx_path}")

    if not docx_path.exists():
        print(f" Erro: Arquivo não encontrado: {docx_path}")
        sys.exit(1)

    # Extrair seções
    print(" Extraindo decisões do .docx...")
    sections = extract_all_sections(docx_path)
    print(f" {len(sections)} seções encontradas")

    # Fazer backup do arquivo existente
    if existing_file_path.exists():
        print(f" Criando backup em: {backup_path}")
        import shutil
        shutil.copy2(existing_file_path, backup_path)

    # Atualizar arquivo preservando anotações
    print(" Atualizando decisões (preservando anotações)...")
    updated_content = update_decisions_in_existing_file(existing_file_path, sections)

    # Salvar
    print(f" Salvando em: {existing_file_path}")
    existing_file_path.write_text(updated_content, encoding='utf-8')

    print(" Atualização concluída!")
    print()
    print(" Resumo das decisões:")
    decision_counts = {}
    for section in sections:
        decision = section['decision']
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

    for decision, count in sorted(decision_counts.items()):
        print(f"  {decision}: {count} seções")

    print()
    print(f" Backup salvo em: {backup_path}")


if __name__ == '__main__':
    main()

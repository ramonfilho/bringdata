"""
Gera PDF de "Requisitos e contrato de dados do sistema novo".

Lê docs/REQUISITOS_SISTEMA_NOVO.md (fonte única — editável) e renderiza
com a base compartilhada `scripts/pdf_base` (paleta/estilos/espaçamento
padrão Bring Data).

Saída: V2/propostas_e_apresentacoes/requisitos_sistema_novo.pdf
"""
import re
from pathlib import Path

from reportlab.platypus import Paragraph, Spacer

import pdf_base as B

SRC = Path(__file__).parent.parent / "docs" / "REQUISITOS_SISTEMA_NOVO.md"
OUTPUT = Path(__file__).parent.parent / "propostas_e_apresentacoes" / "requisitos_sistema_novo.pdf"

ST = B.styles()


def inline(text):
    """Markdown inline -> mini-HTML do reportlab."""
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'`([^`]+)`', r'<font face="Courier" size="8.5">\1</font>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*([^*]+?)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'\1', text)
    return text


def split_row(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def parse_md(text):
    story, para, table, callout = [], [], [], []

    def flush_para():
        if para:
            story.append(Paragraph(inline(' '.join(para)), ST['body']))
            para.clear()

    def flush_callout():
        if callout:
            story.extend(B.callout(inline(' '.join(callout)), ST))
            callout.clear()

    def flush_table():
        if table:
            header = [Paragraph(inline(c), ST['th']) for c in split_row(table[0])]
            rows = [[Paragraph(inline(c), ST['td']) for c in split_row(r)]
                    for r in table[2:]]  # pula o separador |---|
            story.append(B.make_table(header, rows, B.col_widths(len(header))))
            story.append(Spacer(1, 6))
            table.clear()

    lines = text.split('\n')
    code_buf = None
    for raw in lines:
        ln = raw.rstrip()
        s = ln.strip()

        if s.startswith('```'):
            if code_buf is None:
                flush_para(); flush_callout(); flush_table()
                code_buf = []
            else:
                story.extend(B.code_block('\n'.join(code_buf), ST))
                code_buf = None
            continue
        if code_buf is not None:
            code_buf.append(raw)
            continue

        if '|' in ln and s.startswith('|'):
            flush_para(); flush_callout()
            table.append(ln)
            continue
        flush_table()

        if s.startswith('> '):
            flush_para()
            callout.append(s[2:])
            continue
        flush_callout()

        if not s:
            flush_para()
        elif s == '---':
            flush_para()
            story.append(B.rule())
        elif s.startswith('# '):
            flush_para()
            story.append(Paragraph(inline(s[2:].strip()), ST['h1']))
            story.append(B.rule())
        elif s.startswith('## '):
            flush_para()
            story.append(Paragraph(inline(s[3:]), ST['h2']))
        elif s.startswith('### ') or s.startswith('#### '):
            flush_para()
            story.append(Paragraph(inline(s.lstrip('#').strip()), ST['h3']))
        elif re.match(r'^[-*] ', s):
            flush_para()
            story.append(Paragraph(inline(s[2:]), ST['li'], bulletText='•'))
        elif re.match(r'^\d+\. ', s):
            flush_para()
            num = s.split('.', 1)[0]
            story.append(Paragraph(inline(s[len(num) + 2:]), ST['li'], bulletText=f'{num}.'))
        else:
            para.append(s)

    if code_buf is not None:
        story.extend(B.code_block('\n'.join(code_buf), ST))
    flush_para(); flush_callout(); flush_table()
    return story


def main():
    story = parse_md(SRC.read_text(encoding='utf-8'))
    B.build_pdf(OUTPUT, story,
                title="Requisitos e contrato de dados do sistema novo",
                footer_label="Bring Data · Requisitos do sistema novo")
    print(f"PDF gerado: {OUTPUT}")


if __name__ == '__main__':
    main()

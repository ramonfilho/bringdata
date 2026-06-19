"""
Conversor genérico Markdown -> PDF (padrão Bring Data).

Render um .md com a base compartilhada `pdf_base` (paleta/estilos/espaçamento +
`parse_markdown`). PDFs novos passam a ser só um arquivo .md — sem código bespoke.

Uso:
  python scripts/gerar_pdf_md.py --src docs/arquivo.md --out propostas_e_apresentacoes/arquivo.pdf \
      --title "Título" --footer "Bring Data · Rótulo"

Geradores antigos (gerar_pdf_*.py com dados embutidos) continuam válidos para
PDFs que calculam números na hora; este é o caminho para docs em prosa/tabela.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pdf_base as B


def main():
    ap = argparse.ArgumentParser(description="Markdown -> PDF (Bring Data)")
    ap.add_argument("--src", required=True, help="Caminho do .md")
    ap.add_argument("--out", required=True, help="Caminho do .pdf de saída")
    ap.add_argument("--title", required=True, help="Título do documento (metadados)")
    ap.add_argument("--footer", help="Rótulo do rodapé (default: título)")
    a = ap.parse_args()

    src, out = Path(a.src), Path(a.out)
    story = B.parse_markdown(src.read_text(encoding="utf-8"))
    B.build_pdf(out, story, title=a.title, footer_label=a.footer or a.title)
    print(f"PDF gerado: {out}")


if __name__ == "__main__":
    main()

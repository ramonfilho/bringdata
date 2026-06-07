"""
Gera PDF mínimo p/ stakeholders (dono + gestor de tráfego): potencial de
selecionar leads por retorno por real gasto, em vez de propensão de compra,
no DevClub.

Base de números: análise rodada em 2026-06-02/03 sobre snapshot 120d
(scripts/pull_roas_dataset.py + scripts/analise_roas_a_vista.py no worktree
bring_data-roas).

Saída: V2/propostas_e_apresentacoes/descoberta_roas_devclub.pdf
"""
from pathlib import Path

from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER

import pdf_base as B

OUTPUT = Path(__file__).parent.parent / "propostas_e_apresentacoes" / "descoberta_roas_devclub.pdf"
ST = B.styles()


def subtitle_style():
    return ParagraphStyle(
        "subtitle", fontName="Helvetica", fontSize=9.5,
        textColor=B.C_MID_GRAY, leading=13, spaceAfter=8,
    )


def footnote_style():
    return ParagraphStyle(
        "foot", fontName="Helvetica", fontSize=7.5,
        textColor=B.C_MID_GRAY, leading=10, spaceAfter=2,
    )


def kpi_strip(items):
    """Faixa horizontal de KPIs grandes (rótulo em cima, número grande embaixo)."""
    hdr_style = ParagraphStyle(
        "kpih", fontName="Helvetica-Bold", fontSize=8, textColor=B.C_WHITE,
        leading=10, alignment=TA_CENTER,
    )
    val_style = ParagraphStyle(
        "kpiv", fontName="Helvetica-Bold", fontSize=14, textColor=B.C_BLACK,
        leading=18, alignment=TA_CENTER,
    )
    hdrs = [Paragraph(h, hdr_style) for h, _ in items]
    vals = [Paragraph(v, val_style) for _, v in items]
    t = Table([hdrs, vals], colWidths=[B.CONTENT_WIDTH / len(items)] * len(items))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), B.C_BLACK),
        ("BACKGROUND", (0, 1), (-1, 1), HexColor("#f4fbf6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("BOX", (0, 0), (-1, -1), 0.5, B.C_RULE),
    ]))
    return [t, Spacer(1, 6)]


def main():
    story = []

    # Capa enxuta
    story.append(B.P("Retorno esperado por lead — potencial", ST["h1"]))
    story.append(B.P(
        "DevClub · base de análise: 120 dias · R$ 633 mil investidos na Meta",
        subtitle_style(),
    ))
    story.append(B.rule())

    # O que descobrimos — uma frase, sem detalhe técnico
    story.append(B.P("O que descobrimos", ST["h2"]))
    story.append(B.P(
        "Agora conseguimos calcular, lead por lead, <b>quanto a Meta cobrou</b> "
        "por trazer ele. Cruzando esse custo com a probabilidade de compra que "
        "o modelo já estima, sabemos <b>o retorno esperado de cada lead</b> "
        "antes da Meta decidir pra quem mostrar o anúncio.",
        ST["body"],
    ))

    # Como calculamos — fórmula em linguagem de negócio
    story.append(B.P("Como calculamos", ST["h2"]))
    story.append(B.P(
        "Pra cada lead capturado, três números:",
        ST["body"],
    ))
    story.append(B.P(
        "<b>•&nbsp;&nbsp;Custo do lead</b> — quanto a campanha que trouxe ele "
        "gastou no dia, dividido pelos leads que ela trouxe nesse dia.",
        ST["li"],
    ))
    story.append(B.P(
        "<b>•&nbsp;&nbsp;Receita esperada</b> — probabilidade de compra (modelo "
        "atual) × ticket recebido à vista (cartão líquido + 1ª parcela do boleto).",
        ST["li"],
    ))
    story.append(B.P(
        "<b>•&nbsp;&nbsp;Retorno esperado</b> — receita esperada ÷ custo do lead.",
        ST["li"],
    ))
    story.extend(B.code_block(
        "Retorno esperado  =  (probabilidade de compra × ticket à vista) ÷ custo do lead",
        ST,
    ))
    story.append(B.P(
        "O ranking de hoje usa só a 1ª parte (probabilidade de compra). "
        "O ranking testado usa a fórmula inteira — o lead caro precisa "
        "compensar com probabilidade maior pra entrar no topo.",
        ST["body"],
    ))

    # Potencial — a tabela é o coração
    story.append(B.P("Ganho por faixa do funil", ST["h2"]))
    story.append(B.P(
        "Mesma verba, mesmos leads. O que muda é <b>quais leads contam como "
        "“bons” pra Meta otimizar em cima</b> — hoje só a probabilidade de "
        "compra entra na conta; no teste, entra também quanto o lead custou.",
        ST["body"],
    ))

    header = [B.P(c, ST["th"]) for c in (
        "Faixa selecionada", "ROAS hoje", "ROAS com seleção por retorno", "Ganho anual",
    )]
    rows = [
        [B.P("Top 10%", ST["td"]), B.P("1,18x", ST["td"]),
         B.P("<b>1,97x</b>", ST["td"]), B.P("<b>R$ 86 mil</b>", ST["td"])],
        [B.P("Top 20%", ST["td"]), B.P("1,03x", ST["td"]),
         B.P("<b>1,47x</b>", ST["td"]), B.P("<b>R$ 128 mil</b>", ST["td"])],
        [B.P("Top 30%", ST["td"]), B.P("0,86x", ST["td"]),
         B.P("<b>1,26x</b>", ST["td"]), B.P("<b>R$ 235 mil</b>", ST["td"])],
        [B.P("Top 50%", ST["td"]), B.P("0,70x", ST["td"]),
         B.P("<b>0,92x</b>", ST["td"]), B.P("<b>R$ 298 mil</b>", ST["td"])],
    ]
    cw = [4.0 * cm, 3.5 * cm, 5.5 * cm, 4.0 * cm]
    story.append(B.make_table(header, rows, cw))

    story.append(B.P(
        "ROAS calculado contra faturamento <b>recebido à vista</b> "
        "(cartão líquido + 1ª parcela do boleto), critério do dono.",
        footnote_style(),
    ))

    story.append(Spacer(1, 6))
    story.extend(B.callout(
        "<b>Por que o ganho cresce conforme a faixa amplia:</b> o modelo atual "
        "acerta bem o topo, mas no meio do funil mistura leads caros — que a "
        "Meta acaba escolhendo pra otimizar. Tirar esses leads caros da seleção "
        "puxa o ROAS médio pra cima em todas as faixas largas.",
        ST,
    ))

    # O que muda na prática
    story.append(B.P("O que muda na prática", ST["h2"]))
    story.append(B.P(
        "<b>Pra quem investe:</b> mesma verba, mais matrículas pagas "
        "— ou matrículas equivalentes com verba menor.",
        ST["body"],
    ))
    story.append(B.P(
        "<b>Pra quem opera tráfego:</b> visibilidade, pela primeira vez, "
        "de quanto cada campanha está custando vs retornando — lead a lead, "
        "não só na média do conjunto.",
        ST["body"],
    ))
    story.append(B.P(
        "<b>Pra começar:</b> teste A/B em produção sobre a base atual — "
        "sem trocar modelo, sem retreino, sem mexer em criativo.",
        ST["body"],
    ))

    B.build_pdf(
        OUTPUT,
        story,
        title="Mais retorno com a mesma verba",
        footer_label="Bring Data · DevClub",
    )
    print(f"OK -> {OUTPUT}")


if __name__ == "__main__":
    main()

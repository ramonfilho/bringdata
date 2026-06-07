"""
Gera PDF mínimo: % de leads que já estudaram programação por tipo de campanha.

Dados extraídos de registros_ml (ledger novo, desde 23/05/2026) cruzando
survey_responses.estudouProgramacao com tipo de campanha derivado do
utm_campaign (Lead / Champion / Challenger).

Saída: V2/propostas_e_apresentacoes/estudou_prog_por_campanha.pdf
"""
from pathlib import Path

from reportlab.platypus import Paragraph, Spacer

import pdf_base as B

OUTPUT = Path(__file__).parent.parent / "propostas_e_apresentacoes" / "estudou_prog_por_campanha.pdf"
ST = B.styles()


def main():
    story = []

    story.append(B.P(
        "Já estudou programação? Por tipo de campanha",
        ST['h1'],
    ))
    story.append(B.P(
        "Recorte de <b>registros_ml</b> · janela 2026-05-23 → 2026-06-02 · leads com "
        "pesquisa preenchida e base_status=success.",
        ST['body'],
    ))

    # Tabela 1 — Geral
    story.append(B.P("Todos os decis", ST['h2']))
    header = [B.P(c, ST['th']) for c in (
        "Campanha", "Evento otimizado", "n", "Já estudou", "Nunca viu código",
    )]
    rows = [
        [B.P("Lead",       ST['td']), B.P("Lead",                     ST['td']),
         B.P("3.870",      ST['td']), B.P("22,1%",                    ST['td']),
         B.P("<b>77,9%</b>", ST['td'])],
        [B.P("Champion",   ST['td']), B.P("LeadQualifiedHighQuality", ST['td']),
         B.P("2.332",      ST['td']), B.P("37,6%",                    ST['td']),
         B.P("62,4%",      ST['td'])],
        [B.P("Challenger", ST['td']), B.P("HQLB",                     ST['td']),
         B.P("453",        ST['td']), B.P("<b>40,2%</b>",             ST['td']),
         B.P("59,8%",      ST['td'])],
    ]
    cw = [3.6 * 28.35, 5.6 * 28.35, 1.6 * 28.35, 2.6 * 28.35, 3.6 * 28.35]
    story.append(B.make_table(header, rows, cw))

    # Tabela 2 — D9-D10 (recorte top decil)
    story.append(B.P("Recorte D9–D10 (top decil do modelo)", ST['h2']))
    header2 = [B.P(c, ST['th']) for c in (
        "Campanha", "Evento otimizado", "n", "Já estudou", "Nunca viu código",
    )]
    rows2 = [
        [B.P("Lead",       ST['td']), B.P("Lead",                     ST['td']),
         B.P("1.231",      ST['td']), B.P("41,5%",                    ST['td']),
         B.P("58,5%",      ST['td'])],
        [B.P("Champion",   ST['td']), B.P("LeadQualifiedHighQuality", ST['td']),
         B.P("1.392",      ST['td']), B.P("49,5%",                    ST['td']),
         B.P("50,5%",      ST['td'])],
        [B.P("Challenger", ST['td']), B.P("HQLB",                     ST['td']),
         B.P("169",        ST['td']), B.P("<b>79,3%</b>",             ST['td']),
         B.P("<b>20,7%</b>", ST['td'])],
    ]
    story.append(B.make_table(header2, rows2, cw))

    # Tabela 3 — alinhamento com conversão da LP
    story.append(B.P("Comparativo com conversão da LP", ST['h2']))
    header3 = [B.P(c, ST['th']) for c in (
        "Campanha", "Conv LP (Leads/LPViews)", "Nunca viu código (geral)",
    )]
    rows3 = [
        [B.P("Lead",       ST['td']), B.P("~42%", ST['td']), B.P("77,9%", ST['td'])],
        [B.P("Champion",   ST['td']), B.P("~28%", ST['td']), B.P("62,4%", ST['td'])],
        [B.P("Challenger", ST['td']), B.P("~25%", ST['td']), B.P("59,8%", ST['td'])],
    ]
    cw3 = [5.0 * 28.35, 6.0 * 28.35, 6.0 * 28.35]
    story.append(B.make_table(header3, rows3, cw3))

    story.append(Spacer(1, 6))
    story.extend(B.callout(
        "<b>Leitura:</b> a LP comunica <i>“primeiro emprego como programador "
        "mesmo nunca tendo visto código”</i>. Quanto mais profundo o evento "
        "otimizado pela campanha (Lead → Champion → Challenger), mais técnica "
        "a audiência selecionada pela Meta e menor a aderência à narrativa "
        "“do zero”. No top decil da Challenger, 4 em 5 leads <b>já estudaram "
        "programação</b> — a frase “nunca viu código” desserve a maioria do "
        "público mais qualificado dessa campanha.",
        ST,
    ))

    B.build_pdf(
        OUTPUT,
        story,
        title="Já estudou programação? Por tipo de campanha",
        footer_label="Bring Data · DevClub",
    )
    print(f"OK -> {OUTPUT}")


if __name__ == "__main__":
    main()

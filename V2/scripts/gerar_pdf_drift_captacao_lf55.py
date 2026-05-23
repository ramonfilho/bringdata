"""
Gera PDF da análise de drift dia a dia da captação LF55 vs Top 5 ROAS.

Consolidação do estudo: a migração do front pra `lead_surveys` (iniciada ~12/05
22:27 BRT) cortou progressivamente a cobertura do ML/CAPI até zero em 18/05.
Em paralelo, o público que chega à LP foi se afastando do baseline histórico
(Top 5 ROAS atribuível 60d).

Saída: V2/propostas_e_apresentacoes/drift_captacao_lf55.pdf
"""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pg8000.native
from dotenv import load_dotenv
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, KeepTogether

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'scripts'))
load_dotenv(REPO / '.env')

import pdf_base as B
from reportlab.lib.colors import HexColor

from src.monitoring.data_quality import normalizar_categoria_para_comparacao
from scripts.perfil_audiencia import UNIFICATION

OUTPUT = REPO / 'propostas_e_apresentacoes' / 'drift_captacao_lf55.pdf'

C_RED   = HexColor('#b3261e')
C_GREEN = HexColor('#1d8a3e')
C_AMBER = HexColor('#aa7a17')


# ──────────────────────────────────────────────────────────
# Dados
# ──────────────────────────────────────────────────────────

DAYS = ['2026-05-12', '2026-05-13', '2026-05-14', '2026-05-15',
        '2026-05-16', '2026-05-17', '2026-05-18']
DAY_LABELS = ['12/5', '13/5', '14/5', '15/5', '16/5', '17/5', '18/5']

CATEGORICAL_COLS = ['O seu gênero:', 'Qual a sua idade?',
                    'O que você faz atualmente?',
                    'Atualmente, qual a sua faixa salarial?',
                    'Você possui cartão de crédito?',
                    'Já estudou programação?']

ORDINAL = {
    'Qual a sua idade?': ['<18', '18-24', '25-34', '35-44', '45-54', '55+'],
    'Atualmente, qual a sua faixa salarial?':
        ['Sem renda', 'Até R$2.000', 'R$2.001-3.000', 'R$3.001-5.000', 'Acima de R$5.000'],
}

THRESHOLD_PP = 2.0


def _conn():
    return pg8000.native.Connection(
        host=os.environ['RAILWAY_DB_HOST'], port=int(os.environ['RAILWAY_DB_PORT']),
        user=os.environ['RAILWAY_DB_USER'], password=os.environ['RAILWAY_DB_PASSWORD'],
        database=os.environ['RAILWAY_DB_NAME'], ssl_context=True,
    )


def _q_day(start_brt, end_brt_exclusive):
    s_utc = f"{start_brt} 03:00:00+00"
    e_utc = f"{end_brt_exclusive} 03:00:00+00"
    s_naive = f"{start_brt} 03:00:00"
    e_naive = f"{end_brt_exclusive} 03:00:00"
    conn = _conn()
    rows_l = conn.run(f'''
        SELECT pesquisa->>'genero', pesquisa->>'idade', pesquisa->>'ocupacao',
               pesquisa->>'faixaSalarial', pesquisa->>'cartaoCredito',
               pesquisa->>'estudouProgramacao'
        FROM "Lead"
        WHERE "createdAt" >= '{s_utc}' AND "createdAt" < '{e_utc}'
    ''')
    rows_s = conn.run(f'''
        SELECT genero, idade, ocupacao, "faixaSalarial",
               "cartaoCredito", "estudouProgramacao"
        FROM lead_surveys
        WHERE "submittedAt" >= '{s_naive}' AND "submittedAt" < '{e_naive}'
    ''')
    n_lead = conn.run(f'''
        SELECT COUNT(*) FROM "Lead"
        WHERE "createdAt" >= '{s_utc}' AND "createdAt" < '{e_utc}'
          AND decil IS NOT NULL
    ''')[0][0]
    n_surveys = conn.run(f'''
        SELECT COUNT(*) FROM lead_surveys
        WHERE "submittedAt" >= '{s_naive}' AND "submittedAt" < '{e_naive}'
    ''')[0][0]
    conn.close()
    df = pd.concat([
        pd.DataFrame(rows_l, columns=CATEGORICAL_COLS),
        pd.DataFrame(rows_s, columns=CATEGORICAL_COLS),
    ], ignore_index=True)
    return df, int(n_lead), int(n_surveys)


def normalize(s, col):
    s = s.fillna('(nulo)').astype(str).str.strip()
    s = s.replace({'': '(nulo)', 'None': '(nulo)', 'nan': '(nulo)'})
    s = s.apply(lambda v: '(nulo)' if v == '(nulo)' else
                (normalizar_categoria_para_comparacao(v) or '(nulo)'))
    mp = UNIFICATION.get(col, {})
    return s.map(lambda v: mp.get(v, v))


def classify(direction, delta):
    if delta is None or direction in (None, 'neutral', 'uncertain', 'insufficient_data'):
        return 'neutro'
    pos = direction in ('positive', 'very_positive')
    neg = direction in ('negative', 'very_negative')
    if delta > 0 and pos: return 'bom'
    if delta > 0 and neg: return 'ruim'
    if delta < 0 and neg: return 'bom'
    if delta < 0 and pos: return 'ruim'
    return 'neutro'


# ──────────────────────────────────────────────────────────
# Estilos
# ──────────────────────────────────────────────────────────

ST = B.styles()

# Estilos custom pra células coloridas e tabelas estreitas (9 colunas)
ST['th_c'] = ParagraphStyle('th_c', fontName='Helvetica-Bold', fontSize=7.5,
                            textColor=HexColor('#ffffff'), alignment=TA_CENTER, leading=10)
ST['th_l'] = ParagraphStyle('th_l', fontName='Helvetica-Bold', fontSize=7.5,
                            textColor=HexColor('#ffffff'), alignment=TA_LEFT, leading=10)
ST['td_c'] = ParagraphStyle('td_c', fontName='Helvetica', fontSize=7.5,
                            textColor=B.C_DARK_GRAY, alignment=TA_CENTER, leading=10)
ST['td_l'] = ParagraphStyle('td_l', fontName='Helvetica', fontSize=7.5,
                            textColor=B.C_DARK_GRAY, alignment=TA_LEFT, leading=10)
ST['td_b_l'] = ParagraphStyle('td_b_l', fontName='Helvetica-Bold', fontSize=7.5,
                              textColor=B.C_BLACK, alignment=TA_LEFT, leading=10)
ST['td_red'] = ParagraphStyle('td_red', fontName='Helvetica-Bold', fontSize=7.5,
                              textColor=C_RED, alignment=TA_CENTER, leading=10)
ST['td_green'] = ParagraphStyle('td_green', fontName='Helvetica-Bold', fontSize=7.5,
                                textColor=C_GREEN, alignment=TA_CENTER, leading=10)
ST['td_gray'] = ParagraphStyle('td_gray', fontName='Helvetica', fontSize=7.5,
                               textColor=B.C_MID_GRAY, alignment=TA_CENTER, leading=10)


def delta_cell(direction, delta):
    if delta is None:
        return Paragraph('—', ST['td_gray'])
    q = classify(direction, delta)
    s = f'{delta:+.1f}'
    if q == 'bom':   return Paragraph(s, ST['td_green'])
    if q == 'ruim':  return Paragraph(s, ST['td_red'])
    return Paragraph(s, ST['td_gray'])


# ──────────────────────────────────────────────────────────
# Story
# ──────────────────────────────────────────────────────────

def main():
    # Carrega baseline e direction map
    base = json.loads((REPO / 'configs/reference_audience_profiles/devclub.json').read_text())
    feats = base['categorical_features']
    ref_label = base['reference_pool']['label']
    ref_n = base['reference_pool']['n_leads']
    dmap = json.loads((REPO / 'configs/audience_direction_map.json').read_text()).get('direction_map', {})

    # Puxa dados por dia + totals
    day_dfs = []
    day_n_lead = []
    day_n_surveys = []
    for i, d in enumerate(DAYS):
        next_d = DAYS[i+1] if i + 1 < len(DAYS) else '2026-05-19'
        df, n_l, n_s = _q_day(d, next_d)
        day_dfs.append(df)
        day_n_lead.append(n_l)
        day_n_surveys.append(n_s)
    total_df = pd.concat(day_dfs, ignore_index=True)
    n_total = len(total_df)

    story = []

    # ── Cabeçalho
    story.append(B.P('Drift de público — captação LF55', ST['h1']))
    story.append(B.P(f'Cobertura ML decaindo (12 → 18/05) vs Top 5 ROAS · DevClub',
                     ST['body']))
    story.append(B.rule())

    # ── Contexto
    story.append(B.P('Contexto', ST['h2']))
    contexto = (
        'A captação do LF55 ocorreu entre 12 e 18 de maio de 2026. Na noite do dia 12 '
        '(~22:27 BRT) o front passou a gravar as respostas de pesquisa numa tabela nova '
        '(<font face="Courier" size="8.5">lead_surveys</font>), em vez da tabela '
        '<font face="Courier" size="8.5">Lead</font> usada até então. A migração foi '
        'progressiva: nos primeiros dias quase tudo ainda caía em <font face="Courier" size="8.5">Lead</font> '
        '(que aciona o pipeline de scoring e envia o evento <i>LeadQualified</i> ao Meta CAPI), '
        'mas a cada dia a fração que ia pra <font face="Courier" size="8.5">lead_surveys</font> '
        'crescia. Em 18/05 nenhum lead foi scoreado.'
    )
    story.append(B.P(contexto, ST['body']))
    story.append(B.P(
        'Esse documento mostra: (1) a curva de cobertura ML dia a dia; '
        '(2) o drift de cada característica de público dia a dia vs '
        f'<b>{ref_label}</b> (n={ref_n:,}, baseline já calibrado no projeto, '
        'arquivo <font face="Courier" size="8.5">configs/reference_audience_profiles/devclub.json</font>).',
        ST['body']))

    # ── Tabela 1: cobertura ML por dia
    story.append(B.P('Cobertura ML por dia BRT', ST['h2']))
    hdr = [
        Paragraph('Dia BRT', ST['th_l']),
        Paragraph('Lead scoreados', ST['th_c']),
        Paragraph('lead_surveys', ST['th_c']),
        Paragraph('Total', ST['th_c']),
        Paragraph('% scoreado', ST['th_c']),
    ]
    rows = []
    for i, d in enumerate(DAYS):
        nL = day_n_lead[i]; nS = day_n_surveys[i]; tot = nL + nS
        pct = (nL / tot * 100) if tot else 0
        # Cor da % scoreado: verde >=80, amber 40-80, red <40
        if pct >= 80:
            pct_style = ST['td_green']
        elif pct >= 40:
            pct_style = ParagraphStyle('amber', parent=ST['td_c'], textColor=C_AMBER,
                                       fontName='Helvetica-Bold')
        else:
            pct_style = ST['td_red']
        rows.append([
            Paragraph(d, ST['td_l']),
            Paragraph(f'{nL:,}', ST['td_c']),
            Paragraph(f'{nS:,}', ST['td_c']),
            Paragraph(f'{tot:,}', ST['td_c']),
            Paragraph(f'{pct:.1f}%', pct_style),
        ])
    total_l = sum(day_n_lead); total_s = sum(day_n_surveys); total_t = total_l + total_s
    rows.append([
        Paragraph('<b>TOTAL</b>', ST['td_b_l']),
        Paragraph(f'<b>{total_l:,}</b>', ST['td_c']),
        Paragraph(f'<b>{total_s:,}</b>', ST['td_c']),
        Paragraph(f'<b>{total_t:,}</b>', ST['td_c']),
        Paragraph(f'<b>{(total_l/total_t*100):.1f}%</b>', ST['td_c']),
    ])
    cw1 = [3*cm, 3.5*cm, 3.5*cm, 3*cm, 4*cm]
    story.append(B.make_table(hdr, rows, cw1))
    story.append(Spacer(1, 6))
    story.append(B.P(
        '<i>Lead scoreados</i> = leads cuja resposta de pesquisa caiu na tabela '
        '<font face="Courier" size="8.5">Lead</font> e foi scoreada pelo pipeline '
        '(Cloud Run → ML → CAPI). <i>lead_surveys</i> = leads que caíram só na tabela '
        'nova, sem scoring nem evento CAPI. Cobertura ML cai linearmente de 99% pra 0%.',
        ST['body']))

    # ── Tabela 2: a grande — drift dia a dia
    story.append(B.P('Drift por característica · dia a dia', ST['h2']))
    story.append(B.P(
        'Cada célula é a diferença em pontos percentuais (Δpp) entre o público do dia '
        'na LP e o baseline Top 5. Cor segue a regra do digest: '
        '<font color="#1d8a3e"><b>verde</b></font> = afastamento de categoria com lift '
        'baixo OU aproximação de categoria com lift alto; '
        '<font color="#b3261e"><b>vermelho</b></font> = o inverso; '
        '<font color="#777777"><b>cinza</b></font> = categoria sem leitura direcional '
        'confiável no <font face="Courier" size="8.5">audience_direction_map</font> '
        '(CI cruza 1.0). Só entram linhas com |Δpp| ≥ '
        f'{THRESHOLD_PP:.1f}pp em algum dia ou no agregado da captação.',
        ST['body']))

    # Calcula proporções por dia + total + monta linhas
    rows_by_feature = {}
    for col, entry in feats.items():
        if col == 'Tem computador/notebook?':
            continue  # lead_surveys não coleta — excluído pra consistência
        ref_props = entry['proportions']
        label = entry['label']

        day_props = []
        for ddf in day_dfs:
            if col not in ddf.columns or len(ddf) == 0:
                day_props.append({}); continue
            s = normalize(ddf[col], col)
            s = s[s != '(nulo)']
            day_props.append((s.value_counts() / len(s)).to_dict() if len(s) > 0 else {})

        s = normalize(total_df[col], col)
        s = s[s != '(nulo)']
        total_props = (s.value_counts() / len(s)).to_dict() if len(s) > 0 else {}

        all_cats = set(ref_props)
        for dp in day_props: all_cats |= set(dp)
        all_cats |= set(total_props)

        out = []
        for cat in all_cats:
            ref_p = ref_props.get(cat, 0) * 100
            day_pcts = [dp.get(cat, 0) * 100 for dp in day_props]
            total_pct = total_props.get(cat, 0) * 100
            day_deltas = [dp - ref_p for dp in day_pcts]
            total_delta = total_pct - ref_p
            max_abs = max([abs(d) for d in day_deltas] + [abs(total_delta)])
            if max_abs < THRESHOLD_PP:
                continue
            direction = (dmap.get(col, {}).get(cat, {}) or {}).get('direction')
            out.append({
                'label': label, 'cat': cat, 'ref': ref_p,
                'day_deltas': day_deltas, 'total_delta': total_delta,
                'direction': direction, 'max_abs': max_abs,
            })
        ord_list = ORDINAL.get(col)
        if ord_list:
            idx = {c: i for i, c in enumerate(ord_list)}
            out.sort(key=lambda r: idx.get(r['cat'], 99))
        else:
            out.sort(key=lambda r: -r['max_abs'])
        rows_by_feature[col] = out

    # Dedup binárias
    binary = {c for c, e in feats.items() if len(e.get('proportions', {})) == 2}
    for col in binary:
        rs = rows_by_feature.get(col, [])
        if len(rs) == 2:
            rs.sort(key=lambda r: -r['max_abs'])
            rows_by_feature[col] = [rs[0]]

    group_order = sorted(rows_by_feature.keys(),
                         key=lambda c: -max((r['max_abs'] for r in rows_by_feature[c]),
                                            default=0))

    # Header da tabela grande
    n_per_day = [len(d) for d in day_dfs]
    hdr2 = [Paragraph('Característica', ST['th_l']),
            Paragraph('Top%', ST['th_c'])]
    for lbl, n in zip(DAY_LABELS, n_per_day):
        hdr2.append(Paragraph(f'{lbl}<br/><font size="6">n={n}</font>', ST['th_c']))
    hdr2.append(Paragraph(f'Lanç<br/><font size="6">n={n_total}</font>', ST['th_c']))

    body_rows = []
    for col in group_order:
        for r in rows_by_feature[col]:
            row_cells = [
                Paragraph(f'{r["label"]}: {r["cat"]}', ST['td_l']),
                Paragraph(f'{r["ref"]:.1f}%', ST['td_c']),
            ]
            for d in r['day_deltas']:
                row_cells.append(delta_cell(r['direction'], d))
            row_cells.append(delta_cell(r['direction'], r['total_delta']))
            body_rows.append(row_cells)

    # Larguras: label 4.8cm + Top% 1.2cm + 7 days × 1.15cm = 8.05 + Lanç 1.45cm = 15.5cm
    cw2 = [4.8*cm, 1.2*cm] + [1.15*cm]*7 + [1.45*cm]
    story.append(B.make_table(hdr2, body_rows, cw2))
    story.append(Spacer(1, 8))

    # ── Resumo executivo (callout)
    resumo = (
        f'<b>Resumo:</b> o público que chegou à LP nos primeiros 2 dias (12-13/05, '
        f'cobertura ML ≥82%) é praticamente idêntico ao Top 5 — chega a ter +9,2pp em '
        f'18-24 e +2-3pp em 25-34 (faixas com lift bom historicamente). A partir de '
        f'14-15/05, conforme a cobertura ML cai abaixo de 66%, a audiência começa a '
        f'envelhecer (45-54 e 55+ sobem progressivamente) e perde "técnico" (já estudou '
        f'programação e CLT caem). Em 17/05, com cobertura ML em 3%, o drift máximo '
        f'chega a 17,6pp em 45-54 e -14,9pp em 18-24. CLT é o único campo '
        f'<b>constantemente</b> ruim (-4 a -7pp todos os dias) — problema estrutural do '
        f'LF55, independente da migração.'
    )
    story.extend(B.callout(resumo, ST))

    # ── Leitura linha a linha
    story.append(B.P('Leitura por categoria', ST['h2']))
    leituras = [
        ('Idade 18-24', 'começa +9,2pp acima do Top-5 (mais jovem que o histórico), '
                        'inverte para -15pp em 17/05 — categoria com lift baixo, sair dela '
                        'é direcionalmente bom mas a inversão é violenta.'),
        ('Idade 45-54 e 55+', 'praticamente neutras nos primeiros 2 dias, sobem '
                              'continuamente até +17,6pp e +11,8pp em 17/05. Direction '
                              'incerta no map (CI cruza 1.0), mas a magnitude do shift é '
                              'inédita.'),
        ('Já estudou programação Sim', 'estável em torno do Top-5 nos 2 primeiros dias '
                                       '(+2,2/+0,2pp), despenca para -15,2pp em 17/05. '
                                       'Direction positive — perder essa categoria é ruim.'),
        ('CLT/funcionário público', 'constantemente -4 a -7pp em todos os dias. Não é '
                                    'consequência da migração — é problema do mix da '
                                    'audiência captada no LF55 como um todo.'),
        ('Tem cartão de crédito Sim', 'indiferente nos 2 primeiros dias, despenca a '
                                      'partir de 16/05 (mesmo timing da queda de "já '
                                      'estudou prog"). Direction positive — perder = ruim.'),
        ('Gênero Masculino', 'cai de -0,2pp para -11,5pp ao longo da semana. Direction '
                             'incerta no map; o shift é grande mas a leitura direcional '
                             'é cinza.'),
    ]
    for titulo, txt in leituras:
        story.append(Paragraph(f'<b>{titulo}</b> — {txt}', ST['li'], bulletText=u'•'))

    # ── Notas metodológicas
    story.append(B.P('Notas metodológicas', ST['h2']))
    notas = [
        ('Baseline', f'<b>{ref_label}</b> (LF45, LF44, LF46, LF41, LF43), '
                     f'pool de {ref_n:,} leads. Snapshot em '
                     '<font face="Courier" size="8.5">configs/reference_audience_profiles/devclub.json</font>.'),
        ('Cor das células', 'rule = direction(audience_direction_map) × sign(Δpp). '
                            'Sem porta de magnitude — qualquer Δ na direção "ruim" vira '
                            'vermelho, mesmo +0,3pp. Isso é fiel ao digest atual '
                            '(<font face="Courier" size="8.5">_classify_drift_quality</font> '
                            'em <font face="Courier" size="8.5">data_quality.py</font>).'),
        ('Threshold de visibilidade', f'2pp em algum dia OU no agregado. Linhas com '
                                      'drift menor não aparecem na tabela.'),
        ('Fonte', 'UNION das tabelas <font face="Courier" size="8.5">Lead.pesquisa</font> '
                  'e <font face="Courier" size="8.5">lead_surveys</font> no Railway. '
                  'A coluna "Tem computador/notebook?" foi excluída — '
                  '<font face="Courier" size="8.5">lead_surveys</font> não coleta esse '
                  'campo, então incluí-la criaria viés temporal.'),
        ('Categorias binárias', 'em features com 2 categorias (Gênero, Cartão, Já '
                                'estudou prog), só uma aparece na tabela — a outra é '
                                'redundante.'),
    ]
    for titulo, txt in notas:
        story.append(Paragraph(f'<b>{titulo}.</b> {txt}', ST['li'], bulletText='•'))

    # ── Build
    B.build_pdf(OUTPUT, story,
                title='Drift de público — captação LF55',
                footer_label='Bring Data · Drift LF55 · captação 12-18/05/2026')
    print(f'PDF gerado: {OUTPUT}')


if __name__ == '__main__':
    main()

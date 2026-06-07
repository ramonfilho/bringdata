"""
Gera PDF explicativo do Random Forest usado pelo DevClub.

Foco: explicar p/ o time como o modelo funciona, com exemplos de split como em
curso de ML. Mínimo texto, sem fórmulas/probabilidades.

Base de números: Challenger abr28 (run_id 5d158f0aa6e54b489498470446194a6c) —
metadata + .pkl locais em V2/mlruns/1/.

Saída: V2/propostas_e_apresentacoes/random_forest_explicado.pdf
"""
from __future__ import annotations

import io
import json
import pickle
import statistics
import sys
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, Spacer, KeepTogether, Table, TableStyle, HRFlowable
from reportlab.lib.colors import HexColor

sys.path.insert(0, str(Path(__file__).parent))
from pdf_base import (
    styles, P, callout, rule, build_pdf,
    C_BLACK, C_DARK_GRAY, C_MID_GRAY, C_LIGHT_GRAY, C_GREEN, C_WHITE, C_RULE,
    CONTENT_WIDTH,
)


ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / "mlruns" / "1" / "5d158f0aa6e54b489498470446194a6c"
OUTPUT = ROOT / "propostas_e_apresentacoes" / "random_forest_explicado.pdf"


# Tradução de feature one-hot para pergunta humana
HUMAN = {
    "Tem_computador_notebook_sim":            ("Tem computador?",                   "Sim",  "Não"),
    "Tem_computador_notebook_nao":            ("Tem computador?",                   "Não",  "Sim"),
    "J_estudou_programa_o_Sim":               ("Já estudou programação?",           "Sim",  "Não"),
    "J_estudou_programa_o_N_o":               ("Já estudou programação?",           "Não",  "Sim"),
    "Medium_Linguagem_programacao":           ("Campanha 'Linguagem'?",             "Sim",  "Não"),
    "Medium_Aberto":                          ("Campanha 'Aberto'?",                "Sim",  "Não"),
    "Medium_Outros":                          ("Campanha 'Outros'?",                "Sim",  "Não"),
    "Medium_Lookalike_2pct_Cadastrados":      ("Lookalike 2%?",                     "Sim",  "Não"),
    "Voc_possui_cart_o_de_cr_dito_sim":       ("Tem cartão de crédito?",            "Sim",  "Não"),
    "Voc_possui_cart_o_de_cr_dito_nao":       ("Tem cartão de crédito?",            "Não",  "Sim"),
    "Atualmente_qual_a_sua_faixa_salarial_nao_tenho_renda":             ("Sem renda?",           "Sim",  "Não"),
    "Atualmente_qual_a_sua_faixa_salarial_mais_de_r5001_reais_ao_mes":  ("Renda > 5 mil?",       "Sim",  "Não"),
    "Atualmente_qual_a_sua_faixa_salarial_entre_r3001_a_r5000_reais_ao_mes": ("Renda 3 a 5 mil?", "Sim",  "Não"),
    "Atualmente_qual_a_sua_faixa_salarial_entre_r2001_a_r3000_reais_ao_mes": ("Renda 2 a 3 mil?", "Sim",  "Não"),
    "Atualmente_qual_a_sua_faixa_salarial_entre_r1000_a_r2000_reais_ao_mes": ("Renda 1 a 2 mil?", "Sim",  "Não"),
    "O_que_mais_voc_quer_ver_no_evento_fazer_transicao_de_carreira_e_conseguir_meu_primeiro_emprego_na_area":
        ("Quer transição p/ tecnologia?", "Sim", "Não"),
    "O_que_mais_voc_quer_ver_no_evento_quero_saber_se_e_para_mim":
        ("'Quero saber se é p/ mim'?", "Sim", "Não"),
    "O_que_mais_voc_quer_ver_no_evento_fazer_um_projeto_na_pratica":
        ("Quer projeto prático?", "Sim", "Não"),
    "O_que_mais_voc_quer_ver_no_evento_a_aula_com_a_recrutadora":
        ("Quer aula c/ recrutadora?", "Sim", "Não"),
    "O_que_mais_voc_quer_ver_no_evento_fazer_freelancer_como_programador":
        ("Quer ser freelancer?", "Sim", "Não"),
    "O_que_voc_faz_atualmente_nao_trabalho_e_nem_estudo":
        ("Não trabalha nem estuda?", "Sim", "Não"),
    "O_que_voc_faz_atualmente_sou_cltfuncionario_publico":
        ("É CLT / serv. público?", "Sim", "Não"),
    "O_que_voc_faz_atualmente_sou_apenas_estudante":
        ("Só estuda?", "Sim", "Não"),
    "O_que_voc_faz_atualmente_sou_autonomo":
        ("É autônomo?", "Sim", "Não"),
    "O_seu_g_nero_Masculino":                 ("Gênero masculino?",                 "Sim",  "Não"),
    "O_seu_g_nero_Feminino":                  ("Gênero feminino?",                  "Sim",  "Não"),
    "Voc_j_fez_faz_pretende_fazer_faculdade_N_o": ("Faculdade no plano?",           "Não",  "Sim"),
    "Voc_j_fez_faz_pretende_fazer_faculdade_Sim": ("Faculdade no plano?",           "Sim",  "Não"),
    "Qual_a_sua_idade_menos_de_18_anos":      ("Menor de 18?",                      "Sim",  "Não"),
    "Qual_a_sua_idade_18_24_anos":            ("Entre 18 e 24?",                    "Sim",  "Não"),
    "Qual_a_sua_idade_25_34_anos":            ("Entre 25 e 34?",                    "Sim",  "Não"),
    "Source_facebook_ads":                    ("Veio do Facebook?",                 "Sim",  "Não"),
    "Source_outros":                          ("Veio de outra fonte?",              "Sim",  "Não"),
    "nome_comprimento":                       ("Nome longo?",                       "Sim",  "Não"),
    "dia_semana":                             ("Dia útil?",                         "Sim",  "Não"),
}


def humanize(feat: str) -> tuple[str, str, str]:
    if feat in HUMAN:
        return HUMAN[feat]
    # fallback genérico (não esperado se modelo for o atual)
    return (feat.replace("_", " "), "Sim", "Não")


# ─────────────────────────────────────────────────────────────────────────────
# Carrega modelo e métricas
# ─────────────────────────────────────────────────────────────────────────────
def load_model_stats():
    with open(RUN_DIR / "artifacts" / "model" / "model.pkl", "rb") as f:
        m = pickle.load(f)
    feats = list(m.feature_names_in_)
    sizes = [t.tree_.node_count for t in m.estimators_]
    leaves = [t.tree_.n_leaves for t in m.estimators_]
    depths = [t.tree_.max_depth for t in m.estimators_]
    meta = json.loads((RUN_DIR / "artifacts" / "model_metadata.json").read_text())
    # Para reverter class_weight=balanced e obter taxas reais por folha
    n_train = meta["training_data"]["training_records"]
    n_pos   = meta["training_data"]["target_distribution"]["training_positive_count"]
    baseline = n_pos / n_train       # ~1,56% no treino
    w_pos = n_train / (2 * n_pos)    # peso de classe positivo
    return {
        "model": m,
        "feats": feats,
        "n_trees": m.n_estimators,
        "max_depth": m.max_depth,
        "n_features": m.n_features_in_,
        "nodes_total": sum(sizes),
        "nodes_mean": round(statistics.mean(sizes)),
        "leaves_total": sum(leaves),
        "leaves_mean": round(statistics.mean(leaves)),
        "depth_mean": round(statistics.mean(depths)),
        "auc": meta["performance_metrics"]["auc"],
        "top3": meta["performance_metrics"]["top3_decil_concentration"],
        "top5": meta["performance_metrics"]["top5_decil_concentration"],
        "lift_d10": meta["performance_metrics"]["lift_maximum"],
        "n_records": meta["training_data"]["total_records"],
        "trained_at": meta["model_info"]["trained_at"][:10],
        "baseline": baseline,
        "w_pos": w_pos,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Diagrama: uma árvore por dentro (profundidade 3)
# ─────────────────────────────────────────────────────────────────────────────
MAX_DEPTH_DIDACTIC = 4  # profundidade exibida no diagrama (16 folhas)
TREE_INDEX = 107  # árvore escolhida: sem PERGUNTA humana repetida nos 4 níveis
                  #                    + distribuição equilibrada ALTA/MÉDIA/BAIXA


def real_pos_rate(tree, nid: int, w_pos: float) -> float:
    """Taxa REAL de compradores na folha, desfazendo o class_weight=balanced.

    tree.value armazena proporções (somam 1.0) já reponderadas pelo class_weight.
    Para recuperar o número de positivos reais:
        weighted_pos = value[1] × weighted_n_node_samples
        n_pos_real   = weighted_pos / w_pos
        rate_real    = n_pos_real / n_node_samples
    """
    weighted_pos = tree.value[nid][0][1] * tree.weighted_n_node_samples[nid]
    n_pos_est = weighted_pos / w_pos
    n_total = tree.n_node_samples[nid]
    return n_pos_est / n_total if n_total > 0 else 0.0


def band_for_lift(lift: float) -> tuple[str, str]:
    """Faixa qualitativa pelo lift sobre a baseline de conversão."""
    if lift >= 2.0:
        return ("ALTA",  "#1d8a3e")
    if lift >= 0.7:
        return ("MÉDIA", "#52a86b")
    return ("BAIXA", "#999999")


def draw_tree(stats) -> bytes:
    """Desenha árvore escolhida até profundidade fixa com perguntas humanas."""
    m = stats["model"]
    feats = stats["feats"]
    t = m.estimators_[TREE_INDEX].tree_
    D = MAX_DEPTH_DIDACTIC

    # Coleta nós BFS até profundidade D (precisa vir antes do label, pra ranquear folhas)
    levels: dict[int, list[tuple[int, int]]] = {0: [(0, -1)]}  # node_id, parent_node_id
    for d in range(0, D):
        next_lvl = []
        for nid, _ in levels[d]:
            l_ = t.children_left[nid]
            r_ = t.children_right[nid]
            if l_ >= 0:
                next_lvl.append((l_, nid))
            if r_ >= 0:
                next_lvl.append((r_, nid))
        levels[d + 1] = next_lvl

    # Atribui faixa por lift sobre a baseline (taxa real, sem class_weight)
    leaf_ids = [nid for nid, _ in levels[D]]
    band = {}
    for nid in leaf_ids:
        pr = real_pos_rate(t, nid, stats["w_pos"])
        lift = pr / stats["baseline"] if stats["baseline"] > 0 else 0
        label, color = band_for_lift(lift)
        band[nid] = ("Intenção", label, color)

    def value_label(node_id):
        return band[node_id]

    # Espaço virtual: largura proporcional ao número de folhas
    X_MAX = 20.0
    Y_LEVELS = {0: 5.4, 1: 4.2, 2: 3.0, 3: 1.8, 4: 0.6}
    positions = {}
    for d, nodes in levels.items():
        n = len(nodes)
        if n == 0:
            continue
        spacing = X_MAX / (n + 1)
        for i, (nid, _) in enumerate(nodes, start=1):
            positions[nid] = (spacing * i, Y_LEVELS[d])

    fig, ax = plt.subplots(figsize=(11.5, 5.4))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.set_xlim(0, X_MAX)
    ax.set_ylim(0, 6)
    ax.axis("off")

    # Largura/altura das caixas por nível — encolhem conforme aumenta o número de nós
    BOX_H = 0.42
    def box_width(d):
        n = len(levels[d])
        spacing = X_MAX / (n + 1)
        if d == D:  # folhas
            return min(1.05, spacing * 0.78)
        return min(1.75, spacing * 0.82)

    # Desenha arestas
    for d in range(1, D + 1):
        for nid, parent in levels[d]:
            px, py = positions[parent]
            x, y = positions[nid]
            is_right = (t.children_right[parent] == nid)
            ax.plot([px, x], [py - BOX_H / 2, y + BOX_H / 2],
                    color="#bbbbbb", linewidth=0.9, zorder=1)
            # rótulo Sim/Não no meio da aresta
            parent_feat = feats[t.feature[parent]]
            _, yes_lbl, no_lbl = humanize(parent_feat)
            lbl = yes_lbl if is_right else no_lbl
            mid_x = (px + x) / 2
            mid_y = (py + y) / 2
            # fonte menor em níveis mais profundos
            fs = 6.5 if d <= 2 else 5.5
            ax.text(mid_x, mid_y, lbl, fontsize=fs, color="#777777",
                    ha="center", va="center",
                    bbox=dict(boxstyle="round,pad=0.12", facecolor="white",
                              edgecolor="#dddddd", linewidth=0.4))

    # Desenha nós
    for d in range(0, D + 1):
        bw = box_width(d)
        for nid, _ in levels[d]:
            x, y = positions[nid]
            is_leaf = (t.children_left[nid] < 0 or d == D)
            if is_leaf:
                hdr, val, color = value_label(nid)
                box = mpatches.FancyBboxPatch(
                    (x - bw / 2, y - BOX_H / 2), bw, BOX_H,
                    boxstyle="round,pad=0.02,rounding_size=0.06",
                    facecolor=color, edgecolor=color, linewidth=0,
                )
                ax.add_patch(box)
                # em folhas pequenas, só mostra o rótulo (sem o "Intenção" cabeçalho)
                if bw < 0.9:
                    ax.text(x, y, val, fontsize=6.5, color="white",
                            ha="center", va="center", fontweight="bold")
                else:
                    ax.text(x, y + 0.06, hdr, fontsize=6.0, color="white", ha="center", va="center")
                    ax.text(x, y - 0.10, val, fontsize=8.0, color="white",
                            ha="center", va="center", fontweight="bold")
            else:
                feat = feats[t.feature[nid]]
                question, _, _ = humanize(feat)
                # quebra com textwrap (não trunca); fonte adaptativa por nível
                if d <= 1:
                    wrap_w, fs = 18, 7.2
                elif d == 2:
                    wrap_w, fs = 14, 6.4
                else:  # nível 3 — caixas mais estreitas
                    wrap_w, fs = 12, 5.6
                q_render = textwrap.fill(question, width=wrap_w,
                                          break_long_words=False)
                box = mpatches.FancyBboxPatch(
                    (x - bw / 2, y - BOX_H / 2), bw, BOX_H,
                    boxstyle="round,pad=0.02,rounding_size=0.06",
                    facecolor="#f5f5f5", edgecolor="#cccccc", linewidth=0.6,
                )
                ax.add_patch(box)
                ax.text(x, y, q_render, fontsize=fs, color="#1a1a1a",
                        ha="center", va="center")

    plt.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# Diagrama: a árvore inteira (profundidade completa), sem texto
# ─────────────────────────────────────────────────────────────────────────────
def draw_full_tree(stats) -> bytes:
    """Esqueleto da mesma árvore (TREE_INDEX) até a profundidade máxima.

    Sem texto — só estrutura + cores nas folhas, com limiar absoluto sobre
    a proporção de compradores em cada folha.
    """
    m = stats["model"]
    t = m.estimators_[TREE_INDEX].tree_
    D = m.max_depth  # profundidade real (8)

    # BFS até a profundidade D, mas só estendendo nós não-folha
    levels: dict[int, list[tuple[int, int]]] = {0: [(0, -1)]}
    for d in range(0, D):
        nxt = []
        for nid, _ in levels[d]:
            l_ = t.children_left[nid]
            r_ = t.children_right[nid]
            if l_ >= 0:
                nxt.append((l_, nid))
            if r_ >= 0:
                nxt.append((r_, nid))
        levels[d + 1] = nxt

    # Coleta TODAS as folhas reais; cor por lift sobre baseline
    band = {}
    for d in range(0, D + 1):
        for nid, _ in levels[d]:
            is_leaf = (t.children_left[nid] < 0) or (d == D)
            if is_leaf:
                pr = real_pos_rate(t, nid, stats["w_pos"])
                lift = pr / stats["baseline"] if stats["baseline"] > 0 else 0
                _, color = band_for_lift(lift)
                band[nid] = color

    # Layout: cada nível distribui horizontalmente
    X_MAX = 100.0  # virtual
    Y_LEVELS = {d: (D - d) for d in range(D + 1)}
    positions = {}
    for d, nodes in levels.items():
        n = len(nodes)
        if n == 0:
            continue
        spacing = X_MAX / (n + 1)
        for i, (nid, _) in enumerate(nodes, start=1):
            positions[nid] = (spacing * i, Y_LEVELS[d])

    fig, ax = plt.subplots(figsize=(11.5, 5.0))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.set_xlim(0, X_MAX)
    ax.set_ylim(-0.5, D + 0.5)
    ax.axis("off")

    # Arestas (finas, claras)
    for d in range(1, D + 1):
        for nid, parent in levels[d]:
            if parent < 0:
                continue
            px, py = positions[parent]
            x, y = positions[nid]
            ax.plot([px, x], [py, y], color="#d0d0d0", linewidth=0.35, zorder=1)

    # Nós: leaves coloridas, internos cinzas pequenos
    for d in range(0, D + 1):
        for nid, _ in levels[d]:
            x, y = positions[nid]
            if nid in band:  # folha
                ax.scatter(x, y, s=14, color=band[nid], edgecolor=band[nid],
                           linewidth=0, zorder=3)
            else:
                ax.scatter(x, y, s=6, color="#888888", edgecolor="#888888",
                           linewidth=0, zorder=2)

    # Legenda enxuta no canto superior
    from matplotlib.lines import Line2D
    handles = [
        Line2D([], [], marker="o", color="w", markerfacecolor="#1d8a3e",
               markersize=7, label="folha ALTA"),
        Line2D([], [], marker="o", color="w", markerfacecolor="#52a86b",
               markersize=7, label="folha MÉDIA"),
        Line2D([], [], marker="o", color="w", markerfacecolor="#999999",
               markersize=7, label="folha BAIXA"),
        Line2D([], [], marker="o", color="w", markerfacecolor="#888888",
               markersize=4.5, label="nó intermediário"),
    ]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, -0.05),
              ncol=4, frameon=False, fontsize=7.5)

    plt.tight_layout(pad=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# Diagrama: floresta → voto médio → decil
# ─────────────────────────────────────────────────────────────────────────────
def draw_forest_flow(stats) -> bytes:
    fig, ax = plt.subplots(figsize=(10.5, 2.6))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 2.6)
    ax.axis("off")

    # Lead
    box = mpatches.FancyBboxPatch((0.1, 0.9), 1.4, 0.8,
                                  boxstyle="round,pad=0.02,rounding_size=0.1",
                                  facecolor="#eef4fb", edgecolor="#c9d9ec", linewidth=1)
    ax.add_patch(box)
    ax.text(0.8, 1.45, "Lead", fontsize=9, ha="center", fontweight="bold")
    ax.text(0.8, 1.15, "pesquisa\npreenchida", fontsize=7, ha="center", color="#555")

    # 300 árvores (representadas por pilha de ~6 árvores menores)
    base_x = 2.9
    for i in range(6):
        y_off = 1.95 - i * 0.18
        # tronco
        ax.plot([base_x + i * 0.06, base_x + i * 0.06], [y_off - 0.18, y_off], color="#999", linewidth=0.6)
        # copa
        ax.add_patch(mpatches.Circle((base_x + i * 0.06, y_off), 0.13,
                                     facecolor="#52a86b", edgecolor="#1d8a3e", linewidth=0.4, alpha=0.85))
    ax.text(base_x + 0.3, 0.45, f"{stats['n_trees']} árvores", fontsize=8.5,
            ha="center", color="#444", fontweight="bold")
    ax.text(base_x + 0.3, 0.2, "cada uma vota", fontsize=7, ha="center", color="#777")

    # Seta 1
    ax.annotate("", xy=(2.5, 1.3), xytext=(1.6, 1.3),
                arrowprops=dict(arrowstyle="->", color="#888", lw=1.2))

    # Seta 2
    ax.annotate("", xy=(5.0, 1.3), xytext=(4.1, 1.3),
                arrowprops=dict(arrowstyle="->", color="#888", lw=1.2))

    # Média
    box2 = mpatches.FancyBboxPatch((5.0, 0.95), 1.6, 0.7,
                                   boxstyle="round,pad=0.02,rounding_size=0.1",
                                   facecolor="#fff7e0", edgecolor="#e8b800", linewidth=1)
    ax.add_patch(box2)
    ax.text(5.8, 1.42, "Voto médio", fontsize=8.5, ha="center", fontweight="bold")
    ax.text(5.8, 1.12, "score do lead", fontsize=7, ha="center", color="#555")

    # Seta 3
    ax.annotate("", xy=(7.0, 1.3), xytext=(6.7, 1.3),
                arrowprops=dict(arrowstyle="->", color="#888", lw=1.2))

    # Decis (10 caixinhas)
    deci_x = 7.05
    for i in range(10):
        c = "#1d8a3e" if i >= 7 else "#52a86b" if i >= 5 else "#cccccc"
        ax.add_patch(mpatches.Rectangle((deci_x + i * 0.28, 1.05), 0.24, 0.5,
                                         facecolor=c, edgecolor="white", linewidth=0.8))
        ax.text(deci_x + i * 0.28 + 0.12, 1.3, f"D{i+1}", fontsize=6.2,
                ha="center", color="white", fontweight="bold")
    ax.text(deci_x + 1.4, 0.7, "decil do lead (D1 a D10)", fontsize=8, ha="center", color="#444")
    ax.text(deci_x + 1.4, 0.45, "→ valor enviado ao Meta", fontsize=7.5, ha="center", color="#777")

    plt.tight_layout(pad=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# Diagrama: concentração de compras nos decis altos
# ─────────────────────────────────────────────────────────────────────────────
def draw_concentration(stats) -> bytes:
    """Barra horizontal mostrando onde estão as compras."""
    top3 = stats["top3"]
    top5 = stats["top5"]
    # restante
    other = 100 - top5

    fig, ax = plt.subplots(figsize=(10.5, 1.7))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Top 3 (D8-D10)
    ax.add_patch(mpatches.Rectangle((0, 0.3), top3, 0.4,
                                     facecolor="#1d8a3e", edgecolor="white"))
    ax.text(top3 / 2, 0.5, f"Top 3 decis  ·  ~{top3:.0f}% das compras",
            fontsize=9, ha="center", va="center", color="white", fontweight="bold")

    # D6-D7 (entre top3 e top5)
    mid_width = top5 - top3
    ax.add_patch(mpatches.Rectangle((top3, 0.3), mid_width, 0.4,
                                     facecolor="#52a86b", edgecolor="white"))
    if mid_width > 12:
        ax.text(top3 + mid_width / 2, 0.5, f"D6–D7  ·  ~{mid_width:.0f}%",
                fontsize=8, ha="center", va="center", color="white")

    # restante
    ax.add_patch(mpatches.Rectangle((top5, 0.3), other, 0.4,
                                     facecolor="#cccccc", edgecolor="white"))
    ax.text(top5 + other / 2, 0.5, f"D1–D5  ·  ~{other:.0f}%",
            fontsize=8, ha="center", va="center", color="#555")

    # Labels topo
    ax.text(0, 0.85, "100% dos compradores rastreados pelo modelo",
            fontsize=8, color="#777", ha="left")

    plt.tight_layout(pad=0.2)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────────────────────────────────────
def build(stats):
    st = styles()
    story = []

    # Capa enxuta
    story.append(P("Como funciona o modelo de score de leads", st["h1"]))
    story.append(P(
        "Random Forest  ·  DevClub  ·  versão de produção do braço A/B (abr/2026)",
        ParagraphStyle_subtitle(),
    ))
    story.append(rule())

    # 1. A ideia
    story.append(P("A ideia", st["h2"]))
    story.append(P(
        "O modelo é um <b>conjunto de árvores de decisão</b>. Cada árvore faz "
        "uma sequência de perguntas binárias sobre o lead e aponta para um "
        "rótulo de intenção. O score final é a média do que todas as árvores apontam.",
        st["body"],
    ))

    # 2. Uma árvore por dentro
    story.append(P("Uma árvore, por dentro", st["h2"]))
    story.append(P(
        f"Uma das {stats['n_trees']} árvores do modelo, mostrada até profundidade "
        f"{MAX_DEPTH_DIDACTIC} (das {stats['max_depth']} que ela tem). Cada caixa "
        "cinza é uma pergunta — escolhida no treino por separar compradores de não "
        "compradores melhor que as alternativas naquele ponto. As folhas coloridas "
        "indicam a intenção do lead que cai ali.",
        st["body"],
    ))
    img1 = Image(io.BytesIO(draw_tree(stats)), width=CONTENT_WIDTH, height=8.0 * cm)
    story.append(KeepTogether([img1]))
    story.append(Spacer(1, 4))
    story.append(P(
        "Cor das folhas comparada à taxa de compra média da base: verde-escuro = "
        "folhas com taxa bem acima da média; verde-claro = folhas próximas da média; "
        "cinza = folhas abaixo da média (a maioria dos leads cai aqui). Compradores "
        "são raros — só ~1,5% dos leads compram —, então mesmo as folhas verde-escuras "
        "concentram poucos compradores em termos absolutos; o ganho do modelo é "
        "<i>quantos compradores a mais</i> que a base bruta cada folha entrega.",
        ParagraphStyle_footnote(),
    ))

    # 2b. A árvore inteira (escala completa, sem texto)
    story.append(P("A mesma árvore, até o fim", st["h2"]))
    story.append(P(
        f"Aqui está a árvore inteira — todos os {stats['max_depth']} níveis — sem as perguntas, "
        "só com a estrutura e a cor de cada folha.",
        st["body"],
    ))
    img_full = Image(io.BytesIO(draw_full_tree(stats)), width=CONTENT_WIDTH, height=7.4 * cm)
    story.append(KeepTogether([img_full]))

    # 3. Por que muitas árvores
    story.append(P("Por que muitas árvores", st["h2"]))
    story.append(P(
        "Uma árvore sozinha decora a base e erra em casos novos. A floresta resolve isso "
        "treinando muitas árvores em paralelo — cada uma vê uma amostra diferente dos leads "
        f"e, em cada split, escolhe entre uma fração diferente das {stats['n_features']} "
        f"perguntas disponíveis. Os erros individuais se cancelam na média dos {stats['n_trees']} votos.",
        st["body"],
    ))

    # Caixa de stats
    story.extend(stats_callout(stats, st))

    # 4. Do lead ao decil — manter título + texto + imagem na mesma página
    img2 = Image(io.BytesIO(draw_forest_flow(stats)), width=CONTENT_WIDTH, height=4.2 * cm)
    story.append(KeepTogether([
        P("Do lead ao decil", st["h2"]),
        P(
            "Quando um lead preenche a pesquisa, ele atravessa todas as árvores. "
            "Cada uma vota. A média dos votos é o score; em seguida o score é "
            "convertido no decil (D1 a D10) que vai junto do evento enviado ao Meta.",
            st["body"],
        ),
        img2,
    ]))

    # 5. Assertividade
    story.append(P("Assertividade alcançada", st["h2"]))
    story.append(P(
        "O modelo é avaliado pela capacidade de empurrar os leads que compram "
        "para os decis altos. No conjunto de teste deste modelo:",
        st["body"],
    ))
    img3 = Image(io.BytesIO(draw_concentration(stats)), width=CONTENT_WIDTH, height=2.6 * cm)
    story.append(KeepTogether([img3]))
    story.append(Spacer(1, 4))

    # Tabela: 3 fatos
    story.append(facts_table(stats, st))

    # Rodapé
    story.append(Spacer(1, 10))
    story.append(rule())
    story.append(P(
        f"Modelo: v1_devclub_rf_temporal_leads_single  ·  treinado em {stats['trained_at']}  ·  "
        f"{stats['n_trees']} árvores  ·  {stats['n_features']} features  ·  "
        f"~{stats['n_records']:,} leads no treino.".replace(",", "."),
        ParagraphStyle_footnote(),
    ))

    build_pdf(OUTPUT, story, title="Random Forest explicado", footer_label="Bring Data  ·  Random Forest explicado")
    print(f"PDF gerado: {OUTPUT}")


def ParagraphStyle_subtitle():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle("subtitle", fontName="Helvetica", fontSize=9.5,
                          textColor=C_MID_GRAY, leading=13, spaceAfter=8)


def ParagraphStyle_footnote():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle("foot", fontName="Helvetica", fontSize=7.5,
                          textColor=C_MID_GRAY, leading=10, spaceAfter=2)


def stats_callout(stats, st):
    """Caixa enxuta com os números da floresta."""
    cells = [
        ["Árvores", "Profundidade", "Nós (total)", "Folhas (total)", "Features"],
        [
            f"{stats['n_trees']}",
            f"{stats['max_depth']}",
            f"{stats['nodes_total']:,}".replace(",", "."),
            f"{stats['leaves_total']:,}".replace(",", "."),
            f"{stats['n_features']}",
        ],
    ]
    cell_style_hdr = ParagraphStyle_cell(bold=True, color="white", size=8.5)
    cell_style_val = ParagraphStyle_cell(bold=True, color="#1a1a1a", size=12)
    rows = [
        [Paragraph(c, cell_style_hdr) for c in cells[0]],
        [Paragraph(c, cell_style_val) for c in cells[1]],
    ]
    t = Table(rows, colWidths=[CONTENT_WIDTH / 5] * 5)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_BLACK),
        ("BACKGROUND", (0, 1), (-1, 1), HexColor("#f4fbf6")),
        ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BOX",        (0, 0), (-1, -1), 0.5, C_RULE),
        ("LINEBELOW",  (0, 0), (-1, 0),  0.3, C_RULE),
    ]))
    return [t, Spacer(1, 6)]


def facts_table(stats, st):
    """3 fatos centrais de assertividade."""
    rows = [
        [Paragraph("Top 3 decis (D8–D10)", st["td"]),
         Paragraph(f"~{stats['top3']:.0f}% das compras", style_fact())],
        [Paragraph("Top 5 decis (D6–D10)", st["td"]),
         Paragraph(f"~{stats['top5']:.0f}% das compras", style_fact())],
        [Paragraph("D10 (10% melhores)", st["td"]),
         Paragraph(f"converte ~{stats['lift_d10']:.1f}× a média da base".replace(".", ","), style_fact())],
    ]
    t = Table(rows, colWidths=[6 * cm, CONTENT_WIDTH - 6 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), C_LIGHT_GRAY),
        ("BACKGROUND", (1, 0), (1, -1), C_WHITE),
        ("LINEBELOW",  (0, 0), (-1, -2), 0.3, C_RULE),
        ("BOX",        (0, 0), (-1, -1), 0.5, C_RULE),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def style_fact():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle("fact", fontName="Helvetica-Bold", fontSize=10.5,
                          textColor=HexColor("#1d8a3e"), leading=14)


def ParagraphStyle_cell(*, bold, color, size):
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    fn = "Helvetica-Bold" if bold else "Helvetica"
    return ParagraphStyle("cell", fontName=fn, fontSize=size, leading=size + 3,
                          textColor=HexColor(color) if color.startswith("#") else
                                    (C_WHITE if color == "white" else C_DARK_GRAY),
                          alignment=TA_CENTER)


# Reimport para namespace ParagraphStyle/Paragraph nos helpers acima
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.platypus import Paragraph  # noqa: E402


if __name__ == "__main__":
    stats = load_model_stats()
    build(stats)

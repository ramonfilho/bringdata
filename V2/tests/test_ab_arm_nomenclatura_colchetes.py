"""O funil por variante não pode cegar quando o gestor muda o formato do nome.

Contexto (auditoria 16/08/2026): em 09/08 as campanhas viraram nomenclatura de
colchetes ("[17][DEVLF][CAP][LEADS][SITE][FRIO]...[JUL_24_TOP50]|<id>") e as
linhas "Por variante" do Daily Check ZERARAM por 7 dias com R$ 10,7k/dia de
gasto — dois defeitos independentes:

1. A porta de captação exigia a substring antiga com pipes ('devlf | cap |');
   '[DEVLF][CAP]' não a contém → tudo EXTERNO, descartado em silêncio.
2. O mapa de etiquetas do relatório lia só `campaign_tag` ('HQLB', 'JUL24'),
   enquanto o roteamento do scoring lia `utm_pattern.utm_campaign` (com
   'ABR_28_TOP30', 'JUL_24'): dois lados do MESMO yaml lendo campos diferentes.
   O scoring seguiu roteando; o relatório ficou cego.

Desenho novo (decisão do Ramon, 16/08): a ETIQUETA do modelo decide, achada em
qualquer formato de nome; o resto passa ILESO pro balde 'Lead' padrão; quente/
interno sem etiqueta ficam FORA do Lead. Estes testes usam os nomes REAIS das
campanhas no ar.

Rodável sem pytest: python tests/test_ab_arm_nomenclatura_colchetes.py
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.core.ab_arm import (
    ArmConfig,
    CHAMPION,
    CHALLENGER,
    CONTROLE,
    EXTERNO,
    _normaliza_nome,
    is_captacao,
    load_arm_config,
    resolve_arm,
    resolve_bucket_by_tag,
)

# Config REAL do repositório (configs/active_models/devclub.yaml).
CFG = load_arm_config()

# Nomes reais do ledger, 13-15/08 (auditoria do funil).
JUL24_TOP50 = ("[17][DEVLF][CAP][LEADS][SITE][FRIO][ADVTG_ABERTO][CBO][AUT]"
               "[10.08][TESTE_CONVERSAO][PG1][PIXELNOVO][JUL_24_TOP50]|1203040")
ABR28_TOP30 = ("[18][DEVLF][CAP][LEADS][SITE][FRIO][ADVTG_ABERTO][CBO][AUT]"
               "[10.08][TESTE_CONVERSAO][PG1][PIXELNOVO][ABR_28_TOP30]|1203041")
SEM_ETIQUETA = ("[20][DEVLF][CAP][LEADS][SITE][FRIO][CBO][AUT][09.08]"
                "[TESTE_CRIATIVO][PG1][PIXELNOVO]|1203050")
QUENTE_SEM_ETIQUETA = "[26][DEVLF][CAP][LEADS][SITE][QUENTE][CBO][AUT][12.08]|1203055"
FORMATO_ANTIGO = "DEVLF | CAP | FRIO | FASE 04 | ADV | PIXEL NOVO | LEAD | PG2"
QUENTE_COM_ETIQUETA_ANTIGA = "DEVLF | CAP | QUENTE | LOOKALIKE | LEADHQLB | PG1"
GOOGLE = "cap-go-devclub-pmax"

HOJE = date(2026, 8, 16)


# ───────────────────── porta de captação (formato-agnóstica) ─────────────────────

def test_porta_de_captacao_aceita_colchetes():
    assert is_captacao(JUL24_TOP50, CFG)
    assert is_captacao(SEM_ETIQUETA, CFG)


def test_porta_de_captacao_formato_antigo_continua_passando():
    assert is_captacao(FORMATO_ANTIGO, CFG)
    assert is_captacao(QUENTE_COM_ETIQUETA_ANTIGA, CFG)


def test_porta_de_captacao_google_e_organico_continuam_fora():
    """Não-enfraquecimento: a porta segue separando Meta captação do resto."""
    assert not is_captacao(GOOGLE, CFG)
    assert not is_captacao("DEVLF | AQUECIMENTO | REMARKETING", CFG)


def test_normalizacao_e_canonica():
    assert "devlf | cap | leads" in _normaliza_nome("[17][DEVLF][CAP][LEADS]")
    assert _normaliza_nome("DEVLF | CAP | FRIO") == "devlf | cap | frio"


# ──────────────── etiqueta do modelo decide (fonte única com o scoring) ────────────────

def test_etiqueta_jul24_no_formato_colchetes_roteia_pro_challenger():
    """O caso que zerou o funil: etiqueta JUL_24_TOP50 no fim do nome-colchete."""
    assert resolve_arm(utm_campaign=JUL24_TOP50, captured_at=HOJE, config=CFG) == CHALLENGER


def test_etiqueta_abr28_no_formato_colchetes_roteia_pro_champion():
    assert resolve_arm(utm_campaign=ABR28_TOP30, captured_at=HOJE, config=CFG) == CHAMPION


def test_mapa_de_etiquetas_leu_a_mesma_lista_do_roteamento():
    """As etiquetas do utm_pattern (que o scoring usa) agora estão no mapa do
    relatório. Se alguém remover do yaml, este teste quebra junto — fonte única."""
    tags = {t for t, _k in CFG.tag_variants}
    assert {"ABR_28_TOP30", "JUL_24", "JUL24", "LEADHQLB", "HQLB"} <= tags


def test_precedencia_challenger_antes_de_champion_preservada():
    """Desempate histórico: nome com as duas etiquetas conta como challenger."""
    dupla = "[19][DEVLF][CAP][ABR_28_TOP30][JUL_24_TOP30]|9"
    assert resolve_arm(utm_campaign=dupla, captured_at=HOJE, config=CFG) == CHALLENGER


def test_paineis_por_tag_reconhecem_etiqueta_nova():
    """resolve_bucket_by_tag (painéis de decil) herda o mapa novo."""
    assert resolve_bucket_by_tag(ABR28_TOP30, captured_at=HOJE, config=CFG) == CHAMPION


# ──────────────────── o resto passa ileso pro Lead padrão ────────────────────

def test_captacao_sem_etiqueta_cai_no_lead_padrao():
    """Antes: INDETERMINADO → excluída em silêncio. Agora: 'Lead' padrão,
    independente do formato do nome."""
    assert resolve_arm(utm_campaign=SEM_ETIQUETA, captured_at=HOJE, config=CFG) == CONTROLE
    assert resolve_arm(utm_campaign=FORMATO_ANTIGO, captured_at=HOJE, config=CFG) == CONTROLE


def test_quente_sem_etiqueta_fica_fora_do_lead():
    """Decisão do Ramon: quente/interno sem etiqueta não poluem o CPL da
    captação fria padrão."""
    assert resolve_arm(utm_campaign=QUENTE_SEM_ETIQUETA, captured_at=HOJE, config=CFG) == EXTERNO


def test_quente_COM_etiqueta_segue_pro_modelo():
    """Etiqueta vence público: a campanha QUENTE de R$ 2.271 (29/07) tem
    LEADHQLB e pertence ao modelo, não ao descarte."""
    assert resolve_arm(utm_campaign=QUENTE_COM_ETIQUETA_ANTIGA, captured_at=HOJE,
                       config=CFG) in (CHAMPION, CHALLENGER)


def test_google_segue_externo():
    assert resolve_arm(utm_campaign=GOOGLE, captured_at=HOJE, config=CFG) == EXTERNO


# ───────────────────── o fim-a-fim que o DM consome ─────────────────────

def test_classify_variant_fim_a_fim_com_nomes_reais():
    """O invólucro que o funil do DM usa: os nomes que zeraram o relatório
    agora caem nos baldes certos."""
    from src.validation.campaign_classifier import classify_variant
    assert classify_variant(JUL24_TOP50, HOJE) == "Challenger"
    assert classify_variant(ABR28_TOP30, HOJE) == "Champion"
    assert classify_variant(SEM_ETIQUETA, HOJE) == "Lead"
    assert classify_variant(GOOGLE, HOJE) == "EXTERNO"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

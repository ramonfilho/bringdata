"""Testes da assinatura de tag e do classificador de grupo de controle.

A assinatura de tag (`tag_signature`) é a CHAVE de analytics.campaign_labels: a
mesma tokenização que gerou as 39 assinaturas curadas manualmente. Se ela
divergir da curadoria, todo lookup de rótulo erra e o grupo de controle sai
errado. Por isso o teste de integração exige reproduzir 100% das chaves da
tabela a partir do universo real.

Rodar: python3 V2/tests/test_campaign_signature.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # V2/ no path

from src.validation.campaign_classifier import tag_signature, classify_for_weights


def test_tag_signature_descarta_estruturais():
    # nome longo típico do A/B: só a tag do braço sobrevive (data, fase, adv, ID caem)
    assert tag_signature(
        "DEVLF | CAP | FRIO | FASE 04 | ADV | LEADHQLB | 2026-05-01 | 120240"
    ) == "leadhqlb"
    # dois tokens de tag preservados na ordem
    assert tag_signature("DEVLF | CAP | FRIO | MACHINE LEARNING | LQ | PG2") == "machine learning | lq"
    # captação sem marca de braço → sem tag
    assert tag_signature("DEVLF | CAP | FRIO | FASE 01") == "(sem tag)"
    # ESCALA SCORE (controle) sobrevive
    assert tag_signature("DEVLF | CAP | FRIO | FASE 04 | ADV | ESCALA SCORE | PG2") == "escala score"


def test_tag_signature_url_encoded_e_nulos():
    # '%7C' url-encoded: split por '%' + limpeza do '7c' remonta os tokens
    assert tag_signature("DEVLF %7C CAP %7C FRIO %7C LEADQUALIFIED") == "leadqualified"
    # nulos → (sem tag), nunca estoura
    assert tag_signature(None) == "(sem tag)"
    assert tag_signature("") == "(sem tag)"
    assert tag_signature(float("nan")) == "(sem tag)"


def test_tag_signature_digitos_e_id_puro():
    # segmento só de dígitos (ID) é descartado
    assert tag_signature("DEVLF | LEADHQLB | 120243354440640390") == "leadhqlb"
    # data isolada é descartada
    assert tag_signature("2026-04-30 | MACHINE LEARNING") == "machine learning"


def test_classify_for_weights_pela_curadoria():
    # mapa de rótulos = assinatura → categoria (como vem de analytics.campaign_labels)
    label_map = {
        "aberto": "Controle",
        "lead": "Lead",
        "machine learning": "Champion",
        "leadhqlb": "Challenger",
        "dev20": "Excluir",
    }
    # campanhas reais → assinatura → categoria → grupo de peso
    assert classify_for_weights("DEVLF | CAP | FRIO | ABERTO | PG1", label_map) == "CONTROLE"
    assert classify_for_weights("DEVLF | CAP | FRIO | LEAD | PG1", label_map) == "CONTROLE"  # Lead conta como controle
    assert classify_for_weights("DEVLF | CAP | FRIO | MACHINE LEARNING", label_map) == "ML"
    assert classify_for_weights("DEVLF | CAP | FRIO | LEADHQLB | 123", label_map) == "ML"
    assert classify_for_weights("DEV20", label_map) == "NEUTRO"          # Excluir → fora do reweighting
    # assinatura não catalogada → NEUTRO (peso 1, sem efeito)
    assert classify_for_weights("DEVLF | CAP | FRIO | TAG_NOVA_XYZ", label_map) == "NEUTRO"


def test_classify_for_weights_fallback_legado():
    # sem label_map → classificador por substring legado (COM_ML/SEM_ML/EXCLUIR → grupos)
    assert classify_for_weights("DEVLF | CAP | FRIO | MACHINE LEARNING | PG2", None) == "ML"
    assert classify_for_weights("DEVLF | CAP | FRIO | ESCALA SCORE | PG2", None) == "CONTROLE"
    assert classify_for_weights("PÓS DEV | CAP | FRIO | FASE 01", None) == "NEUTRO"  # não captação
    assert classify_for_weights(None, None) == "NEUTRO"


def test_integracao_reproduz_chaves_curadas_db():
    """Integração (precisa de DB): o tokenizador reproduz 100% das chaves de
    analytics.campaign_labels a partir do universo real. Pula se não houver DB."""
    import os
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))
    try:
        import ssl
        import datetime
        import pg8000.native
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        c = pg8000.native.Connection(
            host=os.environ["LEDGER_DB_HOST"], port=int(os.environ.get("LEDGER_DB_PORT", "5432")),
            database=os.environ.get("LEDGER_DB_NAME", "ledger"), user=os.environ.get("LEDGER_DB_USER", "ledger_app"),
            password=os.environ["LEDGER_DB_PASSWORD"], ssl_context=ctx, timeout=120,
        )
    except Exception as e:
        print(f"  SKIP integração DB (sem conexão: {e})")
        return
    try:
        c.run("SET search_path TO analytics, public")
        keys = set(r[0] for r in c.run("SELECT tag_signature FROM analytics.campaign_labels"))
        if not keys:
            print("  SKIP integração DB (tabela vazia)")
            return
        rows = c.run(
            "SELECT COALESCE(NULLIF(trim(survey_responses->>'Campaign'),''), NULLIF(trim(utm_campaign),'')) camp, "
            "COALESCE((survey_responses->>'Data')::timestamptz, capturado_em) dt "
            "FROM leads WHERE source IN ('leads_treino_prod','train_unified')"
        )
    finally:
        c.close()
    produced = set()
    for camp, dt in rows:
        if camp is None or str(camp).strip() == "":
            continue
        if dt is not None and dt.replace(tzinfo=None) < datetime.datetime(2025, 11, 1):
            continue
        produced.add(tag_signature(camp))
    faltando = keys - produced
    assert not faltando, f"tokenizador não reproduz chaves curadas: {sorted(faltando)}"
    print(f"  OK integração DB: {len(keys)} chaves curadas reproduzidas 100%")


if __name__ == "__main__":
    test_tag_signature_descarta_estruturais()
    test_tag_signature_url_encoded_e_nulos()
    test_tag_signature_digitos_e_id_puro()
    test_classify_for_weights_pela_curadoria()
    test_classify_for_weights_fallback_legado()
    test_integracao_reproduz_chaves_curadas_db()
    print("OK — testes de assinatura de tag e grupo de controle passaram")

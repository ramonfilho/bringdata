"""Testes das funções puras de api/pubsub_branch.

Rodável sem pytest:  python tests/test_pubsub_branch.py

Cobre o caminho do payload Pub/Sub até o ponto onde o pipeline ML toma conta:
  - parse JSON (bytes/str)
  - payload → survey_dict (com tradução slug→PT embutida)
  - payload → enrich (computador/fbp/fbc/etc direto, sem JOIN)
  - payload → utm
  - is_meta_eligible (match contra allowlist)
  - classify (3 verdicts: allowlist / missing_data / send)
  - ledger_row (shape do INSERT)

Não cobre orquestração com Pub/Sub real nem pipeline.run — isso é smoke test
contra os 9 leads capturados, fora deste arquivo.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.pubsub_branch import (
    classify,
    is_meta_eligible,
    ledger_row,
    parse_pubsub_payload,
    payload_to_enrich,
    payload_to_survey_dict,
    payload_to_utm,
)
from src.core.client_config import GoogleAdsConfig


# Payload real do dono — primeira mensagem capturada em 2026-05-23T00:50:11Z
PAYLOAD_REAL = {
    "eventId": "019e524f-6837-7220-9cc3-05f0e5896516",
    "submittedAt": "2026-05-23T00:50:11.602Z",
    "email": "otsuseije@gmail.com",
    "firstName": "Seije",
    "lastName": "Otsu",
    "phone": "+5586981653315",
    "hasComputer": "SIM",
    "fbp": "fb.2.1715780516485.891660576",
    "fbc": None,
    "userAgent": "Mozilla/5.0",
    "ip4": "100.64.0.7",
    "survey": {
        "genero": "feminino",
        "idade": "<18",
        "ocupacao": "clt",
        "faixaSalarial": "0",
        "cartaoCredito": "sim",
        "estudouProgramacao": "sim",
        "faculdade": "sim",
        "investiuCurso": "sim",
        "atracaoProfissao": "trabalhar_exterior",
        "interesseEvento": "transicao_carreira",
    },
    "utm": {
        "source": "org",
        "medium": "api",
        "campaign": "LF56",
        "content": "baseantiga",
        "term": "api",
        "url": "https://lp6.rodolfomori.com.br/cap-org-a-v1/?utm_campaign=LF56",
    },
}


def test_parse_aceita_bytes_e_str():
    raw_str = json.dumps({"eventId": "a", "email": "b@c"})
    raw_bytes = raw_str.encode("utf-8")
    assert parse_pubsub_payload(raw_str) == {"eventId": "a", "email": "b@c"}
    assert parse_pubsub_payload(raw_bytes) == {"eventId": "a", "email": "b@c"}


def test_parse_falha_em_json_invalido():
    try:
        parse_pubsub_payload(b"not json")
    except json.JSONDecodeError:
        return
    raise AssertionError("parse_pubsub_payload deveria ter levantado JSONDecodeError")


def test_payload_to_survey_dict_traduz_slugs():
    s = payload_to_survey_dict(PAYLOAD_REAL)
    # envelope
    assert s["id"]          == PAYLOAD_REAL["eventId"]
    assert s["submittedAt"] == PAYLOAD_REAL["submittedAt"]
    assert s["clientEmail"] == PAYLOAD_REAL["email"]
    assert s["ip"]          == PAYLOAD_REAL["ip4"]
    # 10 canonicalizados (PT-Long)
    assert s["idade"]              == "Menos de 18 anos"
    assert s["ocupacao"]           == "Sou CLT/Funcionário Público"
    assert s["faixaSalarial"]      == "Não tenho renda"
    assert s["atracaoProfissao"]   == "Trabalhar para outros países e ganhar em outra moeda"
    assert s["interesseEvento"]    == "Fazer transição de carreira e conseguir meu primeiro emprego na área"
    assert s["genero"]             == "Feminino"
    assert s["cartaoCredito"]      == "Sim"
    assert s["estudouProgramacao"] == "Sim"
    assert s["faculdade"]          == "Sim"
    assert s["investiuCurso"]      == "Sim"


def test_payload_to_survey_dict_propaga_valueerror_slug_invalido():
    payload = dict(PAYLOAD_REAL)
    payload["survey"] = dict(payload["survey"], idade="70+")  # slug fora do vocab
    try:
        payload_to_survey_dict(payload)
    except ValueError as e:
        assert "idade" in str(e)
        return
    raise AssertionError("payload_to_survey_dict deveria ter levantado ValueError")


def test_payload_to_enrich_lê_campos_direto():
    e = payload_to_enrich(PAYLOAD_REAL)
    assert e["computador"] == "SIM"
    assert e["fbp"]        == PAYLOAD_REAL["fbp"]
    assert e["fbc"]        is None
    assert e["telefone"]   == PAYLOAD_REAL["phone"]
    assert e["nome"]       == "Seije Otsu"
    assert e["ip"]         == PAYLOAD_REAL["ip4"]
    assert e["user_agent"] == PAYLOAD_REAL["userAgent"]


def test_payload_to_enrich_nome_so_first():
    p = dict(PAYLOAD_REAL, lastName="")
    assert payload_to_enrich(p)["nome"] == "Seije"


def test_payload_to_enrich_nome_so_last():
    p = dict(PAYLOAD_REAL, firstName="")
    assert payload_to_enrich(p)["nome"] == "Otsu"


def test_payload_to_enrich_sem_nome():
    p = dict(PAYLOAD_REAL, firstName="", lastName="")
    assert payload_to_enrich(p)["nome"] is None


def test_payload_to_utm_passa_dict():
    u = payload_to_utm(PAYLOAD_REAL)
    assert u == PAYLOAD_REAL["utm"]
    # tem que ser cópia, não referência
    u["source"] = "x"
    assert PAYLOAD_REAL["utm"]["source"] == "org"


def test_payload_to_utm_sem_utm():
    assert payload_to_utm({}) == {}


def test_is_meta_eligible():
    allowlist = {"facebook-ads", "instagram", "ig", "fb"}
    assert is_meta_eligible("facebook-ads", allowlist) is True
    assert is_meta_eligible("ig",           allowlist) is True
    assert is_meta_eligible("organic",      allowlist) is False
    assert is_meta_eligible("org",          allowlist) is False  # caso real 2026-05-23
    assert is_meta_eligible("google",       allowlist) is False
    assert is_meta_eligible(None,           allowlist) is False
    assert is_meta_eligible("",             allowlist) is False


def test_classify_3_verdicts():
    enrich_completo = {"computador": "SIM", "fbp": "x", "fbc": "y"}
    enrich_sem_fbc  = {"computador": "SIM", "fbp": "x", "fbc": None}
    enrich_sem_pc   = {"computador": None,  "fbp": "x", "fbc": "y"}

    assert classify(False, enrich_completo) == "skipped_allowlist"
    assert classify(True,  enrich_sem_fbc)  == "skipped_missing_data"
    assert classify(True,  enrich_sem_pc)   == "skipped_missing_data"
    assert classify(True,  enrich_completo) == "send"


def test_ledger_row_shape():
    r = ledger_row(
        event_id="evt1", email="x@y", variant="champion",
        lead_score=0.42, decil=7, base_status="success",
        base_meta_event_id="qualified_evt1",
        hq_meta_event_id=None, hq_status=None,
        capi_sent_at_now=True, error_message=None,
    )
    assert r["event_id"]           == "evt1"
    assert r["lead_score"]         == 0.42
    assert r["decil"]              == 7
    assert r["base_status"]        == "success"
    assert r["base_meta_event_id"] == "qualified_evt1"
    assert r["capi_sent_at_now"]   is True
    assert "lead_id" not in r, "ledger_row não deve mais usar lead_id (PK é event_id)"
    # P17 — colunas utm_* presentes; None quando utm não foi passado.
    for k in ("utm_source", "utm_medium", "utm_campaign",
              "utm_content", "utm_term", "utm_url"):
        assert k in r, f"{k!r} esperada em ledger_row"
        assert r[k] is None, f"{k!r} sem utm passado deveria ser None, veio {r[k]!r}"


def test_ledger_row_skipped_não_seta_capi_sent_at():
    r = ledger_row(
        event_id="evt2", email="x@y", variant=None,
        lead_score=None, decil=None, base_status="skipped_allowlist",
    )
    assert r["capi_sent_at_now"]  is False
    assert r["base_meta_event_id"] is None
    assert r["hq_meta_event_id"]   is None


def test_ledger_row_grava_utm_quando_passado():
    """P17: com utm passado, todas as 6 colunas utm_* são populadas."""
    utm = {
        "source":   "facebook-ads",
        "medium":   "Aberto",
        "campaign": "DEVLF | CAP",
        "content":  "AD0027",
        "term":     "fb",
        "url":      "https://lp.x/?utm_source=facebook-ads",
    }
    r = ledger_row(
        event_id="evt3", email="x@y", variant="champion",
        lead_score=0.5, decil=8, base_status="success",
        utm=utm,
    )
    assert r["utm_source"]   == "facebook-ads"
    assert r["utm_medium"]   == "Aberto"
    assert r["utm_campaign"] == "DEVLF | CAP"
    assert r["utm_content"]  == "AD0027"
    assert r["utm_term"]     == "fb"
    assert r["utm_url"]      == "https://lp.x/?utm_source=facebook-ads"


def test_ledger_row_utm_parcial_grava_o_que_existe():
    """P17: utm com campos faltando — o que vier vai pra coluna, resto fica None."""
    r = ledger_row(
        event_id="evt4", email="x@y", variant=None,
        lead_score=None, decil=None, base_status="skipped_allowlist",
        utm={"source": "organic"},
    )
    assert r["utm_source"]   == "organic"
    assert r["utm_medium"]   is None
    assert r["utm_campaign"] is None
    assert r["utm_content"]  is None
    assert r["utm_term"]     is None
    assert r["utm_url"]      is None


class _FakeMessage:
    def __init__(self, data: bytes, message_id: str):
        self.data = data
        self.message_id = message_id


class _FakeReceived:
    def __init__(self, ack_id: str, message: _FakeMessage):
        self.ack_id = ack_id
        self.message = message


class _FakeResponse:
    def __init__(self, received):
        self.received_messages = received


class _FakeSubscriber:
    """Mock mínimo do SubscriberClient — só registra pulls e acks."""
    def __init__(self, received):
        self._received = received
        self.acked: list = []

    def pull(self, request, timeout):  # noqa: ARG002
        return _FakeResponse(self._received)

    def acknowledge(self, request):
        self.acked.extend(request["ack_ids"])


class _FakeConn:
    def __init__(self):
        self.inserts: list = []

    def run(self, sql, **params):
        self.inserts.append({"sql": sql, "params": params})
        return []


class _FakePipeline:
    """Pipeline mockado — não precisa rodar porque o payload vai cair em
    'skipped_allowlist' (utm.source='org' não está na allowlist)."""
    class _Cfg:
        class _Capi:
            utm_source_allowlist = ["facebook-ads"]
        capi = _Capi()
        google_ads = GoogleAdsConfig()   # desligado (enabled=False) — canal Google inerte
        client_id = "devclub"
    _client_config = _Cfg()


def test_dedup_in_batch_dispara_capi_uma_vez():
    """Duas mensagens com mesmo eventId no mesmo pull → 1 processada, 1 ackada
    como dup. Cobre o caso visto em produção 2026-05-25 11:35 (marcelo enviado
    2x no mesmo batch porque o publisher republicou).

    Pinned em SCORE_ALL_LEADS=false: testa o caminho legacy (classify decide
    tudo antes do scoring). O fake pipeline não implementa scoring; sob
    SCORE_ALL_LEADS=true o lead source=org cairia em to_score e dispararia
    erro de scoring. Pra testar o novo caminho com scoring, ver
    test_score_all_leads_* (a serem adicionados quando o flag default
    SCORE_ALL_LEADS=true entrar no caminho coberto por testes integrados).
    """
    import os
    from api.pubsub_branch import process_pending_pubsub

    raw = json.dumps(PAYLOAD_REAL).encode("utf-8")
    received = [
        _FakeReceived("ack-1", _FakeMessage(raw, "msg-1")),
        _FakeReceived("ack-2", _FakeMessage(raw, "msg-2")),  # mesma mensagem
    ]
    sub = _FakeSubscriber(received)
    conn = _FakeConn()
    _prev = os.environ.get("SCORE_ALL_LEADS")
    os.environ["SCORE_ALL_LEADS"] = "false"
    try:
        summary = process_pending_pubsub(sub, conn, _FakePipeline(), dry_run=False)
    finally:
        if _prev is None:
            os.environ.pop("SCORE_ALL_LEADS", None)
        else:
            os.environ["SCORE_ALL_LEADS"] = _prev

    # Os 2 ack_ids vão pra fila de ack — não queremos a 2ª mensagem voltando
    assert set(sub.acked) == {"ack-1", "ack-2"}, sub.acked
    # Só 1 do par chega a ser "processado" (o outro vira dup_in_batch)
    assert summary["processed"] == 1, summary
    assert summary["dup_in_batch"] == 1, summary
    # source=org não está na allowlist → o que sobrou cai em skipped_allowlist,
    # confirmando que o caminho de classificação rodou só pra 1 evento.
    assert summary["skipped_allowlist"] == 1, summary
    assert summary["sent"] == 0, summary
    # Ledger insere apenas 1 linha (skipped_allowlist) — a dup nem chega ao
    # INSERT, então o ON CONFLICT do ledger nem é exercitado nesse caso.
    assert len(conn.inserts) == 1, [i["params"].get("event_id") for i in conn.inserts]


# ---------------------------------------------------------------------------
# Dual-write do ledger (PLANO_LEDGER_CLOUDSQL.md Etapa 1)
# ---------------------------------------------------------------------------

class _FailConn:
    """Conexão que falha todo INSERT — simula Cloud SQL/Railway fora do ar."""
    def __init__(self):
        self.attempts = 0

    def run(self, sql, **params):
        self.attempts += 1
        raise RuntimeError("conexão simulada fora do ar")


class _EnvGuard:
    def __init__(self, **kv):
        self._kv = kv
        self._prev = {}

    def __enter__(self):
        import os
        for k, v in self._kv.items():
            self._prev[k] = os.environ.get(k)
            os.environ[k] = v

    def __exit__(self, *a):
        import os
        for k, prev in self._prev.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


def _processa_um_lead(target: str, railway_conn, ledger_conn):
    """1 mensagem real (source=org → skipped_allowlist no caminho legacy)."""
    from api.pubsub_branch import process_pending_pubsub
    raw = json.dumps(PAYLOAD_REAL).encode("utf-8")
    sub = _FakeSubscriber([_FakeReceived("ack-1", _FakeMessage(raw, "msg-1"))])
    with _EnvGuard(SCORE_ALL_LEADS="false", LEDGER_TARGET=target):
        summary = process_pending_pubsub(
            sub, railway_conn, _FakePipeline(), dry_run=False,
            ledger_conn=ledger_conn,
        )
    return sub, summary


def test_ledger_target_parsing():
    from api.pubsub_branch import ledger_target
    with _EnvGuard(LEDGER_TARGET="dual"):
        assert ledger_target() == "dual"
    with _EnvGuard(LEDGER_TARGET="CLOUDSQL "):
        assert ledger_target() == "cloudsql"
    with _EnvGuard(LEDGER_TARGET="banana"):
        assert ledger_target() == "railway"


def test_dual_write_grava_nos_dois_e_acka():
    railway, ledger = _FakeConn(), _FakeConn()
    sub, summary = _processa_um_lead("dual", railway, ledger)
    assert len(ledger.inserts) == 1, ledger.inserts
    assert len(railway.inserts) == 1, railway.inserts
    assert sub.acked == ["ack-1"], sub.acked
    assert summary["ledger_target"] == "dual", summary
    assert summary["ledger_errors"] == 0, summary


def test_cloudsql_primario_falha_nao_acka():
    """Falha no primário (Cloud SQL) → mensagem fica SEM ack pra reentrega;
    espelho Railway ainda grava (não perde a linha na fonte antiga)."""
    railway, ledger = _FakeConn(), _FailConn()
    sub, summary = _processa_um_lead("dual", railway, ledger)
    assert sub.acked == [], sub.acked
    assert summary["ledger_errors"] == 1, summary
    assert summary["unacked_for_retry"] == 1, summary
    assert len(railway.inserts) == 1, railway.inserts


def test_espelho_railway_falha_nao_bloqueia_ack():
    """Espelho tolerante: Railway fora não impede ack nem conta erro do primário."""
    railway, ledger = _FailConn(), _FakeConn()
    sub, summary = _processa_um_lead("dual", railway, ledger)
    assert sub.acked == ["ack-1"], sub.acked
    assert summary["ledger_errors"] == 0, summary
    assert len(ledger.inserts) == 1, ledger.inserts


def test_cloudsql_only_nao_escreve_railway():
    railway, ledger = _FakeConn(), _FakeConn()
    sub, summary = _processa_um_lead("cloudsql", railway, ledger)
    assert len(ledger.inserts) == 1, ledger.inserts
    assert len(railway.inserts) == 0, railway.inserts
    assert sub.acked == ["ack-1"], sub.acked


def test_target_dual_sem_ledger_conn_degrada_railway():
    """Config pede dual mas a conexão Cloud SQL não veio → grava no Railway
    (melhor do que perder linha) e reporta o target efetivo."""
    railway = _FakeConn()
    sub, summary = _processa_um_lead("dual", railway, None)
    assert len(railway.inserts) == 1, railway.inserts
    assert sub.acked == ["ack-1"], sub.acked
    assert summary["ledger_target"] == "railway", summary


def test_insert_ledger_nao_mutila_dict():
    """O dual-write insere a MESMA linha 2x — _insert_ledger não pode
    consumir (pop) campos do dict do caller."""
    from api.pubsub_branch import _insert_ledger
    row = {
        "event_id": "e1", "email": "a@b.c", "variant": None,
        "lead_score": 0.5, "decil": 5, "base_meta_event_id": None,
        "base_status": "success", "hq_meta_event_id": None, "hq_status": None,
        "error_message": None, "utm_source": None, "utm_medium": None,
        "utm_campaign": None, "utm_content": None, "utm_term": None,
        "utm_url": None, "survey_responses": {"idade": "x"},
        "first_name": None, "last_name": None, "phone": None, "fbp": None,
        "fbc": None, "user_agent": None, "ip": None, "has_computer": "SIM",
        "capi_sent_at_now": True,
    }
    c1, c2 = _FakeConn(), _FakeConn()
    _insert_ledger(c1, row)
    _insert_ledger(c2, row)
    assert row["survey_responses"] == {"idade": "x"}, "dict do caller foi mutilado"
    assert row["capi_sent_at_now"] is True
    for c in (c1, c2):
        assert "NOW()" in c.inserts[0]["sql"], "capi_sent_at_now ignorado"
        assert c.inserts[0]["params"]["survey_responses"] is not None


def _run():
    tests = [
        test_parse_aceita_bytes_e_str,
        test_parse_falha_em_json_invalido,
        test_payload_to_survey_dict_traduz_slugs,
        test_payload_to_survey_dict_propaga_valueerror_slug_invalido,
        test_payload_to_enrich_lê_campos_direto,
        test_payload_to_enrich_nome_so_first,
        test_payload_to_enrich_nome_so_last,
        test_payload_to_enrich_sem_nome,
        test_payload_to_utm_passa_dict,
        test_payload_to_utm_sem_utm,
        test_is_meta_eligible,
        test_classify_3_verdicts,
        test_ledger_row_shape,
        test_ledger_row_skipped_não_seta_capi_sent_at,
        test_ledger_row_grava_utm_quando_passado,
        test_ledger_row_utm_parcial_grava_o_que_existe,
        test_dedup_in_batch_dispara_capi_uma_vez,
        test_ledger_target_parsing,
        test_dual_write_grava_nos_dois_e_acka,
        test_cloudsql_primario_falha_nao_acka,
        test_espelho_railway_falha_nao_bloqueia_ack,
        test_cloudsql_only_nao_escreve_railway,
        test_target_dual_sem_ledger_conn_degrada_railway,
        test_insert_ledger_nao_mutila_dict,
    ]
    fails = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL  {t.__name__}\n        {e}")
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - fails}/{len(tests)} passaram")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_run())

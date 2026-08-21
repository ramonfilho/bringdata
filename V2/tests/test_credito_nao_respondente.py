"""Trava a medição do CRÉDITO DO NÃO-RESPONDENTE (Decisão 12).

O que protege, em uma frase: que o refresh meça quanto vale o cadastro sem
pesquisa (compra ÷ compra do respondente) na régua do calendário, e que sem
massa ou fora da faixa o crédito saia INVÁLIDO — o push então não credita nada,
que é o comportamento antigo.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.monitoring.rolling_reference import (  # noqa: E402
    CREDITO_NR_FAIXA, CREDITO_NR_MIN_COMPRADORES, CREDITO_NR_MIN_NAO,
    credito_do_nao_respondente,
)

LAUNCHES = {"LF99": {"cap_start": "2026-07-01", "cap_end": "2026-07-07",
                     "vendas_end": "2026-07-20"}}


def _cadastros(n_resp, n_nao):
    rows = []
    for i in range(n_resp):
        rows.append((f"resp{i}@x.com", f"1199988{i:04d}", "2026-07-03"))
    for i in range(n_nao):
        rows.append((f"nao{i}@x.com", f"2199977{i:04d}", "2026-07-03"))
    return pd.DataFrame(rows, columns=["email", "telefone", "captured_at"])


def _vendas(emails, dia="2026-07-10"):
    return pd.DataFrame([(e, None, pd.Timestamp(dia)) for e in emails],
                        columns=["email", "telefone", "sale_date"])


def test_credito_e_a_razao_das_conversoes():
    """4000 resp (40 compram → 1%) e 4000 não (16 compram → 0,4%) → crédito 0,40."""
    cad = _cadastros(4000, 4000)
    resp_set = {f"resp{i}@x.com" for i in range(4000)}
    vendas = _vendas([f"resp{i}@x.com" for i in range(40)]
                     + [f"nao{i}@x.com" for i in range(16)])
    r = credito_do_nao_respondente(cad, resp_set, vendas, launches=LAUNCHES)
    assert r["valido"] is True
    assert abs(r["credito"] - 0.40) < 1e-6
    assert r["compradores_nao"] == 16


def test_venda_depois_do_fim_de_vendas_nao_conta():
    """Compra fora da janela do lançamento (regra do calendário) fica de fora —
    é a mesma régua da referência, não uma janela própria."""
    cad = _cadastros(4000, 4000)
    resp_set = {f"resp{i}@x.com" for i in range(4000)}
    dentro = _vendas([f"nao{i}@x.com" for i in range(16)], dia="2026-07-19")
    fora = _vendas([f"nao{i}@x.com" for i in range(16, 32)], dia="2026-08-15")
    vendas = pd.concat([dentro, fora,
                        _vendas([f"resp{i}@x.com" for i in range(40)])])
    r = credito_do_nao_respondente(cad, resp_set, vendas, launches=LAUNCHES)
    assert r["compradores_nao"] == 16, "as 16 de agosto estão fora da janela do LF"


def test_sem_massa_sai_invalido():
    """Abaixo dos mínimos (não-respondentes ou compradores), crédito é None e
    inválido — o push não credita nada."""
    cad = _cadastros(4000, CREDITO_NR_MIN_NAO - 1)
    resp_set = {f"resp{i}@x.com" for i in range(4000)}
    vendas = _vendas([f"resp{i}@x.com" for i in range(40)]
                     + [f"nao{i}@x.com" for i in range(CREDITO_NR_MIN_COMPRADORES)])
    r = credito_do_nao_respondente(cad, resp_set, vendas, launches=LAUNCHES)
    assert r["valido"] is False and r["credito"] is None
    assert r["motivo"] == "sem_massa"


def test_fora_da_faixa_sai_invalido():
    """Crédito acima da faixa (não-respondente 'melhor' que respondente) é medição
    quebrada — marca inválido, número fica visível pra investigação."""
    cad = _cadastros(4000, 4000)
    resp_set = {f"resp{i}@x.com" for i in range(4000)}
    vendas = _vendas([f"resp{i}@x.com" for i in range(10)]      # 0,25%
                     + [f"nao{i}@x.com" for i in range(40)])    # 1,0% → crédito 4,0
    r = credito_do_nao_respondente(cad, resp_set, vendas, launches=LAUNCHES)
    assert r["valido"] is False
    assert r["credito"] is not None and r["credito"] > CREDITO_NR_FAIXA[1]


def test_casa_venda_por_telefone_tambem():
    """Venda sem email casado mas com telefone do cadastro conta — é o mesmo
    casamento email+telefone do resto da casa."""
    cad = _cadastros(4000, 4000)
    resp_set = {f"resp{i}@x.com" for i in range(4000)}
    por_tel = pd.DataFrame(
        [(None, f"2199977{i:04d}", pd.Timestamp("2026-07-10")) for i in range(16)],
        columns=["email", "telefone", "sale_date"])
    vendas = pd.concat([_vendas([f"resp{i}@x.com" for i in range(40)]), por_tel])
    r = credito_do_nao_respondente(cad, resp_set, vendas, launches=LAUNCHES)
    assert r["compradores_nao"] == 16


# ───────── consertos do review adversarial de 20/08 ─────────

def _cad_multicanal(n_meta_resp, n_meta_nao, n_google_nao):
    rows = []
    for i in range(n_meta_resp):
        rows.append((f"resp{i}@x.com", f"1199988{i:04d}", "2026-07-03", "facebook-ads"))
    for i in range(n_meta_nao):
        rows.append((f"nao{i}@x.com", f"2199977{i:04d}", "2026-07-03", "facebook-ads"))
    for i in range(n_google_nao):
        rows.append((f"gnao{i}@x.com", f"3199966{i:04d}", "2026-07-03", "google-ads"))
    return pd.DataFrame(rows, columns=["email", "telefone", "captured_at",
                                       "utm_source"])


def test_so_meta_entra_na_medicao():
    """O crédito é aplicado só em linha da Meta (a do Google sai em moeda_real),
    então medir numa população multicanal valoraria a Meta com conversão do
    Google — a mesma classe do incidente dos baldes (PRs #220/#221)."""
    cad = _cad_multicanal(4000, 4000, 4000)
    resp_set = {f"resp{i}@x.com" for i in range(4000)}
    # Meta: 40 resp (1%) e 16 não (0,4%) → crédito 0,40.
    # Google: 200 não compram (5%) — se entrasse, o crédito dispararia.
    vendas = _vendas([f"resp{i}@x.com" for i in range(40)]
                     + [f"nao{i}@x.com" for i in range(16)]
                     + [f"gnao{i}@x.com" for i in range(200)])
    r = credito_do_nao_respondente(cad, resp_set, vendas, launches=LAUNCHES)
    assert abs(r["credito"] - 0.40) < 1e-6, (
        f"o Google contaminou a medição: crédito {r['credito']}")
    assert r["n_nao"] == 4000, "só os não-respondentes da META entram"


def test_janela_de_venda_ainda_aberta_fica_de_fora():
    """Cadastro de lançamento que ainda vende (limite > as_of) sai inteiro: com
    o carrinho aberto, buy=0 é 'ainda não comprou', não 'não compra'."""
    import datetime as _dt
    cad = _cad_multicanal(4000, 4000, 0)
    resp_set = {f"resp{i}@x.com" for i in range(4000)}
    vendas = _vendas([f"resp{i}@x.com" for i in range(40)]
                     + [f"nao{i}@x.com" for i in range(16)])
    # as_of ANTES do vendas_end do LF99 (20/07): tudo é janela aberta.
    r = credito_do_nao_respondente(cad, resp_set, vendas, launches=LAUNCHES,
                                   as_of=_dt.date(2026, 7, 15))
    assert r["valido"] is False and r["motivo"] == "sem_massa", (
        "com o carrinho aberto não há massa madura para medir")
    # as_of DEPOIS: mede normal.
    r2 = credito_do_nao_respondente(cad, resp_set, vendas, launches=LAUNCHES,
                                    as_of=_dt.date(2026, 8, 1))
    assert abs(r2["credito"] - 0.40) < 1e-6


def test_dedup_fica_com_a_captacao_mais_recente_e_e_deterministico():
    """Pessoa com 2 cadastros na janela: vale a captação MAIS RECENTE (convenção
    de build_matured_window). Sem ordenar, o Postgres decide qual sobrevive e o
    crédito muda entre rodadas sem dado novo."""
    cad = _cad_multicanal(4000, 4000, 0)
    # a mesma pessoa, cadastrada de novo DEPOIS (a linha que deve prevalecer)
    extra = pd.DataFrame([("nao0@x.com", "2199977000", "2026-07-06",
                           "facebook-ads")],
                         columns=["email", "telefone", "captured_at",
                                  "utm_source"])
    resp_set = {f"resp{i}@x.com" for i in range(4000)}
    vendas = _vendas([f"resp{i}@x.com" for i in range(40)]
                     + [f"nao{i}@x.com" for i in range(16)])
    a = credito_do_nao_respondente(pd.concat([cad, extra], ignore_index=True),
                                   resp_set, vendas, launches=LAUNCHES)
    b = credito_do_nao_respondente(pd.concat([extra, cad], ignore_index=True),
                                   resp_set, vendas, launches=LAUNCHES)
    assert a["credito"] == b["credito"], (
        "a ordem das linhas de entrada mudou o crédito — não é determinístico")
    assert a["n_nao"] == 4000, "a duplicata não pode virar duas pessoas"

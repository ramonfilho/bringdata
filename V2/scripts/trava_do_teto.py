"""Trava do teto: o número que a gente MANDARIA teria acertado no passado?

É o passo 3 do plano do teto e o único teste que pega erro de fórmula, porque confere
contra a REALIDADE em vez de contra a própria conta. Os testes unitários provam que a
aritmética está certa; este prova que ela responde à pergunta certa.

    O teto promete: "com CPL até X, este segmento bate a meta de ROAS."

Então a conferência é direta: pega lançamento já encerrado, calcula o teto que teríamos
mandado para cada campanha, e olha o que de fato aconteceu com ela.

    campanha com CPL ABAIXO do teto  -> deveria ter batido a meta
    campanha com CPL ACIMA do teto   -> não deveria

Se a promessa não se sustenta no passado, ela não vai se sustentar no futuro, e teto
errado não custa ranking: custa verba, porque o gestor mexe no orçamento com base nele.

POR QUE ISTO É UM PORTÃO, E NÃO UM TESTE DE UMA VEZ SÓ
=====================================================
Roda de novo antes de CADA mudança que altere o valor entregue: entrada da nota de
conversão do criativo, entrada do palpite pela fala, troca da meta de ROAS. Cada uma
muda o número na tela do gestor, e cada uma passa por aqui antes.

O QUE ESTE SCRIPT NÃO FAZ
=========================
Não usa a referência de HOJE para julgar campanha de meses atrás — isso seria trapaça,
porque a referência de hoje já viu o desfecho daquelas vendas. Cada lançamento é julgado
com a conversão por decil apurada FORA da janela dele.

    python -m scripts.trava_do_teto                 # todos os lançamentos encerrados
    python -m scripts.trava_do_teto --lf DEV20      # um só
    python -m scripts.trava_do_teto --roas 2.0      # meta alternativa
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("trava_do_teto")

# Piso de gasto para a campanha entrar na conferência. Abaixo disto o ROAS observado é
# ruído de amostra: uma venda a mais ou a menos vira 100% de diferença, e a campanha
# entraria dizendo mais sobre o acaso do que sobre o teto.
MIN_GASTO = 300.0
MIN_LEADS = 100

# QUANTOS COMPRADORES A GENTE CONSEGUE RECONHECER COMO TENDO SIDO LEAD NOSSO.
#
# De cada 10 pessoas que compram, a gente liga ~6 a um lead. As outras 4 compraram e
# não dá pra atribuir a ninguém. Toda taxa de conversão que a gente calcula sai
# encolhida por esse fator, e medir o resultado de uma campanha sem desfazer isso a
# faz parecer bem pior do que foi.
#
# Estes números vêm da coluna "Na Base" da planilha de compradores do cliente, que
# marca comprador por comprador se ele estava na nossa base. É medição, não estimativa.
#
# São notavelmente ESTÁVEIS (57,6% a 66,2%), o que é o que permite usar um número por
# lançamento em vez de ter que medir tudo de novo a cada vez.
TAXA_DE_RECONHECIMENTO = {
    "LF57": 0.662, "LF58": 0.576, "LF59": 0.594, "LF60": 0.615, "LF61": 0.632,
}
TAXA_MEDIANA = 0.615     # para os lançamentos que a planilha ainda não cobre


def _conexao():
    from src.data.analytics_connection import open_analytics_connection
    return open_analytics_connection(timeout=900)


def _lancamentos_encerrados(conn, apenas=None) -> list:
    """LFs cujas vendas já fecharam. Lançamento em curso não pode ser julgado: as
    vendas dele ainda estão acontecendo e o ROAS observado sairia baixo por construção."""
    linhas = conn.run(
        "SELECT lf_name, cap_start, cap_end, vendas_start, vendas_end "
        "FROM launch_calendar WHERE client_id = 'devclub' "
        "  AND vendas_end IS NOT NULL AND vendas_end < CURRENT_DATE "
        "ORDER BY cap_start DESC")
    out = [dict(lf=r[0], cap_start=r[1], cap_end=r[2], vendas_start=r[3], vendas_end=r[4])
           for r in linhas]
    return [x for x in out if (apenas is None or x["lf"] == apenas)]


def _gasto_por_campanha(conn, ini: date, fim: date) -> dict:
    """Gasto e leads por campanha na janela de captação. `analytics.ad_spend`."""
    linhas = conn.run(
        "SELECT campaign_id, campaign_name, SUM(spend), SUM(leads) "
        "FROM ad_spend WHERE client_id='devclub' AND platform='meta' "
        "  AND spend_date >= :i AND spend_date <= :f "
        "GROUP BY 1,2", i=ini.isoformat(), f=fim.isoformat())
    return {str(r[0]): dict(nome=r[1], gasto=float(r[2] or 0), leads=int(r[3] or 0))
            for r in linhas if r[0]}


def _realidade_por_campanha(conn, lf: dict) -> dict:
    """O que DE FATO aconteceu: leads, mistura de decis e compradores, por campanha.

    A compra conta se caiu dentro da janela de vendas DAQUELE lançamento — mesma regra
    que a nota do criativo usa, e pelo mesmo motivo: depois do carrinho fechar o lead só
    volta a receber oferta no lançamento seguinte, que é outro evento.
    """
    linhas = conn.run("""
        WITH cap AS (
          SELECT DISTINCT ON (lower(trim(c.email)))
                 lower(trim(c.email)) AS email, c.phone, c.utm_campaign
          FROM captacoes c
          WHERE c.lf = :lf AND c.utm_campaign IS NOT NULL
          ORDER BY lower(trim(c.email)), c.captured_at
        ),
        dec AS (
          SELECT DISTINCT ON (lower(email)) lower(email) AS email, decil
          FROM registros_ml
          WHERE created_at >= :ini AND created_at < :fim AND decil IS NOT NULL
          ORDER BY lower(email), created_at DESC
        ),
        comp AS (
          SELECT DISTINCT lower(trim(email)) AS email FROM sales
          WHERE sale_date >= :vi AND sale_date <= :vf
        )
        SELECT cap.utm_campaign, dec.decil,
               COUNT(*) AS n, COUNT(comp.email) AS compradores
        FROM cap
        LEFT JOIN dec  ON dec.email = cap.email
        LEFT JOIN comp ON comp.email = cap.email
        GROUP BY 1, 2
    """, lf=lf["lf"], ini=lf["cap_start"].isoformat(),
         fim=(lf["cap_end"] + timedelta(days=1)).isoformat(),
         vi=lf["vendas_start"].isoformat(), vf=lf["vendas_end"].isoformat())

    por_campanha: dict = {}
    for campanha, decil, n, compradores in linhas:
        d = por_campanha.setdefault(str(campanha), {"decis": {}, "leads": 0, "compradores": 0})
        d["leads"] += int(n or 0)
        d["compradores"] += int(compradores or 0)
        if decil is not None:
            d["decis"][f"D{int(decil):02d}"] = d["decis"].get(f"D{int(decil):02d}", 0) + int(n or 0)
    return por_campanha


def _id_da_campanha(utm) -> str | None:
    """O `campaign_id` que o tráfego cola no fim do UTM. Mesma regra do relatório."""
    ultimo = str(utm or "").split("|")[-1].strip()
    return ultimo if ultimo.isdigit() and len(ultimo) >= 10 else None


def conferir(lf: dict, conn, roas_alvo: float) -> list:
    """Uma linha por campanha: o que o teto teria dito, e o que aconteceu."""
    from src.data.reference_reader import read_rolling_reference
    from src.monitoring.teto import CalculadoraDeTeto

    # A referência é lida COM CORTE EM `vendas_end`: julgar um lançamento com a
    # referência de hoje seria trapaça, porque ela já viu o desfecho daquelas vendas.
    ref = read_rolling_reference("devclub", conn=conn)
    if not ref:
        return []
    # AJUSTE DE CANAL, aproximado e assumido de propósito: a referência tem a taxa de
    # cada canal, mas só no agregado — não tem conversão por decil DENTRO do canal.
    # Então a aproximação é escalar todos os decis pela razão canal/geral, o que supõe
    # que o degrau entre decis tem o mesmo formato em cada canal. Serve para medir o
    # TAMANHO do efeito; não serve como implementação final.
    canal = globals().get("_CANAL")
    if canal:
        conv = ref.get("conversion") or {}
        geral = (conv.get("overall") or {}).get("rate")
        do_canal = ((conv.get("by_channel") or {}).get(canal) or {}).get("rate")
        if geral and do_canal:
            fator = do_canal / geral
            import copy
            ref = copy.deepcopy(ref)
            for d in ref["conversion"]["by_decile"].values():
                d["conv"] = (d.get("conv") or 0) * fator
    calc = CalculadoraDeTeto.de_referencia_carregada(ref, roas_alvo=roas_alvo)
    if not calc.utilizavel:
        return []
    vps = (ref.get("conversion") or {}).get("economics", {}).get("value_per_sale")

    gasto = _gasto_por_campanha(conn, lf["cap_start"], lf["cap_end"])
    real = _realidade_por_campanha(conn, lf)

    saida = []
    for utm, dados in real.items():
        cid = _id_da_campanha(utm)
        g = gasto.get(cid) if cid else None
        if not g or g["gasto"] < MIN_GASTO or dados["leads"] < MIN_LEADS:
            continue
        t = calc.por_mistura_de_decis(dados["decis"])
        if not t.ok:
            continue
        cpl = g["gasto"] / dados["leads"]
        # FATOR DE RASTREAMENTO. `tracking_rate` = vendas_casadas / vendas_REAIS,
        # mediana de LF43-LF53 no config do cliente. Sem ele, o ROAS medido aqui conta
        # so a venda que a gente conseguiu atribuir a um lead, e subestima TODA
        # campanha pelo mesmo fator. O `revenue_forecast` ja corrige assim ha tempos.
        compradores = dados["compradores"]
        if globals().get("_RASTREIO"):
            tr = TAXA_DE_RECONHECIMENTO.get(lf["lf"], TAXA_MEDIANA)
            if tr and tr > 0:
                compradores = compradores / tr
        receita = compradores * (vps or 0)
        saida.append(dict(
            lf=lf["lf"], campanha=utm[:44], cid=cid,
            gasto=g["gasto"], leads=dados["leads"], compradores=dados["compradores"],
            cpl=cpl, teto=t.valor, dentro_do_teto=(cpl <= t.valor),
            roas_real=(receita / g["gasto"]) if g["gasto"] else None,
            bateu_a_meta=((receita / g["gasto"]) >= roas_alvo) if g["gasto"] else None,
        ))
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lf", help="confere um lançamento só")
    ap.add_argument("--roas", type=float, default=None,
                    help="meta de ROAS (default: a vigente no código)")
    ap.add_argument("--rastreio", action="store_true",
                    help="corrige a receita pelo fator de rastreamento: so ~52%% das "
                         "vendas reais sao casadas a um lead, entao medir ROAS com "
                         "venda casada subestima TODA campanha por quase metade")
    ap.add_argument("--canal", default=None, choices=("meta", "google", "organic"),
                    help="ajusta a conversão para o canal (o teto hoje usa a média de "
                         "TODOS, e orgânico converte 3,8x mais que Meta, inflando-a)")
    args = ap.parse_args()

    from src.monitoring.teto import ROAS_ALVO_PADRAO
    roas = args.roas if args.roas is not None else ROAS_ALVO_PADRAO

    conn = _conexao()
    try:
        lfs = _lancamentos_encerrados(conn, args.lf)
        globals()["_CANAL"] = args.canal
        globals()["_RASTREIO"] = args.rastreio
        print(f"TRAVA DO TETO · meta de ROAS {roas:.1f} · {len(lfs)} lançamentos encerrados")
        print(f"piso por campanha: R$ {MIN_GASTO:.0f} de gasto e {MIN_LEADS} leads\n")
        todas = []
        for lf in lfs:
            todas.extend(conferir(lf, conn, roas))
    finally:
        conn.close()

    if not todas:
        print("nenhuma campanha passou do piso — nada a conferir")
        return 1

    print(f"{'lançamento':<9}{'campanha':<34}{'CPL':>9}{'teto':>9}{'nosso sinal':>14}"
          f"{'ROAS real':>11}{'acertou?':>10}")
    print("-" * 96)
    acertos = 0
    for x in sorted(todas, key=lambda r: (r["lf"], -r["gasto"])):
        sinal = "aumentar" if x["dentro_do_teto"] else "reduzir"
        ok = (x["dentro_do_teto"] == x["bateu_a_meta"])
        acertos += ok
        print(f"{x['lf']:<9}{x['campanha']:<34}{x['cpl']:>8.2f}{x['teto']:>9.2f}"
              f"{sinal:>14}{x['roas_real']:>10.2f}x{'  sim' if ok else '  NÃO':>10}")

    # A matriz é o que importa, não a taxa de acerto solta: os dois tipos de erro
    # custam coisas diferentes. Dizer "aumentar" numa campanha que não bate a meta
    # QUEIMA dinheiro; dizer "reduzir" numa que bateria só deixa dinheiro na mesa.
    vp = sum(1 for x in todas if x["dentro_do_teto"] and x["bateu_a_meta"])
    fp = sum(1 for x in todas if x["dentro_do_teto"] and not x["bateu_a_meta"])
    fn = sum(1 for x in todas if not x["dentro_do_teto"] and x["bateu_a_meta"])
    vn = sum(1 for x in todas if not x["dentro_do_teto"] and not x["bateu_a_meta"])
    print(f"\n{'':>26}{'bateu a meta':>16}{'não bateu':>14}")
    print(f"  {'dissemos AUMENTAR':<24}{vp:>16}{fp:>14}   <- falso positivo QUEIMA verba")
    print(f"  {'dissemos REDUZIR':<24}{fn:>16}{vn:>14}")
    print(f"\n  acerto geral: {acertos}/{len(todas)} ({100*acertos/len(todas):.0f}%)")
    if vp + fp:
        print(f"  quando mandamos AUMENTAR, acertamos {100*vp/(vp+fp):.0f}% das vezes")
    print("\n  Leitura: o teto não precisa acertar tudo — ele precisa não mandar")
    print("  aumentar verba em campanha que queima. É o quadrante de cima à direita.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

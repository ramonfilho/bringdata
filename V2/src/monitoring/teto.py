"""Teto de CPL — derivado da referência rolante (NÃO é fonte nova).

    teto_cpl(grupo) = conversão(grupo) × valor_por_venda ÷ roas_alvo

- roas_alvo = 1.0 → BREAKEVEN: o CPL máximo pra não dar prejuízo (a pedido). Acima
  do teto, o grupo queima dinheiro; abaixo, sobra.
- valor_por_venda: fórmula da planilha devclub geral — cartão a R$2.000, boleto a
  50% (R$1.000) — ponderado pela mistura REAL cartão/boleto da janela da referência.
  A mistura vem das vendas de fato (não do pct histórico do config, que estava
  desatualizado: ~46,8% vs ~35,7% real recente → teto ~10% menor).

Reuso (/sw-architect): `forma_pagamento` (core.payment_method) é a fonte única de
gateway→forma; não reclassifico gateway aqui.

A MONTAGEM mora aqui, não nos relatórios (passo 1 do plano do teto, 14/08/2026)
======================================================================
`teto_cpl` sempre foi só a aritmética. Quem decidia QUAL conversão entra, com que
recorte de decil e com que ROAS eram os relatórios, cada um por conta própria:

  - o relatório de criativo montava dois baldes na mão (D9-D10 contra D1-D8) e
    interpolava pela fatia da campanha no topo;
  - o resumo diário lia uma taxa já pronta por balde de variante (Lead/Champion/
    Challenger).

Mesmo conceito, duas implementações, dois recortes. Quando os cinco baldes entrarem
(passo 2), mudar num lugar e esquecer o outro produziria dois tetos diferentes para o
mesmo cliente no mesmo dia — e ninguém saberia qual estava certo. Por isso a montagem
subiu para cá: `CalculadoraDeTeto` carrega a referência UMA vez e responde por
segmento, e os dois relatórios viraram clientes finos dela.

O resultado é um `Teto` com MOTIVO explícito, e não um `None` solto. Foram
encontrados 7 pontos onde o teto sumia em silêncio, e no resumo diário ele virava
string vazia: "não há teto" e "não deu para calcular" ficavam idênticos na tela do
gestor. O motivo é o que torna os dois distinguíveis. Ver
`docs/TETO_DE_CPL_DECISOES.md`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from src.core.payment_method import forma_pagamento, CARTAO, BOLETO

logger = logging.getLogger(__name__)

CARTAO_VALUE = 2000.0   # "cartão a 2k" (planilha devclub geral; ≠ ticket_contracted 2200)
BOLETO_HAIRCUT = 0.5    # boleto conta a 50% (risco de calote), convenção do debriefing

# ROAS alvo. 2,0 desde 14/08/2026 (decisão de negócio de 13/08): o teto responde "qual
# o CPL máximo para o retorno ser o DOBRO do investido". Antes era 1,0, o breakeven —
# que não é meta, é piso de sobrevivência, e mirar nele aceita lucro zero como
# resultado bom. Todo teto entregue cai pela metade nesta virada, e o gestor precisa
# saber disso ANTES, não ao abrir o relatório.
ROAS_ALVO_PADRAO = 2.0

# Os cinco baldes de decil, em pares.
#
# POR QUE NÃO DOIS (o que era até 14/08/2026): tudo de D1 a D8 recebia o mesmo teto,
# R$ 3,96, quando a conversão real dentro dessa faixa varia 5,2 vezes. Uma campanha
# inteiramente D7-D8 era mandada cortar verba tendo 59% de folga escondida; uma
# inteiramente D1-D2 recebia teto quase 3 vezes acima do que sustenta.
#
# POR QUE NÃO DEZ: sobre a referência viva (104.453 leads, 881 compradores), 5 dos 9
# pares vizinhos de decil são estatisticamente INDISTINGUÍVEIS (D2-D3, D3-D4, D4-D5,
# D5-D6 e D8-D9). Separá-los seria vender ruído como precisão. Em pares, o pior par
# vizinho ainda dá p = 4,6 × 10⁻³.
#
# Evidência completa e critério para revisitar (todo par vizinho com p < 0,05) em
# `docs/TETO_DE_CPL_DECISOES.md`, decisão 1.
BALDES_DE_DECIL = (
    ('D1-D2',  ('D01', 'D02')),
    ('D3-D4',  ('D03', 'D04')),
    ('D5-D6',  ('D05', 'D06')),
    ('D7-D8',  ('D07', 'D08')),
    ('D9-D10', ('D09', 'D10')),
)

# Por que os motivos são constantes e não literais espalhados: eles vão virar texto na
# tela do gestor e critério de alarme. Literal solto diverge entre chamadores.
MOTIVO_OK = 'ok'
MOTIVO_SEM_REFERENCIA = 'sem_referencia'            # nenhuma linha de referência
MOTIVO_SEM_VALOR_POR_VENDA = 'sem_valor_por_venda'  # referência sem economia apurada
MOTIVO_SEM_CONVERSAO = 'sem_conversao'              # o segmento não tem taxa apurada
MOTIVO_SEGMENTO_VAZIO = 'segmento_vazio'            # segmento sem lead nenhum
MOTIVO_SEM_DISTRIBUICAO = 'sem_distribuicao_de_decis'  # não sabemos em que faixa caiu

# CHAVES DE AMBIENTE QUE MUDAM O TETO SEM PASSAR POR COMMIT.
#
# São o pior caso da procedência: código tem histórico, dado tem carimbo, mas uma
# chave de ambiente muda o número e não deixa rastro em lugar nenhum. Já custou caro
# aqui — um deploy ligou `REFERENCE_SOURCE=rolling` a partir de um template sujo, sem
# ninguém pedir, e o relatório mudou sozinho.
#
# São gravadas junto do resultado porque não existe outra fonte a consultar depois.
CHAVES_QUE_MUDAM_O_TETO = ("REFERENCE_SOURCE", "LAUNCHES_SOURCE", "LEDGER_DECIL_READ_SOURCE")

# Encolhimento do histórico do criativo (Decisão 9). Platô medido: 250 a 4.000 dão
# praticamente o mesmo resultado no backtest; 2.000 é o valor documentado.
K_HISTORICO_CRIATIVO = 2000


def _configuracao_vigente() -> dict:
    """As chaves acima como estão AGORA. Ausente vira '(default)', que é informação:
    diz que ninguém definiu, e não que a chave não existe."""
    import os
    return {k: (os.environ.get(k) or "(default)") for k in CHAVES_QUE_MUDAM_O_TETO}


def value_per_sale_from_sales(sales_df, *, cartao_value: float = CARTAO_VALUE,
                              boleto_haircut: float = BOLETO_HAIRCUT) -> dict:
    """Valor médio por venda da janela, ponderado pela mistura REAL de gateways.

    Devolve dict {value_per_sale, pct_cartao, n_sales, cartao_value, boleto_value}.
    value_per_sale=None quando não há vendas classificáveis (o teto degrada pra None).
    """
    boleto_value = cartao_value * boleto_haircut
    empty = {"value_per_sale": None, "pct_cartao": None, "n_sales": 0,
             "cartao_value": cartao_value, "boleto_value": boleto_value}
    if sales_df is None or len(sales_df) == 0:
        return empty
    cols = list(getattr(sales_df, "columns", []))
    # read_analytics_sales renomeia gateway→origem; aceita os dois nomes.
    gw_col = "origem" if "origem" in cols else ("gateway" if "gateway" in cols else None)
    if gw_col is None:
        return empty

    formas = sales_df[gw_col].apply(forma_pagamento)
    known = formas[formas.isin([CARTAO, BOLETO])]
    n_known = int(len(known))
    if n_known == 0:
        return empty
    n_cartao = int((known == CARTAO).sum())
    n_boleto = n_known - n_cartao
    vps = (n_cartao * cartao_value + n_boleto * boleto_value) / n_known
    pct_cartao = n_cartao / n_known
    logger.info("[teto] valor_por_venda R$%.0f (cartão %.1f%% × R$%.0f + boleto %.1f%% × R$%.0f) "
                "sobre %d vendas", vps, pct_cartao * 100, cartao_value,
                (1 - pct_cartao) * 100, boleto_value, n_known)
    return {"value_per_sale": round(vps, 2), "pct_cartao": round(pct_cartao, 4),
            "n_sales": n_known, "cartao_value": cartao_value, "boleto_value": boleto_value}


def teto_cpl(conversion_rate, value_per_sale, roas_alvo: float = ROAS_ALVO_PADRAO):
    """CPL máximo pra bater `roas_alvo` dado conversão e valor por venda.
    None se faltar ingrediente. roas_alvo=1.0 = breakeven.

    Primitivo ARITMÉTICO. Quem monta os ingredientes é a `CalculadoraDeTeto` abaixo;
    esta função permanece pública porque é o que os testes exercitam diretamente e o
    que deixa a conta auditável sem instanciar nada.
    """
    if conversion_rate is None or value_per_sale is None or not roas_alvo or roas_alvo <= 0:
        return None
    return conversion_rate * value_per_sale / roas_alvo


def conversao_prevista_da_unidade(conv_modelo: Optional[float],
                                  leads_historico: int,
                                  compradores_historico: int,
                                  compradores_esperados: float,
                                  k: int = K_HISTORICO_CRIATIVO) -> Optional[float]:
    """Conversão prevista de uma UNIDADE (um criativo rodando numa campanha) — Decisão 9.

        conversão = conv_modelo × (peso × lift + (1 − peso))      peso = n ÷ (n + k)

    - `conv_modelo`: a mistura de decis da campanha (braço "público"), lida da
      referência. É o nível: quando o mercado se move, ele se move por aqui.
    - `lift` = compradores_historico ÷ compradores_esperados. O mérito RELATIVO do
      criativo: quantas vezes acima (ou abaixo) da média DA ÉPOCA em que ele rodou.
      `compradores_esperados` = Σ leads do criativo em cada lançamento passado × a
      conversão geral daquele lançamento — é o que ele teria vendido se fosse médio.
      Adimensional: mercado dobra, lift não muda.
    - `peso` cresce com o histórico: n=0 → 0 (estreante: só o modelo; é aqui que o
      palpite do TEXTO vai entrar como prior); n=8.000 → 0,8; n=40.000 → 0,95.
      O modelo NUNCA sai da fórmula.

    Regra de ouro do backtest preservada por contrato: o histórico passado aqui deve
    vir só de lançamentos ANTERIORES ao avaliado, nunca do próprio.
    """
    if conv_modelo is None:
        return None
    n = max(int(leads_historico or 0), 0)
    if n <= 0 or not compradores_esperados or compradores_esperados <= 0:
        return conv_modelo
    lift = max(int(compradores_historico or 0), 0) / float(compradores_esperados)
    peso = n / (n + float(k))
    return conv_modelo * (peso * lift + (1.0 - peso))


@dataclass(frozen=True)
class Teto:
    """O teto de um segmento, com o MOTIVO de ele existir ou não.

    `valor is None` nunca é a resposta inteira: `motivo` diz se faltou referência,
    faltou economia ou o segmento é que está vazio. É a diferença entre o gestor ler
    "não temos teto hoje" e "não conseguimos calcular", que hoje são a mesma coisa
    na tela dele.

    `referencia_as_of` é o carimbo: de qual reconstrução semanal da referência este
    teto saiu. Sem ele, "por que o teto era R$ 7,13 em 14/08?" não tem resposta dois
    meses depois, porque aquela referência já foi sobrescrita.
    """
    valor: Optional[float]
    motivo: str
    # Conversão ESPERADA usada na conta — já corrigida pelo fator de rastreamento
    # (a medida crua é conversao ÷ fator_rastreamento). O invariante vale sempre:
    # valor = conversao × valor_por_venda ÷ roas_alvo.
    conversao: Optional[float] = None
    valor_por_venda: Optional[float] = None
    roas_alvo: float = ROAS_ALVO_PADRAO
    # Fator de rastreamento (Decisão 9): só ~6 de 10 compradores casam com um lead,
    # e a decomposição de 15/08 mostrou que a correção legítima é ~1,2 (só as vendas
    # "sumidas" — 16% das não-casadas — podem ser de lead nosso; as outras 84% são
    # gente conhecida que comprou por outro funil). Vem MEDIDO do payload da
    # referência; 1,0 = referência sem o fator (comportamento antigo).
    fator_rastreamento: float = 1.0
    referencia_as_of: Optional[str] = None
    # ── PROCEDÊNCIA ─────────────────────────────────────────────────────────────
    # Três coisas mudam este número, e cada uma se registra de um jeito diferente:
    #
    #   o que varia sozinho   -> `conversao` e `valor_por_venda` acima, gravados como
    #                            VALOR, porque não há outra fonte a consultar depois
    #   decisão de código     -> `codigo`, um carimbo só, que responde por K, número
    #                            de baldes, fórmula do encolhimento e todo parâmetro
    #                            futuro sem precisar de coluna nova pra cada um
    #   configuração          -> `configuracao`, porque chave de ambiente muda o
    #                            número e não aparece em commit nenhum
    #
    # Com os três, "por que o teto era X naquele dia" é consulta, não arqueologia.
    referencia_id: Optional[str] = None      # único: "2026-08-03T19:15"
    codigo: Optional[dict] = None            # {commit, dirty, origem}
    configuracao: Optional[dict] = None      # {REFERENCE_SOURCE: ..., ...}

    @property
    def ok(self) -> bool:
        return self.valor is not None

    def arredondado(self, casas: int = 2) -> Optional[float]:
        return None if self.valor is None else round(self.valor, casas)


class CalculadoraDeTeto:
    """Carrega a referência UMA vez e responde o teto por segmento.

    Ponto único de montagem. Quem consome recebe a calculadora pronta (injeção de
    dependência) e chama o método do seu recorte, sem saber de onde a conversão veio
    nem qual é o ROAS alvo vigente.

    Dois construtores, porque os dois consumidores têm a referência em mãos de formas
    diferentes: o relatório de criativo lê do banco na hora, o resumo diário já a
    recebeu dentro do payload que vai renderizar. Ler o banco de novo lá dentro seria
    ir buscar o que já está na mão, e abriria a chance de os dois relatórios do mesmo
    dia usarem versões diferentes da referência.
    """

    def __init__(self, ref: Optional[dict], *, roas_alvo: float = ROAS_ALVO_PADRAO):
        from src.core.git_info import versao_do_codigo
        self._roas = roas_alvo
        conv = (ref or {}).get('conversion') or {}
        self._as_of = str((ref or {}).get('as_of') or '') or None
        self._ref_id = (ref or {}).get('referencia_id') or self._as_of
        # Lidos UMA vez, na construção: são constantes durante a vida da calculadora e
        # ler por linha custaria um subprocesso de git por campanha.
        self._codigo = versao_do_codigo()
        self._config = _configuracao_vigente()
        self._vps = (conv.get('economics') or {}).get('value_per_sale')
        self._by_decile = conv.get('by_decile') or {}
        self._by_bucket = conv.get('by_bucket') or {}
        # Fator de rastreamento MEDIDO pelo job da referência na mesma janela
        # (conversion.tracking.factor). Referência antiga sem a chave → 1,0.
        try:
            self._fator = float((conv.get('tracking') or {}).get('factor') or 1.0)
        except (TypeError, ValueError):
            self._fator = 1.0
        if self._fator <= 0:
            logger.warning("[teto] fator de rastreamento inválido (%s) — usando 1,0",
                           self._fator)
            self._fator = 1.0
        # Lift de plataforma MEDIDO pelo refresh (conversion.platform_lift):
        # o lead google converte acima do que os decis preveem (estudo 18/08,
        # +31%); inválido/ausente → 1,0 (comportamento antigo).
        self._lift_plataforma = conv.get('platform_lift') or {}
        self._tem_ref = bool(ref)

    def lift_da_plataforma(self, plataforma: str = 'google') -> float:
        p = self._lift_plataforma.get(plataforma) or {}
        if p.get('valido') and p.get('lift'):
            return float(p['lift'])
        return 1.0

    @classmethod
    def da_referencia(cls, client_id: str = 'devclub', *, conn=None,
                      roas_alvo: float = ROAS_ALVO_PADRAO) -> "CalculadoraDeTeto":
        """Lê a referência rolante do banco. Usado por quem ainda não a tem.

        `conn` só é repassado quando existe: sem isso a chamada mudaria de assinatura
        mesmo para quem não injeta conexão, o que é mudança de contrato disfarçada de
        refator (e foi exatamente o que os testes de orçamento por campanha pegaram).
        """
        from src.data.reference_reader import read_rolling_reference
        ref = (read_rolling_reference(client_id, conn=conn) if conn is not None
               else read_rolling_reference(client_id))
        return cls(ref, roas_alvo=roas_alvo)

    @classmethod
    def de_referencia_carregada(cls, ref: Optional[dict], *,
                                roas_alvo: float = ROAS_ALVO_PADRAO) -> "CalculadoraDeTeto":
        """Recebe a referência que o chamador já carregou. Não toca no banco."""
        return cls(ref, roas_alvo=roas_alvo)

    # ------------------------------------------------------------------ diagnóstico
    def _falta_base(self) -> Optional[str]:
        """O que impede QUALQUER teto de sair. None se a base está de pé."""
        if not self._tem_ref:
            return MOTIVO_SEM_REFERENCIA
        if not self._vps:
            return MOTIVO_SEM_VALOR_POR_VENDA
        return None

    @property
    def utilizavel(self) -> bool:
        """Se falso, nenhum segmento vai ter teto — o chamador degrada de uma vez."""
        return self._falta_base() is None

    @property
    def referencia_as_of(self) -> Optional[str]:
        return self._as_of

    def _monta(self, conversao: Optional[float], motivo_se_falta: str) -> Teto:
        proc = dict(referencia_as_of=self._as_of, referencia_id=self._ref_id,
                    codigo=self._codigo, configuracao=self._config,
                    fator_rastreamento=self._fator)
        base = self._falta_base()
        if base:
            return Teto(None, base, roas_alvo=self._roas, **proc)
        if conversao is None:
            return Teto(None, motivo_se_falta, valor_por_venda=self._vps,
                        roas_alvo=self._roas, **proc)
        # A conversão MEDIDA sobe pelo fator de rastreamento antes de virar teto:
        # a medida só enxerga os compradores casados, e a fatia "sumida" (falha de
        # casamento) pertence aos leads. Ver Decisão 9 do doc do teto.
        esperada = conversao * self._fator
        return Teto(teto_cpl(esperada, self._vps, roas_alvo=self._roas), MOTIVO_OK,
                    conversao=esperada, valor_por_venda=self._vps,
                    roas_alvo=self._roas, **proc)

    def de_conversao_medida(self, conversao_medida, origem: str = '') -> Teto:
        """Teto de uma conversão MEDIDA composta fora (ex.: o composto lift do
        criativo em `teto_por_chave`). Mesmo funil `_monta` de sempre: fator de
        rastreamento, valor por venda, ROAS e carimbos — nenhum caminho paralelo."""
        return self._monta(conversao_medida, MOTIVO_SEM_CONVERSAO)

    # ------------------------------------------------------------------ por decil
    def _taxa_dos_decis(self, decis) -> Optional[float]:
        """Conversão agregada de um conjunto de decis, ponderada pelo volume real.

        Soma compradores e soma leads antes de dividir — NÃO é média das taxas. A
        média das taxas daria o mesmo peso a um decil com 8 mil leads e a outro com
        12 mil, e o resultado não seria a conversão de ninguém.
        """
        c = sum((self._by_decile.get(k) or {}).get('conv', 0) or 0 for k in decis)
        n = sum((self._by_decile.get(k) or {}).get('leads', 0) or 0 for k in decis)
        return (c / n) if n else None

    def por_mistura_de_decis(self, distribuicao: Optional[dict]) -> Teto:
        """Teto de um segmento, pela distribuição de decis DELE.

        Substituiu `por_fatia_no_topo` em 14/08/2026. Aquele método só sabia que
        fatia do segmento estava em D9-D10 e jogava todo o resto num balde só, o que
        dava o MESMO teto para um criativo inteiramente D7-D8 e outro inteiramente
        D1-D2 — cuja conversão real difere 5,2 vezes. Foi removido em vez de mantido
        ao lado: dois jeitos de calcular o mesmo teto é como esta bagunça começou.

        A conta é uma média ponderada: cada balde entra com a conversão medida dele
        na referência, pesada por quantos leads DESTE segmento caíram nele.

        Args:
            distribuicao: `{'D01': n, ..., 'D10': n}` com a contagem de leads do
                segmento em cada decil. Chaves ausentes contam como zero.
        """
        if distribuicao is None:
            return self._monta(None, MOTIVO_SEM_DISTRIBUICAO)
        if not sum(int(v or 0) for v in distribuicao.values()):
            return self._monta(None, MOTIVO_SEGMENTO_VAZIO)

        soma, peso = 0.0, 0
        for _, decis in BALDES_DE_DECIL:
            n_balde = sum(int(distribuicao.get(d) or 0) for d in decis)
            if not n_balde:
                continue
            taxa = self._taxa_dos_decis(decis)
            if taxa is None:
                continue      # ver o comentário do peso, logo abaixo
            soma += n_balde * taxa
            peso += n_balde
        if not peso:
            return self._monta(None, MOTIVO_SEM_CONVERSAO)
        # Normaliza pelo peso CONHECIDO, não pelo total do segmento. Lead num balde
        # sem taxa apurada na referência sai da conta em vez de entrar como conversão
        # zero: excluir é neutro, contar como zero rebaixaria o teto sistematicamente
        # sempre que a referência tivesse um buraco.
        return self._monta(soma / peso, MOTIVO_SEM_CONVERSAO)

    # ------------------------------------------------------------------ por balde
    def por_balde(self, balde: Optional[str]) -> Teto:
        """Teto de um balde de variante do A/B (Lead, Champion, Challenger).

        A referência já traz a taxa apurada de cada balde, então aqui não há
        interpolação: é a conversão daquele grupo, medida.
        """
        taxa = ((self._by_bucket.get(balde) or {}).get('rate')
                if balde is not None else None)
        return self._monta(taxa, MOTIVO_SEM_CONVERSAO)

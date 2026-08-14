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

# ROAS alvo padrão. 1,0 = breakeven (o CPL máximo pra não dar prejuízo). A decisão de
# negócio de 13/08/2026 é subir pra 2,0, e isso é o passo 2 — deliberadamente FORA
# deste passo, que não muda nenhum número entregue, só de onde ele é montado.
ROAS_ALVO_PADRAO = 1.0

# Por que os motivos são constantes e não literais espalhados: eles vão virar texto na
# tela do gestor e critério de alarme. Literal solto diverge entre chamadores.
MOTIVO_OK = 'ok'
MOTIVO_SEM_REFERENCIA = 'sem_referencia'            # nenhuma linha de referência
MOTIVO_SEM_VALOR_POR_VENDA = 'sem_valor_por_venda'  # referência sem economia apurada
MOTIVO_SEM_CONVERSAO = 'sem_conversao'              # o segmento não tem taxa apurada
MOTIVO_SEGMENTO_VAZIO = 'segmento_vazio'            # segmento sem lead nenhum


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
    conversao: Optional[float] = None
    valor_por_venda: Optional[float] = None
    roas_alvo: float = ROAS_ALVO_PADRAO
    referencia_as_of: Optional[str] = None

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
        self._roas = roas_alvo
        conv = (ref or {}).get('conversion') or {}
        self._as_of = str((ref or {}).get('as_of') or '') or None
        self._vps = (conv.get('economics') or {}).get('value_per_sale')
        self._by_decile = conv.get('by_decile') or {}
        self._by_bucket = conv.get('by_bucket') or {}
        self._tem_ref = bool(ref)

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
        base = self._falta_base()
        if base:
            return Teto(None, base, roas_alvo=self._roas, referencia_as_of=self._as_of)
        if conversao is None:
            return Teto(None, motivo_se_falta, valor_por_venda=self._vps,
                        roas_alvo=self._roas, referencia_as_of=self._as_of)
        return Teto(teto_cpl(conversao, self._vps, roas_alvo=self._roas), MOTIVO_OK,
                    conversao=conversao, valor_por_venda=self._vps,
                    roas_alvo=self._roas, referencia_as_of=self._as_of)

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

    def por_fatia_no_topo(self, pct_topo: Optional[float]) -> Teto:
        """Teto de um segmento do qual só se sabe QUE FATIA dele está em D9-D10.

        É o recorte que o relatório de criativo tem hoje: cada linha carrega o
        `%D9-D10` e mais nada da distribuição. A conversão esperada interpola entre a
        taxa de quem está no topo e a taxa de todo o resto.

        LIMITE CONHECIDO, e é o que o passo 2 conserta: "todo o resto" são os decis 1
        a 8 juntos, cuja conversão real varia 5,2 vezes por dentro. Um segmento
        inteiramente D7-D8 e outro inteiramente D1-D2 recebem hoje o mesmo teto.
        Trocar isto exige a distribuição completa por linha, que o chamador ainda não
        carrega.

        Args:
            pct_topo: fatia dos leads em D9-D10, em PONTOS PERCENTUAIS (0 a 100),
                que é como as linhas do relatório já a carregam.
        """
        if pct_topo is None:
            return self._monta(None, MOTIVO_SEGMENTO_VAZIO)
        alto = self._taxa_dos_decis(['D09', 'D10'])
        baixo = self._taxa_dos_decis([f'D{i:02d}' for i in range(1, 9)])
        if alto is None or baixo is None:
            return self._monta(None, MOTIVO_SEM_CONVERSAO)
        f = pct_topo / 100.0
        return self._monta(f * alto + (1 - f) * baixo, MOTIVO_SEM_CONVERSAO)

    # ------------------------------------------------------------------ por balde
    def por_balde(self, balde: Optional[str]) -> Teto:
        """Teto de um balde de variante do A/B (Lead, Champion, Challenger).

        A referência já traz a taxa apurada de cada balde, então aqui não há
        interpolação: é a conversão daquele grupo, medida.
        """
        taxa = ((self._by_bucket.get(balde) or {}).get('rate')
                if balde is not None else None)
        return self._monta(taxa, MOTIVO_SEM_CONVERSAO)

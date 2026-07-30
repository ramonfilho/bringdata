#!/usr/bin/env python3
"""Etapa 0 do refator de fonte única de papel de campanha: cataloga as assinaturas
de campanha que têm GASTO e não têm rótulo em `analytics.campaign_labels`.

POR QUE ISSO EXISTE
-------------------
A tabela `analytics.campaign_labels` casa a assinatura de tag por IGUALDADE EXATA
(`tag_signature(utm_campaign)` → categoria). Toda variação nova de nome que o gestor
cria (sufixo `TESTEPROMESSA`, `DUPLICADOS`, prefixo `LLK`) gera uma assinatura NOVA
que não está catalogada. Assinatura não catalogada cai em `NEUTRO` no peso do grupo
de controle do treino (`classify_for_weights`), ou seja: o lead que FOI selecionado
por um evento de ML entra no retreino como se nenhum modelo o tivesse tocado.

Em 30/07/2026 havia R$ 3.250 de gasto Meta em 6 assinaturas órfãs (3 do challenger
jul_24 e 3 variações do HQLB).

O QUE FAZ
---------
1. Varre `analytics.ad_spend` na janela pedida, tokeniza cada `campaign_name` com a
   MESMA função da curadoria (`validation.campaign_classifier.tag_signature`) e lista
   as assinaturas com gasto que não estão na tabela.
2. Deriva a categoria de cada órfã pela tag do YAML de modelos ativos (substring
   `campaign_tag` → `role`), que é a fonte que o relatório já usa. Nada de adivinhar.
3. Reconcilia as assinaturas HQLB já existentes para a categoria do YAML (o abr28 foi
   promovido a Champion em 25/07 e a tabela ficou dizendo Challenger).

Categoria `Champion` e `Categoria` `Challenger` caem AMBAS no grupo `ML` do peso de
controle, então a reconciliação HQLB é semântica (não muda peso). O que muda peso é
catalogar as órfãs: elas saem de `NEUTRO` para `ML`.

Dry-run por padrão. Rollback: `DELETE FROM analytics.campaign_labels WHERE source = '<SOURCE>'`
para as inseridas, e restaurar a categoria antiga das reconciliadas (o script imprime
o valor anterior de cada uma antes de escrever).

MODO --check (guarda fail-loud, para rodar sozinho)
---------------------------------------------------
Sai com código 1 quando existe campanha COM GASTO que o sistema não sabe rotular, nas
duas réguas que importam:

  (a) papel do modelo indeterminado (`core.ab_arm.resolve_arm` devolve INDETERMINADO):
      o gasto dela cai no balde errado do relatório;
  (b) assinatura ausente de `analytics.campaign_labels`: o lead entra no retreino como
      NEUTRO, ou seja, como se nenhum modelo o tivesse tocado.

Esta guarda existe porque as duas falhas são MUDAS. Em 29/07/2026 três campanhas novas
(JUL24_TOP10/30/50) e uma QUENTE gastaram R$ 5.500 sem rótulo em lugar nenhum, e o único
sintoma foi uma linha do relatório parecendo zerada.

Uso:
    python3 -m scripts.seed_campaign_labels_faltantes                 # dry-run, 30 dias
    python3 -m scripts.seed_campaign_labels_faltantes --days 60
    python3 -m scripts.seed_campaign_labels_faltantes --apply
    python3 -m scripts.seed_campaign_labels_faltantes --check         # guarda (exit 1)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # .../V2
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:  # noqa: BLE001 — sem .env o chamador já falha na conexão
    pass

SOURCE_TAG = "rotulagem_fonte_unica_papel"

# role do YAML → categoria da tabela curada. Os dois caem em 'ML' no peso de controle;
# a distinção existe pro relatório, não pro treino.
_ROLE_TO_CATEGORIA = {"champion": "Champion", "challenger": "Challenger"}


def _yaml_tags() -> list[tuple[str, str]]:
    """[(TAG_UPPER, categoria)] do YAML de modelos ativos, challenger antes de champion.

    Reusa o MESMO campo (`campaign_tag` + `role`) que `ModelRegistry` já lê pra montar
    o bucket_map do relatório — não é uma segunda régua, é a mesma.
    """
    from src.validation.model_performance import ModelRegistry

    reg = ModelRegistry()
    out: list[tuple[str, str]] = []
    for tag, bucket in reg.bucket_map.get("tags", []):
        cat = _ROLE_TO_CATEGORIA.get(str(bucket).lower())
        if cat and tag:
            out.append((str(tag).upper(), cat))
    return out


def _categoria_de(campaign_name: str, yaml_tags: list[tuple[str, str]]) -> str | None:
    """Categoria pela tag do YAML (substring, precedência da lista). None = não é de modelo."""
    c = str(campaign_name or "").upper()
    for tag, cat in yaml_tags:
        if tag in c:
            return cat
    return None


def _check(*, days: int, client_id: str) -> int:
    """Guarda fail-loud. Exit 1 se alguma campanha com gasto não tiver papel resolvível
    (régua do relatório) ou não tiver assinatura curada (régua do peso de treino)."""
    from datetime import date, timedelta

    from src.core.ab_arm import INDETERMINADO, resolve_arm
    from src.data.analytics_connection import open_analytics_connection
    from src.data.campaign_labels_reader import read_campaign_labels
    from src.validation.campaign_classifier import tag_signature

    start = date.today() - timedelta(days=days)
    conn = open_analytics_connection()
    try:
        labels = read_campaign_labels(client_id=client_id, conn=conn)
        rows = conn.run(
            "SELECT campaign_name, sum(spend) FROM ad_spend "
            "WHERE spend_date >= :s AND spend > 0 AND platform = 'meta' GROUP BY 1",
            s=start.isoformat(),
        )
    finally:
        conn.close()

    sem_papel = []
    # Agrega por ASSINATURA, não por nome: nomes diferentes colapsam na mesma assinatura
    # (é o ponto do tokenizador), e listar duas vezes a mesma chave confunde o operador.
    _por_sig: dict[str, float] = {}
    for nome, spend in rows:
        gasto = float(spend or 0)
        if resolve_arm(campaign_name=nome) == INDETERMINADO:
            sem_papel.append((gasto, nome))
        sig = tag_signature(nome)
        if labels.get(sig) is None:
            _por_sig[sig] = _por_sig.get(sig, 0.0) + gasto
    sem_rotulo = [(g, s) for s, g in _por_sig.items()]

    print(f"janela: últimos {days} dias | {len(rows)} campanhas Meta com gasto\n")
    ok = True
    if sem_papel:
        ok = False
        print(f"!! {len(sem_papel)} campanha(s) SEM PAPEL RESOLVÍVEL "
              f"(R$ {sum(g for g, _ in sem_papel):,.0f}) — balde errado no relatório:")
        for g, n in sorted(sem_papel, reverse=True):
            print(f"   R$ {g:>9,.0f}  {n[:90]}")
    if sem_rotulo:
        ok = False
        print(f"!! {len(sem_rotulo)} assinatura(s) SEM RÓTULO CURADO "
              f"(R$ {sum(g for g, _ in sem_rotulo):,.0f}) — entram como NEUTRO no treino:")
        for g, sig in sorted(sem_rotulo, reverse=True):
            print(f"   R$ {g:>9,.0f}  {sig!r}")
        print("   conserto: rode este script sem --check e depois com --apply")
    if ok:
        print("OK — toda campanha com gasto tem papel resolvível e rótulo curado.")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=30, help="janela de gasto a varrer (default 30)")
    ap.add_argument("--apply", action="store_true", help="escreve (sem isso é dry-run)")
    ap.add_argument("--check", action="store_true",
                    help="guarda: exit 1 se houver campanha com gasto sem papel/rótulo")
    ap.add_argument("--client-id", default="devclub")
    args = ap.parse_args()
    if args.check:
        return _check(days=args.days, client_id=args.client_id)

    from src.data.analytics_connection import open_analytics_connection
    from src.data.campaign_labels_reader import read_campaign_labels
    from src.validation.campaign_classifier import tag_signature

    yaml_tags = _yaml_tags()
    print(f"tags do YAML (precedência): {yaml_tags}\n")

    end = date.today()
    start = end - timedelta(days=args.days)
    conn = open_analytics_connection()
    try:
        labels = read_campaign_labels(client_id=args.client_id, conn=conn)
        rows = conn.run(
            "SELECT campaign_name, sum(spend) FROM ad_spend "
            "WHERE spend_date >= :s AND spend > 0 AND platform = 'meta' "
            "GROUP BY 1",
            s=start.isoformat(),
        )

        # 1. órfãs com gasto → categoria pelo YAML
        orfas: dict[str, dict] = {}
        for nome, spend in rows:
            sig = tag_signature(nome)
            if labels.get(sig) is not None:
                continue
            cat = _categoria_de(nome, yaml_tags)
            e = orfas.setdefault(sig, {"spend": 0.0, "categoria": cat, "exemplo": nome})
            e["spend"] += float(spend or 0)
            if e["categoria"] is None:
                e["categoria"] = cat

        # 2. reconciliação: assinaturas existentes cuja categoria discorda do YAML
        recon: list[tuple[str, str, str]] = []  # (sig, atual, novo)
        for sig, atual in labels.items():
            for tag, cat in yaml_tags:
                if tag.lower() in sig.lower() and atual != cat:
                    recon.append((sig, atual, cat))
                    break

        print(f"=== ÓRFÃS com gasto nos últimos {args.days} dias ({len(orfas)}) ===")
        if not orfas:
            print("  (nenhuma)")
        for sig, e in sorted(orfas.items(), key=lambda kv: -kv[1]["spend"]):
            destino = e["categoria"] or "SEM TAG DE MODELO (pular)"
            print(f"  R$ {e['spend']:>9,.0f}  {sig!r:<42} -> {destino}")

        print(f"\n=== RECONCILIAR (tabela discorda do YAML) ({len(recon)}) ===")
        if not recon:
            print("  (nenhuma)")
        for sig, atual, novo in recon:
            print(f"  {sig!r:<42} {atual} -> {novo}")

        inserir = {s: e for s, e in orfas.items() if e["categoria"]}
        pular = {s: e for s, e in orfas.items() if not e["categoria"]}
        if pular:
            print(f"\n  !! {len(pular)} órfã(s) SEM tag de modelo no nome, não vou adivinhar:")
            for s, e in pular.items():
                print(f"     {s!r}  (R$ {e['spend']:,.0f})  ex: {e['exemplo'][:70]}")

        if not args.apply:
            print(f"\n[DRY-RUN] inseriria {len(inserir)}, atualizaria {len(recon)}.")
            print("          rode com --apply para escrever.")
            return 0

        n_ins = 0
        for sig, e in inserir.items():
            conn.run(
                "INSERT INTO analytics.campaign_labels "
                "(client_id, tag_signature, categoria, curated_at, source) "
                "VALUES (:c, :s, :cat, now(), :src) "
                "ON CONFLICT (client_id, tag_signature) DO NOTHING",
                c=args.client_id, s=sig, cat=e["categoria"], src=SOURCE_TAG,
            )
            n_ins += 1
        n_upd = 0
        for sig, atual, novo in recon:
            conn.run(
                "UPDATE analytics.campaign_labels SET categoria = :novo, curated_at = now(), "
                "source = :src WHERE client_id = :c AND tag_signature = :s",
                novo=novo, src=f"{SOURCE_TAG}_recon_de_{atual}", c=args.client_id, s=sig,
            )
            n_upd += 1

        print(f"\n[APPLY] inseridas {n_ins}, reconciliadas {n_upd}.")
        depois = read_campaign_labels(client_id=args.client_id, conn=conn)
        print(f"        tabela agora tem {len(depois)} assinaturas (antes {len(labels)}).")
        print(f"\nROLLBACK das inserções:")
        print(f"  DELETE FROM analytics.campaign_labels WHERE source = '{SOURCE_TAG}';")
        print(f"ROLLBACK das reconciliações (a categoria antiga está no próprio source):")
        print(f"  UPDATE analytics.campaign_labels SET categoria = split_part(source,'_recon_de_',2)")
        print(f"   WHERE source LIKE '{SOURCE_TAG}_recon_de_%';")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

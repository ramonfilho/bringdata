# Perfil de audiência — LF54 (em captação)

**Atualizado:** 2026-05-07  
**Janela LF54:** captação 2026-05-05 → 2026-05-11 (2,954 leads, 2/7 dias).  
**Vendas:** 2026-05-18 → 2026-05-24.

Comparação contra uma referência:
- **Top 5 ROAS:** LF40, LF41, LF44, LF45, LF47 (39,771 leads pooled, via Sheets)

Teste estatístico: chi-quadrado por característica categórica (`pool vs target`). Categorias normalizadas via `src.monitoring.data_quality.normalizar_categoria_para_comparacao` (sem acento, lower).

---

## LF54 vs Top 5 ROAS

| Característica | Categoria | Top 5 ROAS | LF54 | Δ |
|---|---|---:|---:|---:|
| Gênero | masculino | 81.7% | 72.4% | **-9.3** ⚠⚠ |
| Gênero | feminino | 18.3% | 27.5% | **+9.2** ⚠⚠ |
| Idade | 18 24 anos | 21.6% | 25.2% | **+3.7** ⚠ |
| Idade | 35 44 anos | 22.0% | 17.1% | **-4.9** ⚠ |
| Idade | 45 54 anos | 11.7% | 7.8% | **-3.9** ⚠ |
| Ocupação | sou cltfuncionario publico | 42.8% | 33.3% | **-9.5** ⚠⚠ |
| Ocupação | nao trabalho e nem estudo | 9.3% | 13.6% | **+4.3** ⚠ |
| Faixa Salarial | nao tenho renda | 25.1% | 30.1% | **+5.0** ⚠⚠ |
| Faixa Salarial | entre r2001 a r3000 reais ao mes | 19.4% | 15.9% | **-3.5** ⚠ |
| Faixa Salarial | entre r3001 a r5000 reais ao mes | 14.9% | 11.0% | **-3.9** ⚠ |
| Faixa Salarial | mais de r5001 reais ao mes | 8.1% | 6.0% | **-2.2** ⚠ |
| Tem Cartão de Crédito | nao | 58.2% | 62.1% | **+3.9** ⚠ |
| Tem Cartão de Crédito | sim | 41.8% | 37.8% | **-4.0** ⚠ |
| Já Estudou Programação | nao | 63.2% | 69.5% | **+6.3** ⚠⚠ |
| Já Estudou Programação | sim | 36.8% | 30.4% | **-6.4** ⚠⚠ |
| Tem Computador | sim | 87.4% | 76.4% | **-11.1** ⚠⚠ |
| Tem Computador | nao | 12.5% | 23.5% | **+11.0** ⚠⚠ |

## Significância (chi² pool vs target)

| Característica | n_pool | n_target | chi² | p | resultado |
|---|---:|---:|---:|---:|---|
| Gênero | 39,771 | 2,954 | 156.2 | 1.22e-34 | SHIFT |
| Idade | 39,771 | 2,954 | 283.9 | 3.99e-55 | SHIFT |
| Ocupação | 39,771 | 2,954 | 357.5 | 1.04e-70 | SHIFT |
| Faixa Salarial | 39,771 | 2,954 | 292.1 | 7.31e-57 | SHIFT |
| Tem Cartão de Crédito | 39,771 | 2,954 | 20.8 | 3.06e-05 | SHIFT |
| Já Estudou Programação | 39,771 | 2,954 | 50.7 | 1.00e-11 | SHIFT |
| Tem Computador | 39,771 | 2,954 | 292.3 | 3.39e-64 | SHIFT |

Legenda Δ: ⚠ ≥ 2pp · ⚠⚠ ≥ 5pp.

> **Captação ainda aberta:** dia 2/7. Re-rodar quando fechar em 2026-05-11.
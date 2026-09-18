# Business case: lead score and cost ceiling (as of 15/09/2026)

The canonical numbers of the system, the ones the README quotes. Source: the two-sheet
artifact "Lead score e teto de CPL" (15/09/2026,
https://claude.ai/code/artifact/716d63bc-4eab-49b0-90e2-884ed5a22869), built from the
tables below. The per-launch panels in this folder's siblings (`lf64_resultado/`,
`lf65_resultado/`, `lucro_ml_vs_lead/`) are the launch-by-launch view of the same data.

## Where the numbers come from

- **Leads and scores:** `analytics.cadastros` (every signup) joined to the ledger
  `registros_ml` (score, decile, model that scored the lead).
- **Sales:** `analytics.sales`, five payment gateways, matched to the lead by email and
  phone inside each launch window (`src/core/matching.py`).
- **Spend:** `analytics.ad_spend`, per ad and day, from the Meta account, with the 13% tax
  the operation pays on media.
- **Return per real:** matched revenue over spend, on the matched base only. Unmatched
  sales are not credited to any lead.

## Sheet 1: lead score

| Measure | Value |
|---|---|
| Return per real, tiers 8 to 10 | R$ 2.14 (44.1% of the leads) |
| Return per real, tiers 1 to 5 | R$ 0.89 (32.2% of the leads) |
| Conversion, tiers 8 to 10 against tiers 1 to 5 | 1.00% against 0.38%, lift 2.60x |
| Share of all profit in tiers 8 to 10 | 91.0% |

**Model against rules, same 58k leads.** A hand-built additive score (computer at home,
has studied programming, income, age band) puts a top 10% that converts 2.4x the average,
with 10 distinct scores. The model's top 10% converts 3.5x the average, with 53k distinct
scores. Base rate on the 129,597 leads with a survey: 1.19% (1,537 buyers).

## Sheet 2: cost ceiling per ad

Window Nov/2025 to Jul/2026, 483 ad×campaign pairs in 25 launches, 21 of them with ads on
both sides of the ceiling. The ceiling of each pair was recomputed point-in-time, using
only the launches before it (no look-ahead).

| Side of the ceiling | Return per real | Ads | Spend | Doubled their money |
|---|---|---|---|---|
| Respected the ceiling | R$ 2.52 | 258 | R$ 747k | 60% |
| Paid above it | R$ 1.18 | 225 | R$ 586k | 23% |

Inside wins in 20 of 21 launches, median 2.5x, p < 0.001, on R$ 1.33M of audited media.

## What these numbers do not say

- Inside a single audience the model separates less than across audiences: in DEV21 the
  lift within the cold audience was 1.06x, against 1.55x in LF56. Most of the profit comes
  from choosing which audiences and ads to buy, and the ceiling is the tool for that.
- The "A/B" between champion and challenger compares campaigns routed by UTM, not a
  randomized split; see `docs/AB_TEST.md`. Model verdicts come from the launch series with
  a single ruler (`decil_champion`, signups from 25/07/2026), never from one launch.
- Offline, the model's temporal test set gives AUC 0.73 and lift 3.3 (`docs/MODEL_CHANGELOG.md`);
  the online effect on Meta's delivery has no randomized control yet.

## Reproduction

The per-launch machine is versioned: `python3 scripts/relatorio_lancamento.py --lf <LF>` and
`python3 scripts/render_painel_lancamento.py docs/relatorios/<lf>_resultado` rebuild any
launch panel from the tables above. The script that aggregates the 25 launches into the
two sheets was run on 15/09/2026 and is not versioned yet; until it is, the artifact above
is the record.

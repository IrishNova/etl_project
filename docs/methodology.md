# Methodology & Design Decisions

A defensible record of the analytical choices behind the revenue-planning model, each
tied to the evidence that justifies it. Written so any decision here can be explained
and defended on its merits.

_Last updated: 2026-10-15._

---

## 1. What we are building

A weekly **stacked bar** for revenue planning. Each week has up to three layers, kept
strictly separate because they carry different certainty:

| Layer | Meaning | Certainty |
|---|---|---|
| **Guaranteed** | Revenue already under contract, recognized as it runs off | Certain — computed from data, no assumptions |
| **Expected renewals** | Revenue we expect to retain past expiry (GRR projection) | Estimated — a modeled expectation |
| **New revenue** | Projected net-new sales | Estimated — separate forecast (not yet built) |

**Principle:** never blur what we *know* from what we *assume*. The certain floor is
computed exactly; the projected layers are labelled as estimates and carry uncertainty.

---

## 2. Accounting basis

**Recognized revenue, not cash collected.** Subscriptions and maintenance are
stand-ready obligations, so under ASC 606 revenue is recognized **ratably (straight-line)
over the service period** — not when the invoice is paid. We therefore recognize
`arr_usd / 365.25` per **day** a contract is live.

- *Why not cash?* Cash is lumpy (often annual upfront) and answers a different question
  (collections timing). Recognized revenue answers "what have we earned," which is the
  planning basis. Cash timing can be added later as a separate view.
- **Scope: recurring contracts only.** Perpetual licences and one-time orders have no
  coverage window to run off, so they are excluded from this chart.

---

## 3. `is_active` / the active-rule

`is_active` is **not a stored fact** — it depends on the date you ask about (a contract
is active in June, expired in December). So:

- The warehouse stores only the **immutable coverage window** (`start_date`, `end_date`,
  `cancel_date`).
- Activity is derived by a single function, `active_as_of(as_of)`, and **materialized
  nightly** (a contract can only flip active↔expired at a day boundary, so nightly is the
  correct cadence — recomputing every ingest would be wasted work).

**Validation:** run at Product B's vendor snapshot date (2026-09-30), the rule reproduces
B's own `status` labels **1,115 / 1,115** — zero mismatches. The rule is trusted.

---

## 4. Guaranteed revenue runoff (the certain floor) — built

For every recurring contract, recognize `arr_usd / 365.25` per active day, from **today
forward** (past days are already earned), with a cancellation ending recognition early.
Day-level overlap handles partial first/last weeks exactly.

- **Result:** **$15,769,335** of contracted revenue still to recognize, over 155 weeks to
  2029-09.
- **Reconciliation:** the weekly buckets sum to each contract's directly-computed
  remaining value **to the cent** (we carry full precision internally and round only for
  display — rounding per bucket then summing drifts).
- **Cross-check:** week-0 active-licence count (1,067) equals the independently
  materialized `is_active` count. Two different calculations agree.

---

## 5. Renewal retention (GRR) methodology

### Metric
**Gross Revenue Retention (GRR)** — **revenue-weighted** (a churned $100k deal ≠ a churned
$5k deal) and **gross** (retained capped at the contract's own value; no credit for
expansion/upsell we can't cleanly measure). `retained = min(successor_arr, predecessor_arr)`.

### Reconstructing renewal events
Renewals are reconstructed from contract chains, matched **within `(company_id, product)`**
(A-maintenance renews A, B-subscription renews B). A contract's expiry is "renewed" if the
same company starts a successor contract near that expiry; greedy nearest-match claiming
prevents one successor from renewing two predecessors.

### Decision: renewal window = **[−30, +60] days** around expiry
Justified empirically from the gap between an expiry and its nearest successor start:

| gap (days) | <0 | 0 | 1–7 | 8–30 | 31–60 | 61–90 | 91–180 | 181–400 |
|---|---|---|---|---|---|---|---|---|
| events | 15 | 880 | 488 | 50 | 31 | 27 | 50 | 48 |

Renewals pile up at **0 and 1–7 days** (back-to-back) with a clear valley by ~30–60 days
(p90 = 29d). Beyond that is unrelated later activity, not renewal. The window captures the
real signal and excludes the noise.

### Decision: maturation lag = **60 days** (handling censoring) — the critical one
A contract that expired recently has **not had time to resolve** — counting it as "did not
renew" is wrong (right-censoring). We only score contracts whose expiry is older than the
maturation lag. The impact is enormous:

| Measurement | Logo renewal rate | GRR |
|---|---|---|
| Naive (all events — **wrong**) | 53.5% | **48.3%** |
| Matured only (**honest**) | 89.1% | **86.5%** |

The naive number counts 1,072 still-active contracts and recent expiries as churn. Ignoring
censoring would have reported the business bleeding half its revenue — it is actually
retaining ~86.5%. **This is the single most important methodological control in the model.**

### Decision: segment by **product × region**
All six cells have adequate matured samples, and the splits are real (not noise):

| product | region | n | logo % | GRR % |
|---|---|---|---|---|
| A | EU | 270 | 94.8 | 90.9 |
| A | NA | 475 | 91.6 | 88.6 |
| A | UK | 211 | 91.5 | 91.2 |
| B | EU | 111 | 81.1 | 80.1 |
| B | NA | 355 | 84.8 | 86.5 |
| B | UK | 127 | 82.7 | 86.4 |

**Product is the primary driver** — maintenance (A, ~89–91%) is materially stickier than
subscriptions (B, ~80–86%). Region is a secondary wrinkle. Sample sizes support
per-segment rates rather than one pooled number.

### Validation against the source
92.5% of reconstructed B renewals (459/496) carry B's own `is_renewal = True` flag — our
chain-matching agrees with the source's independent labels, so the reconstruction is sound.

### Non-stationarity: the rate drifts, so we recency-weight (not flat-average)
A flat historical GRR assumes the rate is stable. Cutting matured GRR by expiry year
(per product, with per-cell bootstrap bands) shows it is **not**, for A:

| Product A | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|
| GRR | 93.2% | 93.7% | 90.9% | 84.7% |
| n | 48 | 235 | 378 | 297 |

| Product B | 2022* | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|
| GRR | 64.3% | 86.1% | 78.9% | 85.7% | 89.4% |
| n | 12 | 81 | 132 | 195 | 173 |

- **A is genuinely softening** (93.7 → 90.9 → 84.7 on solid n; 2024 vs 2026 bands barely
  overlap). Its flat average (~90%) would overstate next year.
- **B shows no trend** — it wobbles (86/79/86/89) with heavily overlapping bands. Flat is fine.
- Noise traps respected: B-2022 (n=12, band 37–90) is ignored; `*` years are partly
  censored (only early-year expiries matured) so the latest point is not over-read.

**Decision: recency-weight the rate** (weight recent years more — e.g. last ~2 years or a
gentle exponential) rather than (a) a flat pooled average, which A proves is too rosy, or
(b) a fitted trend line through 4 noisy points, which would over-fit (Taleb). Recency-
weighting tracks A down to ~85% and leaves B near its stable ~87%. A's drift also earns a
**wider band + a genuine downside scenario**. The exact weighting is **settled by the
walk-forward backtest** (flat vs recency-weighted — whichever predicts better out of
sample), not chosen by eye.

---

## 6. Decisions locked

| Decision | Choice | Justification |
|---|---|---|
| Revenue basis | Recognized, straight-line (ASC 606) | Planning is about earned revenue; cash is a separate view |
| Chart scope | Recurring only | Perpetual/one-time have no runoff |
| Retention metric | Gross Revenue Retention (revenue-weighted) | $-impact matters; gross = no unmeasurable expansion credit |
| Renewal window | [−30, +60] days | Gap distribution: renewals cluster at 0–7d, valley by 30–60d |
| Maturation lag | 60 days | Removes censoring bias (48.3% → 86.5% GRR) |
| Segmentation | product × region | All 6 cells 111–475 events; product is a real driver |
| Reconstruction | chain-match within company × product | Validated 92.5% vs B's `is_renewal` flag |
| Rate over time | recency-weighted, not flat | A's GRR drifts down (93.7→84.7); flat would overstate. Exact weighting set by backtest |

---

## 7. Projection & uncertainty display (planned)

- **Point estimate = the bars.** Uncertainty = a **single whisker (P10–P90) on each week's
  total**, not a range per segment. One honest range per bar.
- The whisker **widens with horizon** (projecting multiple renewal cycles compounds
  uncertainty — `p^n` with error bars). A flat band would be a lie.
- **Fill encodes certainty:** guaranteed = solid, projected = lighter/hatched, so "known vs
  assumed" reads instantly.
- **Scenarios:** base / downside / upside, where downside includes a **stress case** (fat
  tails — retention can fall off a cliff in a downturn), not merely −1 standard error.

---

## 8. Backtesting (planned)

Walk-forward validation (modelled on the author's `pairs-trading` engine): **fit the rate
on a training window, freeze it, project the unseen window, score against actuals**;
rolling or expanding. A **maturation lag lives inside the loop** — a test window's actuals
are only scored once resolved. Metrics are forecast-quality, not returns:

- **Error/bias:** MAE, RMSE, mean signed error.
- **Band coverage:** did ~80% of actuals land inside the P10–P90 band? (Validates the
  *uncertainty*, not just the point.)
- **Pinball / interval score:** the proper scoring rule for a quantile forecast.

If the model does not validate, we report that plainly rather than torture the data.

---

## 9. Open risks

- **Stationarity:** the 86.5% GRR is pooled over 2021–2026. If retention is trending, a
  static rate hides it — the walk-forward backtest is designed to expose this.
- **Concurrency in matching:** companies with multiple concurrent same-product contracts
  could create spurious matches; mitigated by within-product matching and corroborated by
  the 92.5% flag agreement.
- **New-revenue layer:** a separate sales/bookings forecast, not yet designed.

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

### Net vs gross: NRR drives the projection (GRR is a KPI)

GRR caps each renewal at its prior value — deliberately conservative, no expansion credit.
But a revenue *forecast* should use the *actual* expected renewed value, so the projection
uses **Net Revenue Retention (NRR)** (uncapped successor value); GRR stays as a reported KPI.

Measured on the matured cohort: **GRR 86.5% → NRR 92.0%** (+5.5pts of expansion; 13% of
renewals expand, 7% contract, 80% flat; A 90→94%, B 85→91%). NRR is still **< 100%**, so the
recurring base still decays — ~8%/yr net vs ~14% gross — it softens the decline, it does not
reverse it. Using NRR (not GRR) is more accurate, not less honest. Re-backtested under NRR:
near-unbiased (−1.2%), recency still best, calibrated coverage ~73%; MAE a touch higher
because expansion adds genuine variance. Production config became **expanding + recency**
(edged rolling under NRR on bias, MAE and coverage).

## 5b. New-business layer (third, most speculative)

New business = bookings that are **not** renewals (B via its `is_renewal` flag; A
maintenance via the chain heuristic; one-time A-perpetual + C orders are always new).
It has **no anchor** (demand generation, not retention of a known base), and we lack
pipeline/headcount/macro drivers — so this is a **business-as-usual run-rate
continuation**, not a bottoms-up forecast. It gets the top of the stack, the lightest
texture, and the widest band.

**Composition** (5y): $55M net-new — **72% one-time** (A perpetual $30.7M + C $9.0M),
28% new recurring (B $12.5M, A $3.1M). **Growing ~+11%/yr** (unlike A's renewals, which
decline). On a recognized-revenue axis one-time is recognized at sale, so a steady
booking run-rate ≈ a steady recognized run-rate (the recognition-timing precision would
be false given the layer's uncertainty).

**Forecast = damped growth**, chosen by a 12-window walk-forward (new bookings resolve at
once, so no maturation lag — more power than GRR):

| scheme | bias | MAE | MAPE |
|---|---|---|---|
| flat | −$259k (−7%) | $611k | 17.5% |
| **damped (½ trend)** | **−$83k** | $654k | 19.0% |
| full trend | +$92k | $700k | 20.6% |

Full trend is the *worst* (over-predicts — the Taleb sin, confirmed). Flat is most
accurate but **sandbags** a growing business. **Damped** cuts the bias ~3× for a +7% MAE
cost that is swamped by the layer's ~18% inherent noise — "some growth expectation without
substantial risk." Flat is kept documented as the ultra-conservative fallback.

**Center = data-derived, never eyeballed.** The growth rate is genuinely unknowable from
this noisy data (the trend reads anywhere from +2% to +24%/yr depending on the window), so
we do **not** pick a growth number — the center is just the damped forecast, and the band
carries the honesty. (A judgment override is only warranted with information the data lacks
— e.g. a known sales-capacity change — and would be a *labelled scenario line*, never the
default center.)

**Band = trend uncertainty + level error, both persistent per path.**
- **Trend deviation** `~N(0, σ)` with **σ ≈ 9.4%/yr** — the *data-derived* spread of the
  annual-growth estimate across trailing windows (6–20 quarters). It compounds over years,
  so the cone spans "growth resumes" (P90) to "fades" (P10). This is measured disagreement,
  not an assumption.
- **Level error (~±18%)** — the one-quarter-ahead residual, held persistent.
Independent quarterly shocks are **not** compounded (that exploded the band to ±87%).
Renewals, by contrast, legitimately compound (renewed revenue feeds the next cycle). A
multi-step backtest to refine the horizon growth of the level error stays a documented
refinement.

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
| Retention rate | NRR for the projection, GRR as KPI | A forecast needs actual expected renewed value (expansion incl.); GRR 86.5%→NRR 92.0% |
| Production config | expanding train + recency-weighted | Won the walk-forward under NRR on bias, MAE, coverage |
| New-biz center | data-derived (damped), not a judgment | Growth unknowable from noisy data (+2% to +24%/yr by window); band carries it |
| New-biz trend band | ±σ≈9.4%/yr, compounding | Data-derived spread of the trend estimate across windows |
| Uncertainty band | empirical ±7%/cycle, compounded | Backtest showed bootstrap band too tight (18% cov); calibrated to realized errors (LOO ~73%) |
| New-business layer | include, damped (½ trend) | Completes the picture; damped beat flat on bias, trend on error — growth without the risky full extrapolation |
| New-business band | persistent ±18% level error | 1-qtr backtest residual; not compounded (that explodes). Multi-step backtest = refinement |

---

## 7. Projection & uncertainty display

- **Point estimate = the bars.** Uncertainty = a **single whisker (P10–P90) on each week's
  total**, not a range per segment. One honest range per bar.
- The whisker **widens with horizon** because the per-cycle error (±7%, from the backtest)
  **compounds** across renewal generations — ±0.1% near-term to ±12% at 3 years. A flat
  band would be a lie.
- **Fill encodes certainty:** guaranteed = solid, projected = lighter/hatched, so "known vs
  assumed" reads instantly.
- **Scenarios:** base / downside / upside, where downside includes a **stress case** (fat
  tails — retention can fall off a cliff in a downturn), not merely −1 standard error.

---

## 8. Backtesting — results

Walk-forward validation (modelled on the author's `pairs-trading` engine): **fit the rate
on matured events before T, freeze it, predict the cohort expiring in `[T, T+quarter]`,
score against the realized outcome**; rolling vs expanding × flat vs recency. The
**maturation lag lives inside the loop** — a window is only scored once `T + h + lag ≤
today`. Scope is honest: we validate the **one-cycle (gen-1)** renewal, the part data can
check; the multi-year compounding is mechanical given gen-1 and has no future to test
against. 11 fully-matured quarterly windows — limited power, stated plainly.

**Finding 1 — the point forecast is sound.** Near-unbiased (bias −0.3% to −0.5%), MAE
~$81k on ~$1.3M cohorts (**≈6%**). `X·p` works one cycle. **Recency beats flat** on every
metric → the recency decision is earned, not asserted. Chosen config: **expanding +
recency-weighted** (rolling under GRR; expanding edged it once the rate switched to NRR).

**Finding 2 — the bootstrap band was overconfident, and the backtest caught it.** Coverage
was only **18–36%** vs a nominal 80%: the bootstrap carried rate-sampling noise but not the
**drift + cohort idiosyncrasy** that actually move quarter to quarter.

**Fix — calibrate to realized error.** The realized relative errors `(actual−pred)/pred`
ARE the true out-of-sample dispersion: **≈ ±7% per quarter-cycle**. Leave-one-out coverage
then rises to **~73%**. We do **not** chase exactly 80%: at n=11, "8 of 11 covered" (72.7%)
is statistically indistinguishable from 80% (expected ~8.8, σ≈1.3), so forcing 80% would
overfit the metric. Honest statement: *calibrated to ≈±7%/quarter; limited power.*

**Forward band.** That ±7%/cycle dispersion feeds the Monte Carlo band (`band.py`): each
path draws one error per renewal cycle from the empirical residual pool and **compounds**
them, so the whisker widens with horizon off a backtested foundation — ±0.1% near-term
(contracted floor) to **±12% at 3 years**. With zero error a path reduces to the closed
form exactly (validation).

Verdict: the point model validates; the uncertainty is now empirical, not theoretical; and
where power is thin we say so rather than torture the data.

---

## 9. Open risks

- **Stationarity:** A's GRR is trending down. Addressed via recency-weighting + a rolling
  train window (both validated by the backtest); residual drift is absorbed into the
  empirical ±7%/cycle band rather than assumed away.
- **Statistical power:** only 11 fully-matured backtest windows, so coverage (~73%) can't
  be distinguished from 80%. More history (or shorter cohorts) would sharpen calibration.
- **New-business horizon:** the ±18% band is held persistent (1-quarter error); a
  multi-step backtest to measure how the error grows with horizon is a known refinement.
- **New-business dominance:** the layer is large and steady, which could make the total
  look healthy and mask the contracted-floor cliff — mitigated by texture-ranking the
  layers (solid→hatch→dots) so "guaranteed vs speculative" reads at a glance.

## 10. Operations — keeping projections live (planned)

- **Scheduled recompute.** Projections are materialized on a schedule, not computed per
  dashboard hit: a nightly/weekly cron re-runs the metrics chain and regenerates
  `projection_series.json` (+ chart), and the Flask API serves the latest file. Same
  pattern as the nightly `is_active` materialization. The chain runs in seconds and the
  MC is **seeded**, so the band is stable run-to-run (no flicker). Cadence is a config knob.
- **Self-adjustment.** The rate (recency-weighted, rolling) and the new-business run-rate
  (damped on a trailing window) are **refit each run**, so if renewals or new business
  deteriorate, the projections follow down automatically — no manual intervention.
- **Circuit-breaker.** An explicit tripwire for regime breaks: when live actuals fall
  outside the band for N periods, flag it and fall back to the conservative (flat) scheme.
  This alarm doubles as the signal for "is growth falling off" monitoring charts.
- **Concurrency in matching:** companies with multiple concurrent same-product contracts
  could create spurious matches; mitigated by within-product matching and corroborated by
  the 92.5% flag agreement.
- **New-revenue layer:** a separate sales/bookings forecast, not yet designed.

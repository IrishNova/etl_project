# Combining Pipeline-Driven and Run-Rate / Trend Forecasts into One Forward Projection

Scope: methodology for the handoff between a near-term, bottom-up pipeline (CRM)
forecast and a longer-term statistical run-rate / trend forecast across the
forecast horizon. Most sales-forecasting sources below are RevOps/FP&A vendor
blogs and practitioner writing; the academic sources are peer-reviewed. Vendor
benchmark numbers are flagged as rough / unsourced where noted.

## Q1 — Pipeline coverage ratio: definition, use, benchmarks, and implied trustworthy horizon

### Takeaway
Coverage ratio = (open qualified pipeline value) / (quota or target for the
period); the required ratio is essentially the inverse of win rate, so the
common 3x–4x "rule of thumb" is only valid when win rate matches the ~25–33%
it implicitly assumes. Coverage is most meaningful as a per-period, per-segment
decay curve, and comparing it across future quarters is the primary way to see
how far out a pipeline is still trustworthy.

### Cited Findings
- Coverage ratio is the inverse of win rate: a 33% win rate needs ~3x, 25% needs ~4x, 20% needs ~5x, 50% needs ~2x; 3:1–4:1 is a common baseline but only holds if your win rate matches the benchmark's embedded assumption — [BoostUp / Clari / fullcast, via search synthesis](https://www.clari.com/blog/pipeline-coverage-best-practices/)
- Segment benchmarks: SMB ~2.5x–3x; mid-market ~3x–4x; enterprise 3x–5x (one source says enterprise with 15–25% win rates needs 4x–7x) — [fullcast sales coverage ratios](https://www.fullcast.com/content/sales-coverage-ratios/)
- Coverage quality matters as much as quantity: high coverage built on stale, unqualified, or single-threaded deals is "a liability," and above ~5x can signal too many low-probability deals — [Clari pipeline coverage best practices](https://www.clari.com/blog/pipeline-coverage-best-practices/)
- Many orgs add a buffer, targeting ~1.5–2x the mathematical minimum; count only qualified, recently active deals in the numerator and match the pipeline period to the quota period — [heyIris practical guide](https://www.heyiris.ai/blog/what-is-sales-pipeline-coverage-a-guide-to-forecasting-with-confidence)
- Benchmark from your OWN win rate and cycle length, not a default 3x: some businesses hit target under 1x, others need 5x — [Weflow out-quarter pipeline view](https://www.weflow.ai/blog/out-quarter-pipeline-view)
- Coverage decays within a period, from ~3x at the start toward ~1x at the end, so each weekly reading should be compared against the expected point in the build, not a flat target — [Weflow out-quarter pipeline view](https://www.weflow.ai/blog/out-quarter-pipeline-view)
- For FUTURE quarters, coverage = Open Pipe Net ARR / Target Net ARR (no Booked ARR exists yet) — [GitLab handbook, via search snippet](https://handbook.gitlab.com/handbook/sales/field-operations/sales-strategy/analytics/pipeline-management-tools)
- A weighted pipeline (apply stage probability to each deal) gives a clearer read than a flat coverage multiple — [heyIris guide](https://www.heyiris.ai/blog/what-is-sales-pipeline-coverage-a-guide-to-forecasting-with-confidence)

### Inferences
- Required coverage ≈ (1 / win rate) × buffer; this is the bridge between a raw pipeline number and an expected-bookings number and should be computed per segment because win rates differ.
- "How far out is the pipeline trustworthy" can be read directly off the coverage-by-target-quarter curve: the quarter where coverage drops well below its historical same-week benchmark is where the bottom-up pipeline forecast stops being credible and the top-down/run-rate forecast should take over.

### Gaps
- Segment benchmark ranges conflict across vendor sources and none cite an underlying dataset; treat ranges as directional.

## Q2 — CRM forecast categories (Commit / Best Case / Pipeline / Omitted) and mapping to confidence and roll-ups

### Takeaway
The standard categories are Closed, Commit, Best Case, Pipeline, and Omitted;
they form a confidence ladder (Commit highest, Pipeline lowest, Omitted
excluded) and roll up cumulatively (Best Case total typically includes Commit
and Closed). They are the natural interface for blending because they already
separate high-confidence near-term bookings from speculative pipeline.

### Cited Findings
- Closed: already won in the period; signed contract/PO or closed-won status, close date in the current period — [Rework forecast categories](https://resources.rework.com/vi/libraries/pipeline-management/forecast-categories)
- Commit: deals the rep will stand behind, ~90–100% probability, backed by verbal/written buyer commitment — [Rework forecast categories](https://resources.rework.com/vi/libraries/pipeline-management/forecast-categories)
- Best Case: plausible but condition-dependent; in Salesforce the Best Case total INCLUDES likely-to-close + closed-won + Commit opportunities — [Outreach sales forecast categories](https://www.outreach.ai/resources/blog/sales-forecast-categories)
- Pipeline: open, early-stage deals, ~10–50% probability; populate coverage metrics but "shouldn't drive commitments"; new opps default here in most CRMs — [Rework](https://resources.rework.com/vi/libraries/pipeline-management/forecast-categories); [Outreach](https://www.outreach.ai/resources/blog/sales-forecast-categories)
- Omitted: excluded from the current forecast — pushed close date, stalled deals, follow-up-later, disqualified-but-not-yet-closed-lost, or on hold for budget/regulatory reasons — [Rework](https://resources.rework.com/vi/libraries/pipeline-management/forecast-categories)
- Governance warnings: some teams use Omitted as a "soft delete" to dodge coverage conversations; without governance, Commit can behave like an optimistic stage field; category should be set by criteria, not instinct, and overrides the deal's default stage-based probability — [Outreach](https://www.outreach.ai/resources/blog/sales-forecast-categories); [Rework](https://resources.rework.com/vi/libraries/pipeline-management/forecast-categories)
- Variations: some orgs replace Omitted with "Upside" or split "Push" vs "Disqualified"; naming is customizable per platform — [Rework](https://resources.rework.com/vi/libraries/pipeline-management/forecast-categories); [Outreach](https://www.outreach.ai/resources/blog/sales-forecast-categories)

### Inferences
- Roll-up ladder for a bottom-up forecast: Closed ⊂ Commit forecast ⊂ Best Case forecast ⊂ (Best Case + remaining Pipeline) = total coverage. This yields a built-in low/mid/high band (Commit = conservative floor, Best Case = mid, full pipeline-weighted = upside) that can be reconciled against the run-rate number.
- Categories map cleanly to the handoff: Commit/Best Case drive the current-quarter forecast; Pipeline feeds coverage analysis for out-quarters; Omitted must be watched so it is not used to hide shortfalls that the run-rate forecast would otherwise catch.

### Gaps
- Exact probability bands differ by vendor and are partly conventions (Rework's 90–100% / 10–50%); Salesforce defines categories by inclusion rules rather than fixed probabilities.

## Q3 — Horizon over which pipeline is complete vs where it "runs dry," detected from creation-to-close lead times

### Takeaway
A pipeline is only "complete" for a target period once enough lead time has
passed for the deals that will close in that period to have been created;
beyond roughly one sales cycle out, the pipeline is structurally incomplete
("unborn") and coverage looks artificially low. Detect the reliable horizon
empirically from the creation-to-close lead-time distribution and from coverage
decay by creation cohort.

### Cited Findings
- Sales cycle is measured from lead/opportunity creation to closed-won; pick one start point and apply it consistently; formula = total days start-to-close ÷ number of closed deals — [SPOTIO length-of-sales-cycle](https://spotio.com/?p=7800); [Teamgate](https://blog.teamgate.com/length-of-sales-cycle/)
- A 90-day cycle means revenue recognized today reflects selling effort from ~3 months ago; so a 30-day pipeline forecast misses most deals that will close in that window — horizon should cover at least one full cycle — [Saber glossary sales cycle length](https://saber.app/glossary/sales-cycle-length)
- Widely cited Implisit B2B benchmark: Lead→Opportunity ~84 days, Opportunity→Close ~18 days (~102 days lead-to-close), varying greatly by opportunity source — [Klipfolio / via search synthesis](https://www.klipfolio.com/resources/kpi-examples/sales/sales-cycle-length)
- "Already baked" logic: with a 180-day cycle, everything in the pipeline now had to be created ~2 quarters ago, so the current/next quarter can't be materially changed — [Intelligence by Intent: The next quarter is already baked](https://intelligencebyintent.com/insights/the-next-quarter-is-already-baked)
- Worked funnel example: $100k target ÷ $10k deal = 10 deals; at 3x coverage need $300k starting pipeline; backward through stages = 605 leads, with stage durations lead→MQL 60d, MQL→SAL 25d, SAL→SQL 5d, SQL→close 180d = ~270 days (~9 months) lead-to-close; a lead/MQL volume shortfall shows up ~9 months before it hits bookings — [Intelligence by Intent](https://intelligencebyintent.com/insights/the-next-quarter-is-already-baked)
- Plan ~8 quarters ahead because some enterprise deals take a year or more — [Intelligence by Intent](https://intelligencebyintent.com/insights/the-next-quarter-is-already-baked)
- Group pipeline by CREATION date (cohort), track each cohort's close rate as it matures, and compare cohorts only at the same age (young cohorts show lower close rates purely from cycle length); a cohort tracking well below norm at the same age is a quality problem, not a volume gap — [Weflow out-quarter pipeline view](https://www.weflow.ai/blog/out-quarter-pipeline-view)
- Concrete out-quarter example: current quarter 3.3x vs $32M target (healthy); next quarter 0.4x vs $36M target (serious gap) — the gap is visible only when you read coverage by target quarter — [Weflow](https://www.weflow.ai/blog/out-quarter-pipeline-view)
- Changes in cycle length may signal problems 60–90 days ahead of revenue (vendor glossary claim, uncited) — [Saber glossary](https://saber.app/glossary/sales-cycle-length)

### Inferences
- Empirical detection recipe: (1) build the distribution of (close date − creation date) from won deals; take a high percentile (e.g. P75–P90) as the "fully-born" horizon H. (2) For each future period t, the fraction of eventual deals already created ≈ CDF of that lead-time distribution evaluated at (period start − today). (3) Pipeline coverage for period t is trustworthy only where that fraction is high (near H out); beyond H the pipeline is structurally incomplete and coverage understates true bookings. (4) The crossover point — where "% of pipeline already born" falls below an acceptable threshold — is the natural handoff point to the run-rate/trend forecast.
- Coverage decay curves and creation-cohort close-rate curves are the two directly observable signals of the reliable horizon; both can be built from CRM stage-history data (which this project already has: pipeline_stage_history.csv, pipeline_opportunities.csv).

### Gaps
- No source gives a formal statistical test for the exact "runs dry" boundary; the percentile/CDF approach above is an inference synthesized from the lead-time and cohort guidance, not a cited method.

## Q4 — Best practices for blending: weighting, smooth handoffs, double-counting, bottom-up vs top-down reconciliation

### Takeaway
Best practice is horizon-dependent weighting (pipeline-heavy near term,
run-rate/top-down heavy long term), computing multiple independent forecasts
and reconciling the GAP as the signal, and treating the handoff as a blend
rather than a hard switch. Academic forecast-combination and hierarchical
reconciliation literature supports mechanical combination and equal-weight
averaging as strong defaults, and MinT optimal reconciliation for making
bottom-up and top-down forecasts coherent.

### Cited Findings
- Horizon → method mapping (practitioner): this month = weighted pipeline + rep adjustments (±5–10%); this quarter = multi-variable/ML with run-rate + capacity check (±10–15%); next quarter = weighted pipeline + signals, checked by top-down capacity (±15–20%); annual = top-down capacity × historical conversion, checked by bottom-up pipeline build (±20–25%) — accuracy bands are the article's own/unsourced — [Salesmotion 7 methods](https://salesmotion.io/blog/sales-forecasting-methods)
- Reconciliation procedure: run each method independently; compare; investigate divergences; the example $2M weighted-pipeline vs $1.5M run-rate = $500k gap is either unrealistic pipeline or genuine growth — determine which; document the assumptions each forecast requires — [Salesmotion](https://salesmotion.io/blog/sales-forecasting-methods)
- "Triangulate 2–3 methods and reconcile the gap; the gap is where the risk lives" — [Salesmotion](https://salesmotion.io/blog/sales-forecasting-methods); [pulseRevOps](https://pulserevops.com/blog/sales-forecasting-methods)
- Weighted pipeline = Σ(deal value × stage close rate), using YOUR historical stage conversion, not generic benchmarks; raw pipeline totals are a poor forecast ($5M pipeline may close $800k) — [Salesmotion](https://salesmotion.io/blog/sales-forecasting-methods); [Saber weighted pipeline](https://www.saber.app/glossary/weighted-pipeline)
- Run-rate assumes the future looks like the past; it breaks when markets/team size change; best used as a sanity check and for stable, high-volume businesses — [Salesmotion](https://salesmotion.io/blog/sales-forecasting-methods)
- Out-quarter coverage should subtract business you historically create AND close within the same period (never came from carry-in pipeline) — this is the explicit anti-double-count adjustment between pipeline and run-rate — [Weflow](https://www.weflow.ai/blog/out-quarter-pipeline-view)
- Gartner: fewer than 25% of sales orgs achieve forecast accuracy within 10% of actuals (only externally attributed figure; note the source article's own URL slug conflicts with the stated number — verify before citing) — [Salesmotion citing Gartner](https://salesmotion.io/blog/sales-forecasting-methods)
- Academic — combination beats single forecasts, greatest benefit at SHORT horizons and easier series; averaging beats unstructured combination — Lawrence, Edmundson & O'Connor (1986), Management Science — [INFORMS](https://pubsonline.informs.org/doi/fpi/10.1287/mnsc.32.12.1521)
- Academic — Armstrong & Collopy (1998), review of 47 studies: integrating judgment with statistics improves accuracy when experts have domain knowledge and trends are significant, but HARMS accuracy when judgment is biased or unstructured; equal-weights combining is the recommended benchmark, especially under high uncertainty/instability — [search synthesis of Armstrong & Collopy](https://ideas.repec.org/a/inm/ormnsc/v32y1986i12p1521-1532.html)
- Academic — judgment based on CONTEXTUAL knowledge (not technical) is the better input to combination forecasts (Lawrence et al. 1995, J. Operations Management); and human input works better as an INPUT to the statistical process than as after-the-fact manual adjustment of statistical output — [search synthesis](https://pubsonline.informs.org/doi/fpi/10.1287/mnsc.32.12.1521)
- Hierarchical reconciliation (makes levels coherent via ỹ = S·P·ŷ): bottom-up loses no low-level info but accumulates error upward; top-down is biased when leaf series have different growth rates; MinT (Wickramasuriya, Athanasopoulos & Hyndman 2019) reconciles all levels to minimize reconciled-error variance, G = (SᵀW⁻¹S)⁻¹SᵀW⁻¹, and generally performs best — [arXiv robust reconciliation](https://arxiv.org/pdf/2510.20383); [MetricGate top-down vs bottom-up](https://metricgate.com/blogs/forecast-reconciliation-top-down-vs-bottom-up/)
- Implementations: Nixtla HierarchicalForecast (Python) includes MinT; darts also implements reconciliation — [Medium: demystifying hierarchical forecasting](https://medium.com/@gmw172/demystifying-hierarchical-forecasting-6c0dc585ced8)

### Inferences
- A clean blending architecture: treat bottom-up pipeline (weighted by stage/forecast category) and top-down run-rate/trend as two independent forecasts of the same quantity, then combine with horizon-dependent weights w(t): w(pipeline) high near-term and decaying to ~0 beyond the reliable horizon H (from Q3), w(run-rate) rising to ~1 beyond H. Using the "% of pipeline already born" CDF from Q3 as w(t) gives a smooth, data-driven handoff instead of a hard cutoff.
- Forecast-reconciliation theory (MinT) is the rigorous version of "triangulate and reconcile": instead of eyeballing the gap, treat period-level pipeline forecasts and the aggregate trend forecast as a hierarchy and reconcile them so they are coherent and variance-minimizing; equal-weight averaging is the defensible simple fallback the academic literature endorses.
- Primary double-counting risks to guard against: (a) counting both carry-in pipeline AND in-period created-and-closed business in the same target (fix per Weflow); (b) summing Commit/Best Case/Pipeline categories that already nest (Best Case includes Commit/Closed); (c) adding a bottom-up pipeline number to a top-down run-rate number that already reflects the same deals — blend/reconcile, never sum.

### Gaps
- No source gives an explicit closed-form weighting schedule for blending pipeline vs run-rate across the horizon; the CDF-weighting scheme above is a synthesized inference.
- Most practitioner accuracy bands (±X%) are unsourced; only the Gartner <25%-within-10% figure is externally attributed, and even that has an internal inconsistency in its source.

## Q5 — The "unborn pipeline" problem (future bookings from deals not yet in the CRM)

### Takeaway
The problem is called out-quarter pipeline analysis: measuring pipeline being
built now for quarters not yet being sold, and accepting that pipeline is a
lagging output of pipegen decisions made 2–3 cohorts earlier. Orgs handle it by
coverage-by-target-quarter, creation-cohort tracking, and backward funnel math
run early enough in the quarter to still generate more pipeline — and by letting
a top-down run-rate/pipegen-capacity model carry the horizon where pipeline is
still unborn.

### Cited Findings
- Out-quarter read judges pipeline being built for future quarters by target quarter, segment, and creation cohort; run it in the back half of the current quarter (around week 6) — earlier is noise, later leaves no time to generate more — [Weflow](https://www.weflow.ai/blog/out-quarter-pipeline-view)
- Pipeline is a lagging output; the decision causing a shortfall was made "two or three cohorts back" — adding volume late can't fix a quality problem — [Weflow](https://www.weflow.ai/blog/out-quarter-pipeline-view)
- Teams typically check coverage once, by hand, at QBR as one blended number, which hides weak regions until the miss is visible — argues for continuous, segmented out-quarter tracking — [Weflow](https://www.weflow.ai/blog/out-quarter-pipeline-view)
- Decision thresholds: flag any segment >20% below its own coverage benchmark; compare the ratio to the same week in the prior 2–3 quarters before reacting; log one segment + one action (volume or quality) weekly and check whether the cohort moved — [Weflow](https://www.weflow.ai/blog/out-quarter-pipeline-view)
- Backward funnel / pipegen math quantifies the unborn requirement: target ÷ deal size × coverage = needed starting pipeline, expanded back through stage conversion rates to required lead/MQL volume, timed by stage durations (≈9 months lead-to-close in the example) — [Intelligence by Intent](https://intelligencebyintent.com/insights/the-next-quarter-is-already-baked)
- Tooling gap: in a Clari community thread, the vendor rep said they don't support viewing pipeline 2–3 quarters out beyond next quarter; practitioners work around it with the Forecast module, opp-source breakdowns, and coverage by stage for Q+3 — [Clari community thread](https://community.clari.com/general-q-a-7/ensuring-sales-is-creating-enough-new-pipeline-for-future-quarters-166)

### Inferences
- "Unborn pipeline" is exactly the region where the bottom-up pipeline forecast must defer to a top-down forecast. Two complementary top-down approaches fill it: (a) run-rate/trend extrapolation of historical bookings; (b) a pipegen-capacity / backward-funnel model that forecasts future bookings from current lead/MQL creation rates and historical conversion — the latter is more leading-indicator-driven and ties the unborn horizon back to marketing/SDR activity.
- The quantity to extrapolate with run-rate is specifically the "created-and-closed-in-period" business plus the expected yield of pipeline not yet born; subtracting carry-in pipeline (per Weflow) prevents double-counting when the two forecasts meet at the handoff.

### Gaps
- No source provides a validated model that converts current lead/MQL creation velocity into a probabilistic future-bookings distribution; the backward-funnel examples are deterministic point estimates.
- Evidence on how often out-quarter/unborn-pipeline discipline actually improves forecast accuracy is anecdotal (vendor case framing), not from a controlled study.

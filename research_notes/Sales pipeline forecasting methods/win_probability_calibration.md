# Calibrating Win Probability by Sales Stage from Historical CRM Pipeline Data

Scope: methodology for estimating P(win | stage, features) from historical won/lost
outcomes, and for correcting a miscalibrated CRM-stated probability field, for a
Python (pandas/scikit-learn) revenue-forecasting model. Sources range from
peer-reviewed/academic calibration literature to IBM Research applied work to
RevOps practitioner writing. Source quality is flagged throughout.

---

## Q1. Computing empirical stage-to-win conversion rates (cohort/flow methods) and pitfalls (open-deal censoring, survivorship)

### Takeaway
The core estimator is simple — of deals that reached a stage, what fraction eventually
closed won — but it is badly biased unless you (a) anchor on *when a deal entered the
stage*, not when it closed, (b) measure *cohorts/flows* rather than period-terminal
deals, and (c) handle still-open deals as **right-censored** rather than dropping them.
Dropping open deals is a survivorship bias that inflates the apparent win rate.

### Cited Findings
- **Stage win rate definition:** deals that eventually closed won ÷ deals that reached
  that stage; e.g. 16 Closed Won ÷ 40 deals that reached Stage 2 = 40%. Closed Won = 100%,
  Closed Lost = 0%; rates typically rise in later stages — [SaaSGrid: Stage Win Rate](https://saasgrid.com/pipeline/stage-win-rate)
- **Anchor on stage-entry date, not close date:** tie each deal to when it *entered* a
  stage (e.g. HubSpot "Entered Deal Stage" date) so recent closes don't skew results;
  CRM default probabilities are "typically based on intuition rather than historical
  performance" — [Databox / HubSpot win probability](https://databox.com/?p=189391)
- **Cohort / "flow" analysis beats period-terminal measurement:** with a ~9-month sales
  cycle, deals closing in one quarter were mostly generated ~3 quarters earlier, so a
  period view mixes different marketing conditions. The recommended fix is to "go back in
  time, grab a cohort of opportunities" (flow analysis) rather than all deals that hit a
  terminal state in a window — [Kellblog: Win Rates, Close Rates and Milestone vs. Cohort/Flow Analysis](https://www.kellblog.com/how-to-align-marketing-budgets-with-sales-targets-using-win-rates-close-rates-and-milestone-vs-flow-analysis/)
- **Right-censoring materially changes the number (Kellblog worked example):** before
  open deals were allowed to resolve, cohorts showed a 50% narrow win rate and 43% / 29%
  broad rates; after open deals resolved, the *true* narrow rate was 57% and broad rate
  40%. "Both these win rate calculations ignore deals that push out of a quarter."
  Kellblog names the persistent version the "rolling hairball" problem — [Kellblog](https://www.kellblog.com/how-to-align-marketing-budgets-with-sales-targets-using-win-rates-close-rates-and-milestone-vs-flow-analysis/)
- **Closed-cohort method (stable version):** take every opportunity that entered a defined
  stage in a period, wait until the cohort fully resolves, then compute won ÷ (won + lost).
  Moving the entry gate later in the funnel raises the reported rate with zero change in
  actual selling performance (denominator/entry-stage sensitivity) — [Tenbound/graph8: Win Rate SaaS KPIs](https://graph8.com/win-rate-saas-kpis-explained/)
- **Denominator choice matters:** win rate = won ÷ (won + lost) vs. close rate = won ÷ all
  qualified. Worked example: 200 qualified, 40 won, 90 lost, 70 faded → 20% close rate but
  30.8% win rate for the same cohort; the gap is the no-decision / silent-stall population.
  Also distinguish won÷closed from won÷created (lower, slower to settle) — [Tenbound](https://graph8.com/win-rate-saas-kpis-explained/); [Metabase: win rate](https://www.metabase.com/metrics/win-rate)
- **Don't divide current wins by all currently-open opps:** this "punishes a growing
  pipeline and flatters a stalling one"; let cohorts mature a fixed window (often 90 or 180
  days from creation) — [Tenbound](https://graph8.com/win-rate-saas-kpis-explained/); [Abmatic: Opportunity to Close Rate](https://blog.abmatic.ai/opportunity-to-close-rate)
- **Open deals = right-censoring, not missing data (statistical framing):** treat an open
  deal's current date as an end point that is "basically lost to follow-up"; you need the
  observation start date and end date (close-won date, close-lost date, or current date for
  open deals). Recommended tools: estimate the survivor function / hazard rate via event-
  history analysis (Kaplan-Meier, Cox regression) which were "designed to use partial
  histories" — [Gelman/Columbia statmodeling blog: BizStat modeling performance indicators for deals](https://statmodeling.stat.columbia.edu/2019/10/08/bizstat-modeling-performance-indicators-for-deals/) (statistician's blog; retrieved only via search summary — direct fetch returned HTTP 403)
- **Survivorship bias, general form:** keeping only records that reached a visible outcome
  overstates success; deleting incomplete records is safe only if data is Missing Completely
  At Random, and "survival is the opposite of random, because it is driven by the outcome
  itself." Practical rule: if you can't account for dropouts, treat every naive average as an
  *upper bound*, not the truth — [MetricGate: Survivorship Bias Inflates Your Performance Estimates](https://metricgate.com/blogs/survivorship-bias-in-performance-data/)
- **Segment before computing:** run new business, expansion, and renewal separately
  ("mixing them destroys accuracy"); also segment by deal-size band, source, product line —
  [Databox](https://databox.com/?p=189391); [Tenbound](https://graph8.com/win-rate-saas-kpis-explained/)
- **Count-based vs amount-weighted rates diverge:** amount-weighted probability "often
  reveals that early-stage probabilities are inflated by small deals that close easily" —
  [Prospeo: Weighted Pipeline](https://prospeo.io/s/weighted-pipeline)
- **Multi-stage / skip-stage correction:** a per-stage direct win rate understates true win
  chance when deals can jump or revert; illustrative formula true P = direct-win 40% +
  (advance 50% × next-stage 70%) = 75%, iterated to convergence. Holds only if outcomes
  don't overlap, so treat as illustrative — [Prospeo](https://prospeo.io/s/weighted-pipeline); [Pedowitz Group](https://www.pedowitzgroup.com/how-does-missing-probability-data-break-forecasts)

### Inferences
- A defensible pandas implementation: for each closed cohort (grouped by stage-entry
  month and segment), compute won ÷ (won + lost) only on *resolved* deals, and report the
  share still open / older than the typical cycle alongside it so censoring is visible.
- For rigor with many open deals, a Kaplan-Meier curve on time-from-stage-entry gives an
  eventual-win estimate that uses partial histories instead of discarding them; the gap
  between the naive won÷closed figure and the KM estimate quantifies the survivorship
  inflation.
- Early-stage rates should probably be computed amount-weighted *and* count-weighted; a
  large divergence is a signal to model with deal size as a feature (Q2) rather than a
  single per-stage constant.

### Gaps
- No peer-reviewed / textbook treatment of sales-funnel conversion with censoring was
  located; the censoring and survival-analysis framing comes from a statistician's blog
  and a general-purpose analytics vendor, not a sales-specific study. The Kellblog cohort
  numbers are a single practitioner worked example, not a benchmarked dataset.

---

## Q2. Moving from raw stage rates to a model (logistic regression vs gradient-boosted/ML classifiers; which deal features)

### Takeaway
Move from constant per-stage rates to a classifier when the per-stage rate hides
systematic variation by deal age/time-in-stage, size, product, source, segment, or rep.
Logistic regression is the standard interpretable, natively-probabilistic starting
point (and is what IBM Research deployed); gradient-boosted trees (XGBoost/LightGBM)
usually win on raw accuracy for structured sales data but need calibration (Q3).

### Cited Findings
- **Target framing:** binary — won (1) vs non-won (lost or still-pending) (0); model the
  log-odds of winning as a linear function of predictors, logit p = x'β, then map back to
  probability — [IBM Research, Yan, Gong, Sun, Huang, Chu, "Sales pipeline win propensity prediction: a regression approach," arXiv:1502.06229](https://arxiv.org/pdf/1502.06229); [arXiv:2501.03418](https://arxiv.org/pdf/2501.03418)
- **IBM chose Logistic Regression deliberately**, for three reasons: (i) LR "can directly
  produce probability instead of a score which lacks direct business interpretation";
  (ii) efficiency on four years of worldwide data (needed because interaction features blow
  up the feature set); (iii) business stakeholders need an interpretable, intuitive model —
  [arXiv:1502.06229](https://arxiv.org/pdf/1502.06229)
- **IBM feature set (Table I, "unary"/raw profile features):** geography (categorical),
  deal size = expected deal size in USD (categorical/binned), sector (categorical), new
  client (flag), lead age = days since opportunity created (continuous), industry
  (categorical), product/sub-brand (categorical); plus lead-profile, product-profile,
  seller-profile, customer-profile data — [arXiv:1502.06229](https://arxiv.org/pdf/1502.06229)
- **IBM "interaction" / time features:** the quarterly-prediction target has an extra
  time-stamp variable; because each lead is re-snapshotted weekly (features fi…fi+k−1
  often unchanged), they derive interaction features by *multiplying the week number* with
  static profiles (sales stage, opportunity owner, current quarter, lead age). Benefits:
  all weekly snapshots are usable (not redundant replicas) and scoring is stable week to
  week — [arXiv:1502.06229](https://arxiv.org/pdf/1502.06229)
- **IBM intuition confirmed:** "as it approaches the quarter end, the chance to win the lead
  becomes smaller and smaller" — i.e. time-to-deadline features carry signal —
  [arXiv:1502.06229](https://arxiv.org/pdf/1502.06229)
- **IBM evaluation:** ROC/AUC (insensitive to class imbalance, no cut-off needed) plus
  cumulative Gain score (ranks opportunities by propensity; business-interpretable);
  validated on a Fortune 500 B2B tech company, training sets built to balance seasonality
  (same quarter prior year) and recency (immediately prior quarter), e.g. 14Q1 trained on
  13Q1 + 13Q4. Gain scores reported per geography over 13 weeks (e.g. GCG model avg 0.686,
  Japan 0.749) — [arXiv:1502.06229](https://arxiv.org/pdf/1502.06229)
- **Typical feature families across studies:** client type, sector, lead age, sales stage;
  current total dollar amount (proxy for resources devoted); stage + momentum (recent
  changes in pipeline value / stage movement); lead/product/seller/customer profiles;
  engagement signals; timing / quarter-end proximity — [arXiv:2501.03418](https://arxiv.org/pdf/2501.03418); [arXiv:1502.06229](https://arxiv.org/pdf/1502.06229)
- **Logistic coefficients read as odds ratios, not absolute-probability changes;** linearity
  in log-odds means a unit change in a numeric feature multiplies the odds by a constant,
  an assumption that may fail for deal size or lead age — [marini.systems: Logistic Regression glossary](https://marini.systems/en/glossary/logistic-regression/)
- **Non-linearity example (RIT thesis):** three binary process/stakeholder signals
  (proof-of-concept initiation, CISO engagement, security-team involvement) each gave a
  4–5× uplift in mean predicted win probability; mid-market ($50M–$150M revenue) was the
  highest-probability segment while very large enterprises got *negative* SHAP
  contributions — a non-monotone pattern a plain logistic model needs splines/bins/squared
  terms to capture. In that thesis LR was still chosen as final model on joint-highest
  AUC 0.970, recall 0.911, Brier 0.0139 — [RIT thesis #12707](https://repository.rit.edu/theses/12707)
- **Interpretable vs accurate:** vendor guidance calls LR "the simplest and most
  interpretable option" and a good start, while tree-based methods (XGBoost/LightGBM)
  "typically deliver the best accuracy for structured sales data" (directional, vendor
  source) — [Lilly Tech aischool: Scoring Models](https://aischool.lillytechsystems.com/ai-deal-scoring/scoring-models.html)
- **Correlation caveat:** LR "does not yet have any machine learning characteristics" and
  results are "at least at a correlative level"; a feature like "CISO engaged" may reflect
  deal quality rather than cause a win — don't read coefficients causally — [marini.systems](https://marini.systems/en/glossary/logistic-regression/)

### Inferences
- A sound progression: (1) empirical per-stage rate baseline → (2) logistic regression on
  stage + deal age/time-in-stage + log(amount) + product + source + segment, with binning
  or splines for non-linear numerics → (3) benchmark a gradient-boosted model if AUC/Brier
  justify the loss of interpretability, always calibrating the GBM afterward (Q3).
- IBM's weekly-snapshot problem maps directly onto a CRM stage-history table: each snapshot
  of an open deal is a training row, so you either de-duplicate or add a time-since-entry
  feature (IBM's interaction trick) to avoid leaking the eventual outcome across replicas.
- Rep as a feature is double-edged: it captures real skill variance but risks overfitting to
  individuals and leaking; segment-level or rep-tenure encodings are safer than raw rep IDs.

### Gaps
- No study was found directly comparing calibrated LR vs calibrated GBM *on win-probability
  Brier score* for the same sales dataset; the LR-vs-GBM accuracy claim rests on a vendor
  source plus general ML literature (Q3), not a head-to-head sales benchmark.

---

## Q3. Probability calibration: reliability curves, Platt, isotonic, Brier; detecting and fixing a wrong CRM probability field

### Takeaway
Calibration = predicted probabilities match observed frequencies (of deals given ~0.8,
~80% should win). Diagnose with a reliability/calibration curve + Brier score; fix with
post-hoc Platt scaling (sigmoid, parametric, small-data) or isotonic regression
(non-parametric, needs ≳1000 samples, corrects any monotonic distortion). The same
reliability-curve diagnostic treats a CRM's stated probability field exactly as it treats
a model's output: bin by the stated value, compare to the actual win fraction, and remap.

### Cited Findings
- **Definition (authoritative):** a well-calibrated classifier's predict_proba "can be
  directly interpreted as a confidence level" — among samples given ~0.8, "approximately
  80% actually belong to the positive class" — [scikit-learn: Probability Calibration guide](https://scikit-learn.org/stable/modules/calibration.html)
- **Reliability diagram:** bin predictions; x-axis = mean predicted probability per bin,
  y-axis = fraction of positives per bin; use `CalibrationDisplay.from_estimator` /
  `calibration_curve`; pair with a histogram of samples per bin — [scikit-learn](https://scikit-learn.org/stable/modules/calibration.html)
- **Expected Calibration Error (ECE):** averages the absolute gap between predicted and
  observed frequency across (equal-width) bins — [letsdatascience: Probability Calibration](https://www.letsdatascience.com/blog/probability-calibration-why-high-accuracy-doesn-t-mean-you-can-trust-your-model); [MetricGate: Calibration Isotonic & Platt](https://metricgate.com/docs/calibration-isotonic-platt)
- **Brier score:** mean squared difference between predicted probability and binary outcome;
  lower is better. BUT it is a *strictly proper* score that mixes calibration (reliability),
  discrimination (resolution) and uncertainty (Murphy decomposition); sklearn warns "A lower
  Brier loss... does not necessarily mean a better calibrated model" — use it *with* a
  reliability diagram, or decompose it — [scikit-learn](https://scikit-learn.org/stable/modules/calibration.html)
- **Which models are miscalibrated how (academic):** boosted trees/stumps and max-margin
  methods (SVM) push probability mass away from 0 and 1 → sigmoid-shaped distortion; Naive
  Bayes pushes toward 0/1; neural nets and bagged trees are already fairly well calibrated.
  After Platt/isotonic calibration, "boosted trees, random forests, and SVMs predict the
  best probabilities." — [Niculescu-Mizil & Caruana, "Predicting Good Probabilities with Supervised Learning," ICML 2005, pp.625–632, doi:10.1145/1102351.1102430](https://mlanthology.org/icml/2005/niculescumizil2005icml-predicting)
- **Logistic regression is often well-calibrated by default** (canonical logit link gives the
  "balance property" in the unpenalized case); RandomForest shows a sigmoid curve and rarely
  outputs near 0/1 because base-model variance makes extreme averages hard — [scikit-learn](https://scikit-learn.org/stable/modules/calibration.html)
- **Platt scaling (sigmoid):** fit logistic P(y=1|f) = 1 / (1 + exp(A·f + B)), A,B by maximum
  likelihood; originally for SVM margins, assumes a sigmoid correction and symmetric
  calibration error (can fail under heavy class imbalance); "most effective for small sample
  sizes or when the un-calibrated model is under-confident." Being strictly monotonic it
  **preserves ranking/AUC** — [scikit-learn](https://scikit-learn.org/stable/modules/calibration.html); [MetricGate](https://metricgate.com/docs/calibration-isotonic-platt)
- **Isotonic regression:** non-decreasing step function minimizing Σ(yi − f̂i)² subject to
  monotonicity (solved by Pool-Adjacent-Violators / PAV); "can correct any monotonic
  distortion" but "more prone to overfitting, especially on small datasets"; performs "as
  well as or better than sigmoid when there is enough data (greater than ~1000 samples)."
  It *introduces ties* so it can change AUC — [scikit-learn](https://scikit-learn.org/stable/modules/calibration.html); [MetricGate](https://metricgate.com/docs/calibration-isotonic-platt)
- **Critical anti-leakage rule:** fit the calibrator on data disjoint from the classifier's
  training data; reusing training outputs "would result in a biased calibrator that maps to
  probabilities closer to 0 and 1 than it should." Use `CalibratedClassifierCV`
  (method="sigmoid" or "isotonic"); `ensemble=True` (default) fits a calibrator per CV fold
  and averages; `ensemble=False` uses `cross_val_predict` then one calibrator (cheaper). For
  an already-fitted model use `FrozenEstimator` with disjoint calibration data — [scikit-learn](https://scikit-learn.org/stable/modules/calibration.html)
- **Method-selection summary (sklearn):** small data / under-confident → sigmoid; >~1000
  samples → isotonic ≥ sigmoid; must preserve AUC/ranking → sigmoid; multiclass one-param →
  temperature scaling (softmax(z/T), T by log-loss on hold-out, doesn't change argmax so
  preserves accuracy) — [scikit-learn](https://scikit-learn.org/stable/modules/calibration.html)
- **Foundational isotonic reference:** Zadrozny & Elkan (2002) is the standard citation for
  isotonic-regression calibration of classifier scores (referenced by practitioner sources;
  original not retrieved) — [letsdatascience](https://www.letsdatascience.com/blog/probability-calibration-why-high-accuracy-doesn-t-mean-you-can-trust-your-model)

### Detecting/fixing a wrong CRM probability field specifically
- **CRM fields drift one way (optimistic):** stage probabilities "are usually set once during
  CRM setup and rarely updated to reflect actual win rates by stage," a pattern that "inflates
  win probability across the pipeline"; one case ran 25% weighting at proposal creation when
  closed-won history supported 20% — [mo.agency: Why your sales forecast is wrong](https://www.mo.agency/blog/why-your-sales-forecast-is-wrong); [Pedowitz Group](https://www.pedowitzgroup.com/how-does-missing-probability-data-break-forecasts); [coffee.ai: Sales Pipeline Mistakes](https://www.coffee.ai/articles/sales-pipeline-mistakes-forecasting-accuracy)
- **Detection procedure:** export ≥4 quarters of closed deals (≥8 if cycle >90 days), compute
  the % of deals that reached each stage and went on to close won, and compare against the
  probability the CRM applies at that stage; back-test quarterly on the prior 12 months. Note
  HubSpot "lacks a native report for stage-probability analysis — you'll need to export and
  compute externally." — [mo.agency](https://www.mo.agency/blog/why-your-sales-forecast-is-wrong); [coffee.ai](https://www.coffee.ai/articles/sales-pipeline-mistakes-forecasting-accuracy)
- **Time-in-stage omission is a top cause of CRM miscalibration:** one vendor claims deals
  closing within 45 days carry a 68% win rate vs 23% for deals open beyond 90 days (vendor
  figure, unverified) — i.e. a static per-stage % ignores dwell time — [coffee.ai](https://www.coffee.ai/articles/sales-pipeline-mistakes-forecasting-accuracy)
- **Stage-definition inconsistency across reps** (one marks "proposal sent" on emailing a PDF,
  another requires a formal SOW to the economic buyer) corrupts the mapping upstream; fix by
  defining each stage by a verifiable buyer commitment with documented evidence — [coffee.ai](https://www.coffee.ai/articles/sales-pipeline-mistakes-forecasting-accuracy); [mo.agency](https://www.mo.agency/blog/why-your-sales-forecast-is-wrong)

### Inferences
- The CRM "probability" field is just an uncalibrated score. The whole Q3 toolkit applies to
  it directly: build a reliability curve binning deals by the CRM's stated probability (its
  natural bins are the stage values 10/25/50/75%), plot observed win fraction per bin, and the
  diagonal gap is the miscalibration. An isotonic (or sigmoid) fit then gives a lookup
  remapping stated→empirical probability; isotonic is attractive here because the CRM field is
  already a coarse monotone step function and there are usually far more than 1000 closed deals.
- Because distortion is systematically optimistic, expect the calibration curve to sit *below*
  the diagonal (stated > actual); isotonic will compress the high stated values downward.
- For a GBM-based win model, do CRM-style calibration twice conceptually: calibrate the model
  with CalibratedClassifierCV, and separately treat the CRM field as a baseline to beat on
  Brier score.

### Gaps
- Original Platt (1999) and Zadrozny & Elkan (2002) papers were not directly retrieved (only
  via the sklearn guide and practitioner secondary sources); the ICML 2005 paper was obtained
  via an anthology summary, not full text. The 68%/23% and 25%/20% CRM figures are single-
  vendor anecdotes, not benchmarks.

---

## Q4. How practitioners treat the gap between a CRM-stated probability and an empirically-calibrated win probability

### Takeaway
Practitioners treat the CRM-stated stage probability as an unvalidated default — an
assumption, not a measurement — and the standard move is to replace it with empirical
win rates by stage (segmented), then layer deal-level signals (age, rep, size) and a
subjective "forecast category" overlay on top, with the two reconciled against actuals.

### Cited Findings
- **Weighted pipeline is only as good as its probabilities:** multiply each stage's open
  value by its win probability and sum (e.g. Stage1 25%, Stage2 40%, Stage3 65% →
  $2,500 + $16,000 + $52,000 = $70,500). CRM defaults "were never tested against outcomes...
  assumptions, not measurements, and they silently corrupt every weighted forecast" — [Prospeo: Weighted Pipeline](https://prospeo.io/s/weighted-pipeline); [SiftHub: weighted pipeline glossary](https://www.sifthub.io/glossary/weighted-pipeline)
- **The empirical replacement:** look back at closed deals, compute the share of deals that
  reached each stage and were eventually won; illustrative empirical ladder Discovery 12% /
  Qualification 25% / Proposal 45% / Negotiation 68%, using 6–12 months of closed data;
  historical models "require at least 12 to 18 months of clean CRM history to be meaningful" —
  [coffee.ai: Accurate Pipeline Forecasting in CRM](https://www.coffee.ai/articles/accurate-pipeline-forecasting-in-crm); [TheSalesBlog: individually weighted pipelines](https://www.thesalesblog.com/blog/improve-sales-forecasts-with-individually-weighted-pipelines)
- **A single pipeline-wide rate hides rep variance:** a 41% blanket win rate underestimates
  the forecast when deals belong to high-performing reps; recommendation is to compute win
  rates per rep *and* stage from CRM history — [TheSalesBlog](https://www.thesalesblog.com/blog/improve-sales-forecasts-with-individually-weighted-pipelines)
- **Stage alone misses deal age:** "a deal stuck in 'Proposal' for 180 days is less likely to
  close than a fresh one" — practitioners add age/engagement signals on top of the stage rate —
  [coffee.ai](https://www.coffee.ai/articles/accurate-pipeline-forecasting-in-crm); [Prospeo](https://prospeo.io/s/weighted-pipeline)
- **Forecast-category overlay (commit / best-case / pipeline):** a qualitative read of buyer
  intent used alongside stage probabilities; the discipline requirement is written definitions
  and measured outcomes per category so you can check whether "commit" actually closes at a
  high rate — otherwise "'commit' means something different to every rep" — [coffee.ai](https://www.coffee.ai/articles/accurate-pipeline-forecasting-in-crm)
- **Recalibrate and measure forecast accuracy on a cadence:** back-test stage probabilities
  quarterly; compare forecast vs actuals (weekly in one guide), which requires periodic
  pipeline *snapshots* because forecast accuracy compares what you predicted at a point in time
  to what actually closed — [coffee.ai: Sales Pipeline Mistakes](https://www.coffee.ai/articles/sales-pipeline-mistakes-forecasting-accuracy); [coffee.ai: Accurate Pipeline Forecasting](https://www.coffee.ai/articles/accurate-pipeline-forecasting-in-crm)
- **IBM contrast (applied research):** IBM evaluated its data-driven win-propensity model
  against "sales subjective rating" as a baseline, i.e. explicitly positioning the learned
  probability as superior to the human/CRM-stated judgment — [arXiv:1502.06229](https://arxiv.org/pdf/1502.06229)

### Inferences
- Practitioner consensus and the academic calibration view converge: the CRM-stated
  probability is a prior/heuristic to be *validated and remapped against outcomes*, never
  trusted as-is. The ML framing (Q3) makes this precise — the CRM field is an uncalibrated
  score whose reliability curve you measure and correct.
- A pragmatic production design that matches both literatures: (1) empirical, segmented
  per-stage rates as the backbone; (2) a calibrated classifier (LR or calibrated GBM) for
  deal-level P(win) using stage + age/time-in-stage + size + product + source + rep/segment;
  (3) keep the forecast-category overlay as a human signal but hold it to the same
  calibration test (does each category's observed win rate match its label); (4) snapshot the
  pipeline and back-test Brier/accuracy quarterly.

### Gaps
- Much of the practitioner material is vendor/consultant blog content; specific uplift claims
  ("10–15% / 15–25% higher forecast accuracy") appear without verifiable sources and should be
  treated as marketing, not evidence. No peer-reviewed source was found that formally quantifies
  how much a calibrated empirical probability beats a CRM-stated field on revenue-forecast error.

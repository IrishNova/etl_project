# Leakage-free Walk-forward Backtesting of Sales-pipeline Bookings Forecasts, and How to Score Them

Scope: methodology for backtesting a sales-pipeline *bookings* forecast using point-in-time
(as-of) data without look-ahead leakage, plus the accuracy and calibration metrics that make
the scoring honest. All findings target a Python implementation.

---

## 1. Point-in-time / as-of reconstruction from a stage-change history log

### Takeaway
A live CRM only stores *current* opportunity values, so you cannot recover a past pipeline by
querying it later. The fix is to persist history — either periodic full snapshots or an
event/stage-change log — and reconstruct "what we knew as of date T" with an **as-of join**
against validity windows. Slowly-Changing-Dimension Type 2 (SCD2) and event sourcing are the
two canonical patterns; bitemporal modeling (valid time + transaction time) is needed when late
corrections must not retroactively change past forecasts.

### Cited Findings
- In Salesforce and most CRMs, the pipeline lives in an opportunity table that keeps only current values, so a live CRM cannot show what the pipeline looked like on a past date; you must save periodic forecast/pipeline snapshots into a separate table (Daily/Weekly/Monthly), or capture each change as it happens — you cannot reconstruct a past forecast after the fact — [Coffee.ai: Accurate Pipeline Forecasting in CRM](https://www.coffee.ai/articles/accurate-pipeline-forecasting-in-crm).
- SCD Type 2 exists specifically so historical states can be reproduced: instead of overwriting, you close the old row and insert a new version; an as-of query then filters `valid_from <= T AND valid_to > T`, returning exactly one row per entity — the version valid at timestamp T — [Microsoft Learn: Implement SCD Type 2](https://learn.microsoft.com/en-us/training/modules/design-implement-data-modeling-unity-catalog/7-implement-slowly-changing-dimension-type-2); [MongoDB docs: Slowly Changing Dimensions](https://www.mongodb.com/docs/v8.0/data-modeling/design-patterns/data-versioning/slowly-changing-dimensions).
- The traditional SCD2 implementation is a nightly ETL job that compares today's snapshot with yesterday's, detects changes, closes old rows, and opens new ones; a streaming alternative maintains history continuously — [Data Engineer Academy: SCD Type 2 with SQL and dbt](https://dataengineeracademy.com/blog/slowly-changing-dimensions-type-2-with-sql-and-dbt/).
- The standard leakage fix in ML feature stores is the **as-of join**: select the feature value whose timestamp is the latest one at or before the label-event timestamp; Feast/Tecton expose this via `get_historical_features()`, and hand-written SQL for it is an `ASOF JOIN` or a lateral subquery with a time filter — [RisingWave: Point-in-Time Joins in SQL](https://risingwave.com/blog/point-in-time-joins-ml-training-sql); [Towards Data Science: Point-in-time correctness](https://towardsdatascience.com/point-in-time-correctness-in-real-time-machine-learning-32770f322fb1).
- A credit-default example shows the trap: a naive join on user ID retrieves the aggregate (e.g., transaction count) as of *today*, not as of the application date; offline metrics look strong, then production underperforms — this is "future leakage" / look-ahead bias — [Towards Data Science: Point-in-time correctness](https://towardsdatascience.com/point-in-time-correctness-in-real-time-machine-learning-32770f322fb1).

### Inferences
- A stage-change history log is an event stream, so an SCD2 table of opportunities is best viewed as a *materialized projection* of that log. Two reconstruction routes: (a) replay events up to T from an empty state (exact, but costly over long histories — use periodic snapshots to speed it up); (b) derive validity intervals where each row's `valid_from` is an event time and `valid_to` is the next event time for the same opportunity, turning as-of reconstruction into a simple range filter.
- For a pipeline model this means: for each as-of date T, materialize the set of open opportunities with the stage, amount, and close-date they carried *as of T only*, and compute features (stage, age-in-stage, amount, rep, product) from that frozen view. In pandas this is `pd.merge_asof(labels, features, on="ts", by="opp_id", direction="backward")`.
- Bitemporal modeling matters precisely because CRM data is restated: a close-date or amount corrected *after* T should be visible in "what was true" queries but must be excluded from "what we knew at T" (the view the model is allowed to see). Keep both `valid_time` (when it was true in the business) and `transaction_time`/`record_time` (when the system learned it).

### Gaps
- Search results described point-in-time correctness thoroughly but gave no primary database-literature source that names and formalizes the two-axis *bitemporal* design (e.g., Snodgrass); the bitemporal framing above is synthesized from the as-of-join and SCD2 sources rather than a single authoritative bitemporal reference.

---

## 2. Common leakage traps in pipeline-forecast backtests, and how to avoid them

### Takeaway
The dominant trap is training or evaluating on information that did not exist at the forecast
origin: final deal outcomes, fields updated after the as-of date, restated close dates/amounts,
survivorship (only deals that still exist in today's CRM), and preprocessing fit on the full
series. Each inflates the backtest relative to live performance.

### Cited Findings
- A model trained on final stages or later-corrected close dates sees data unavailable at forecast time, which inflates backtest results relative to live performance — without snapshots this leakage makes backtests look better than reality — [Coffee.ai: Accurate Pipeline Forecasting in CRM](https://www.coffee.ai/articles/accurate-pipeline-forecasting-in-crm).
- Preprocessing before splitting leaks future information: normalizing, smoothing, decomposing, or extracting features (tsfeatures, catch22) on the full series must instead be fit on the training data only, and recomputed over input windows if they change over time — [Forecast Evaluation for Data Scientists (Hewamalage, Ackermann, Bergmeir 2022/2023), arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716).
- Wrong-horizon / availability leakage: using data that arrives after the forecast time (e.g., a full-day summary used for a next-day forecast) leaks information — align data timing with when forecasts are actually produced — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716).
- Cross-series leakage: in global models, unaligned series can carry future information about other series; rolling retraining mixes test and train data, so verify implementations rather than trusting them — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716).
- A clean win-rate backtest conditions on state at each start date, not today's view: analyze all deals that were *in a specific stage at the start of each month* over the prior four quarters; and don't use unvalidated CRM default probabilities ("Proposal = 60%") — [Coffee.ai: Accurate Pipeline Forecasting in CRM](https://www.coffee.ai/articles/accurate-pipeline-forecasting-in-crm).

### Inferences
- Survivorship bias is the pipeline-specific analog of look-ahead: a backtest built from today's CRM only sees opportunities that still exist, so deleted/archived/purged deals and deals that dropped out early are missing, pushing historical win and conversion rates too high. Mitigation: include *every* opportunity that was open at each snapshot date, including those later lost or removed, and verify that snapshot record counts stay stable over time (a sudden drop signals purged/survivorship-filtered rows). (Not directly in the sources; synthesized from the look-ahead and reconstruction findings.)
- Restatement leakage is handled by the bitemporal rule from Q1: the label (did the deal book, and for how much, in period P) uses *final* valid-time truth, but every feature uses only transaction-time-<=T knowledge.
- Practical leakage checklist for a pipeline backtest: (1) freeze features at T via as-of join; (2) derive the label from final outcomes but never expose post-T fields as features; (3) fit scalers/imputers/encoders on the training window only; (4) include churned/deleted opportunities in each historical snapshot; (5) leave a horizon-length gap between train and target windows (see Q3); (6) unit-test the reconstruction by confirming a re-run "as of T" never references a timestamp > T.

### Gaps
- No academic/primary source was found that quantifies the *magnitude* of backtest inflation from each trap specifically in a sales-pipeline setting; the RevOps sources (Coffee.ai) are vendor blogs, so treat specific numbers as indicative only.

---

## 3. Walk-forward / rolling-origin evaluation and train/test split discipline

### Takeaway
Use rolling-origin evaluation (a.k.a. time-series cross-validation, tsCV, or prequential
evaluation): move the forecast origin forward through time, always training on the past and
testing on the future, refitting or updating at each step. It gives many forecasts per horizon
and mirrors production. Never use random k-fold on temporally dependent data, and always leave
a horizon-length gap for multi-step forecasts.

### Cited Findings
- Rolling-origin always trains on past observations and tests on future ones, keeping temporal order intact, unlike k-fold CV; Hyndman's `tsCV` applies the method to y1..yt for t=1..T−h and returns errors e_{t+h} = y_{t+h} − ŷ_{t+h|t}, with a `window` argument for a fixed-length rolling window and an `initial` period skipped at the start — [Hyndman, "Cross-validation for time series" (Hyndsight)](https://robjhyndman.com/hyndsight/tscv/); [forecast::tsCV R docs](https://search.r-project.org/CRAN/refmans/forecast/html/tsCV.html).
- Rolling origin gives multiple forecasts per horizon step (supporting a forecast distribution per step) and matches production where new actuals arrive; fixed origin gives only one forecast per horizon, mixes very different horizons, and may reflect one business phase — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716).
- Window choice: use an **expanding window** for short series; use a **sliding/rolling window** when old data may hurt (especially pure-AR ML models and after regime changes) — one empirical study found sliding windows performed best, and expanding windows can overestimate validation error in streaming settings — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716).
- Random k-fold CV breaks temporal order (handles serial correlation poorly, can put future observations in training, can drop whole seasonal periods); it is valid only for pure-AR models that capture the autocorrelation — check with a Ljung-Box test on out-of-sample residuals (significant autocorrelation ⇒ underfitted ⇒ CV too optimistic) — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716).
- Partitioning guidelines: long series → prefer tsCV; non-stationary series → use order-preserving validation, not k-fold unless non-stationarity is removed; gradual drift → a validation block at the end can be more appropriate; abrupt structural breaks → no method reliably estimates the error — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716).
- Always benchmark against a naïve forecast ŷ_{t+h}=y_t and a seasonal-naïve for seasonal series; for random-walk-like series the naïve is often the best achievable and small gains over it may be chance — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716).
- Python tooling: scikit-learn `TimeSeriesSplit` is an expanding-window splitter (train starts at the beginning and grows; `max_train_size` caps it into a sliding window); sktime `SlidingWindowSplitter` takes a fixed `window_length`, forecast horizon `fh`, and `step_length`; sklearn's `TimeSeriesSplit` does *not* add a gap, so multi-step forecasts risk target leakage unless you enforce a gap of at least the horizon — [sklearn/sktime walk-forward tutorials](https://blog.devgenius.io/how-to-implement-time-series-cross-validation-in-python-1ce8aa6f9a6c); [temporalcv WalkForwardCV](https://temporalcv.readthedocs.io/en/stable/api/cv.html).

### Inferences
- For bookings forecasts the "origin" is each as-of snapshot date and the "horizon" is the number of future periods you forecast bookings for (e.g., end-of-quarter commit from a week-6 snapshot). Walk the origin across historical snapshot dates; at each, reconstruct the pipeline (Q1), forecast, then score against realized bookings once the period closes.
- The gap discipline maps directly: if you forecast bookings that close up to h periods ahead, the train window must end at least h periods before the target window so no training label overlaps the forecast target.
- tsCV's `window` and sktime's `SlidingWindowSplitter` vs `TimeSeriesSplit` (expanding) give you the expanding-vs-sliding choice above; pick sliding after known regime changes (new pricing, re-org, new product).

### Gaps
- The Bergmeir–Hyndman–Koo (2015) theoretical justification for when CV is valid for time-series models was cited secondhand via Hyndman's blog; the primary paper was not fetched, so the exact conditions (stationarity, AR structure) are only paraphrased.

---

## 4. Accuracy metrics for bookings forecasts

### Takeaway
Report a scale-dependent error (MAE and/or RMSE) plus signed mean error (bias), and prefer
**WAPE** or **scaled/relative** measures over MAPE/sMAPE for lumpy, intermittent, low-volume
sales data. MAPE is undefined at zero actuals and explodes on small denominators; sMAPE is still
asymmetric. Always compare against naïve/seasonal-naïve benchmarks, and match the metric to the
statistic the model targets.

### Cited Findings (notation e_t = y_t − ŷ_t)
- **ME** = (1/n)Σe_t — use signed ME to detect bias; **MAE** = (1/n)Σ|e_t| (targets the median); **RMSE** = √((1/n)Σe_t²) (targets the mean; equals the error std for an unbiased model) — scale-dependent, compare only within a series — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716).
- **MAPE** = (100/n)Σ|e_t/y_t| is scale-free but undefined when y_t=0 and biased toward low actuals; a drop to 20 units can produce a ~6000% APE that dominates the mean; it is asymmetric (swapping actuals and forecasts changes the result) — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716); [Cleverence: MAPE pitfalls](https://www.cleverence.com/articles/oracle-documentation/mape-mean-absolute-percentage-error-4827/).
- **sMAPE** = (1/n)Σ 200|e_t|/(|y_t|+|ŷ_t|) is bounded but still asymmetric — it penalizes underestimates more and tends to favor slight overestimation — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716).
- **WAPE** = Σ|e_t| / Σ|y_t| (also WMAPE) divides summed absolute error by summed actuals; it is scale-free but not inflated by small values, and is recommended over MAPE when totals are low or sales are intermittent — [Baeldung: MAPE vs WAPE vs WMAPE](https://www.baeldung.com/cs/mape-vs-wape-vs-wmape); [NTT Data: Measuring forecast accuracy](https://us.nttdata.com/en/blog/2022/march/measuring-forecast-accuracy-keeping-score-on-keeping-score); [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716).
- **Scaled errors** divide by the *training mean* (not each actual), avoiding division by individual actuals: sMAE = (1/n)Σ |e_t| / ȳ_train, sMSE analogously; global variants ND = Σ|e_t|/Σ|y_t| and NRMSE = RMSE / ((1/n)Σ|y_t|). The training mean must be nonzero — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716).
- **MASE** scales MAE by the in-sample MAE of a naïve/seasonal-naïve forecast — scale-free, comparable across series, defined at zero; **RMSSE** is its squared analog. (Formulas not in the fetched excerpt of the paper, which marks both with usage restrictions in its Table 1.) MASE is described elsewhere as suitable for intermittent values but less intuitive — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716); [demandplanning.net on MASE](https://demandplanning.net/).
- **Relative errors** r_t = e_t / e^b_t scale by a benchmark's (naïve/seasonal-naïve) error for the same step; MRAE/MdRAE/GMRAE summarize |r_t|, are comparable across datasets, but break down when the benchmark is very accurate — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716).
- Choosing/summarizing: use medians or geometric means to limit outlier-series effects, arithmetic means to expose them; **match the training objective to the evaluation measure** (training L2 while evaluating MAE is unfair); measure error in value terms (e.g., gross profit / dollar bookings) where possible — [arXiv:2203.10716](https://ar5iv.labs.arxiv.org/html/2203.10716); [NTT Data](https://us.nttdata.com/en/blog/2022/march/measuring-forecast-accuracy-keeping-score-on-keeping-score).

### Inferences
- Bookings are a dollar aggregate, often lumpy (a few large deals dominate) and sometimes intermittent at the segment/rep level. WAPE is the natural headline KPI because it weights by dollars and is stable near zero; pair it with signed ME/bias (chronic over- vs under-commit is the RevOps question) and RMSE if a few large misses must be penalized hard.
- Because MAE targets the median and RMSE the mean, choose the model's loss to match: if you report WAPE/MAE, train to the median (or a quantile), not least-squares.
- Report metrics *per horizon* (week-1 vs week-6 of the quarter) because rolling-origin produces a distribution of errors by horizon, and pipeline accuracy should tighten as the period closes.

### Gaps
- The exact MASE and RMSSE formulas were not captured from a primary source in this pass (the fetched excerpt omits them); use Hyndman & Koehler (2006) for the canonical MASE definition before implementing.

---

## 5. Calibration / probabilistic-forecast metrics

### Takeaway
A point bookings number is not enough — validate the uncertainty band. Use **pinball (quantile)
loss** for quantile forecasts, **CRPS** for full predictive distributions, the **(Weighted)
Interval Score** for quantile/interval formats, **prediction-interval coverage (PICP)** vs
sharpness for honesty, and — for deal-level win-probability models — the **Brier score** and
**reliability diagram**. Proper scoring rules reward reliability and sharpness simultaneously,
which checking interval width or coverage alone cannot.

### Cited Findings
- **Pinball / quantile loss** QS_τ(F,y) = 2·{1(y ≤ q_τ) − τ}(q_τ − y) is a strictly proper scoring rule for quantile forecasts, asymmetric (penalizes under-prediction at rate τ, over-prediction at 1−τ), minimized in expectation at the true conditional τ-quantile; at τ=0.5 it reduces to a scaled MAE (MAE/2) — [Bracher, Ray, Gneiting, Reich 2021, arXiv:2005.12881 / PLoS Comp Biol](https://ar5iv.labs.arxiv.org/html/2005.12881); [r-statistics.co: Forecast Scoring Rules in R](https://r-statistics.co/Forecast-Scoring-Rules-in-R.html).
- **Interval score** for a central (1−α) PI with bounds l,u: IS_α(F,y) = (u−l) + (2/α)(l−y)·1(y<l) + (2/α)(y−u)·1(y>u) — decomposes into **sharpness** (u−l), an **overprediction** penalty (2/α)(l−y) when y<l, and an **underprediction** penalty (2/α)(y−u) when y>u; equivalently IS_α = [QS_{α/2} + QS_{1−α/2}]/α — [Bracher et al., arXiv:2005.12881](https://ar5iv.labs.arxiv.org/html/2005.12881).
- **Weighted Interval Score (WIS)** with median m, K intervals at levels α_1..α_K, weights w_0=1/2, w_k=α_k/2: WIS = (1/(K+1/2))·(w_0|y−m| + Σ_k w_k·IS_{α_k}); it is proper, equals absolute error when K=0, and **approximates CRPS** for large K with equally spaced levels — built for the COVID-19 Forecast Hub because quantile/interval submissions rule out scores (like the log score) that need full distributions — [Bracher et al. 2021, PLoS Comp Biol / PMC7880475](https://pmc.ncbi.nlm.nih.gov/articles/PMC7880475/).
- **CRPS** is a strictly proper score comparing the predictive CDF with the observation's step function (scores the whole distribution, not one number); it is the integral of the quantile score over all τ∈(0,1), so CRPS(F,y) = 2∫ PL(Q̂(p),y,p) dp and is approximated in practice on a dense grid (e.g., 99 levels 0.01–0.99); RMSE/MAE tie two forecasters who share a point forecast but differ in spread, whereas CRPS separates them — [r-statistics.co: CRPS and Pinball Loss](https://r-statistics.co/Forecast-Scoring-Rules-in-R.html); [CRPS Learning, arXiv:2102.00968](https://arxiv.org/pdf/2102.00968).
- **Prediction-interval coverage probability (PICP)** = fraction of observations whose true value falls inside the estimated interval; a well-calibrated 80% interval should contain ~80% of outcomes; report PICP **alongside interval width** so a band isn't judged well-calibrated merely for being very wide — [AWS Fortuna metrics docs](https://aws-fortuna.readthedocs.io/en/stable/references/metric.html).
- **Reliability diagram** (classification/probability side): bin predicted probabilities and plot each bin's mean prediction against the observed event frequency; points on the 45° diagonal = perfect calibration, above = under-confident, below = over-confident — [k-diagram: plot_reliability_diagram](https://k-diagram.readthedocs.io/en/latest/_autosummary/comparison/kdiagram.plot.comparison.plot_reliability_diagram.html); [MetricGate: Reliability Diagram](https://metricgate.com/calculator/reliability-diagram-calibration/).
- **Brier score** = mean squared difference between predicted probability and the 0/1 outcome (lower is better), a proper score for binary events; its **Murphy decomposition** splits it into reliability (calibration), resolution, and uncertainty, linking it to the reliability diagram; **Expected Calibration Error (ECE)** is the bin-weighted average gap between observed frequency and mean predicted probability (the 0.05 "meaningful miscalibration" cutoff is a tool rule of thumb, not a standard) — [AWS Fortuna metrics docs](https://aws-fortuna.readthedocs.io/en/stable/references/metric.html); [k-diagram docs](https://k-diagram.readthedocs.io/en/latest/_autosummary/comparison/kdiagram.plot.comparison.plot_reliability_diagram.html).
- Proper scores assess reliability and sharpness simultaneously, which makes them more informative than interval width or coverage alone; pinball loss became the most popular proper score in applied benchmarks after GEFCom2014 — [CRPS Learning, arXiv:2102.00968](https://arxiv.org/pdf/2102.00968).

### Inferences
- Two complementary calibration layers for a pipeline model: (a) **deal-level** win-probability calibration — the per-opportunity close probability is a binary-outcome forecast, so score it with Brier + reliability diagram + ECE; a well-calibrated "60% proposal" deal should actually close ~60% of the time (directly addresses the unvalidated-CRM-probability trap from Q2). (b) **Aggregate bookings** uncertainty — score the forecast distribution/quantiles for the period total with pinball loss, WIS, CRPS, and PICP-vs-width.
- WIS is the pragmatic choice when the model emits quantiles/intervals rather than a full distribution (the usual case for a Monte-Carlo pipeline roll-up), and it conveniently decomposes into the three RevOps-relevant parts: band too wide (sharpness), chronically too high (overprediction), chronically too low (underprediction).
- Report pinball loss at the business-relevant quantiles (e.g., 0.1/0.5/0.9 for a conservative/commit/best-case band) and aggregate across walk-forward origins; because QS at 0.5 ∝ MAE, the median-quantile score ties back to the point-accuracy section.
- Python implementations: `properscoring` (CRPS), `sklearn.metrics.mean_pinball_loss` and `brier_score_loss`, `sklearn.calibration.calibration_curve` (reliability), and `scoringrules` for CRPS/WIS; coverage is a one-line mean of `(lower <= y) & (y <= upper)`.

### Gaps
- Several calibration sources are library/vendor docs (Fortuna, k-diagram, MetricGate) rather than peer-reviewed texts; for formal definitions of proper scoring rules and the Murphy/Brier decomposition, the primary references are Gneiting & Raftery (2007, JASA) and Gneiting & Katzfuss (2014), which were not fetched in this pass.
- No source was found giving a worked end-to-end example of probabilistic *sales-pipeline* forecast scoring specifically; the mapping from the epidemic/energy-forecast literature (where WIS/CRPS/pinball are standard) to bookings is an inference, though the metrics are domain-agnostic.

# Probabilistic Methods for Forecasting New-Business Bookings from a Sales Pipeline

Scope: methods that produce a *distribution* of expected bookings by period (a prediction
interval), not a point estimate. Emphasis on Python-implementable, quantitative methodology
(numpy/pandas/lifelines/scikit-survival).

---

## Weighted-pipeline (expected value = amount x probability): mechanics, strengths, weaknesses

### Takeaway
Weighted pipeline multiplies each deal's amount by a stage-based win probability and sums the
result into a single expected-value point estimate. It is cheap and intuitive but produces no
distribution, relies on stage-average probabilities that mask deal- and rep-level variation, and
assumes clean CRM stage hygiene. It is best treated as the *mean* of the far richer distribution
a simulation produces, not as a forecast in itself.

### Cited Findings
- Mechanics: stage probability is "a percentage value assigned to each stage ... that represents the statistical likelihood of deals in that stage eventually closing as won," and the weighted forecast multiplies that probability by pipeline value — e.g. "the expected revenue from this stage will be 70% of $12285 = $8600" — [Saber glossary](https://saber.app/glossary/stage-probability); [Freshworks weighted pipelines](https://crmsupport.freshworks.com/support/solutions/articles/50000002959-how-to-set-up-and-use-weighted-pipelines-)
- Stage probabilities should be derived from history: RevOps teams "analyze historical deal data to calculate actual conversion rates from each pipeline stage to closed-won," and this "typically requires 12-24 months of historical data" — [Saber glossary](https://saber.app/glossary/stage-probability)
- Weakness — averaging hides rep-level variation: a manager showed a 41% weighted win rate at the negotiation stage while individual reps ranged 12%–75%; using a weighted pipeline "can skew your forecast by using an average" — [The Sales Blog](https://www.thesalesblog.com/blog/improve-sales-forecasts-with-individually-weighted-pipelines)
- Weakness — every deal in a stage gets equal weight regardless of momentum: a stalled deal "stuck for months" and a fast-moving one count equally — [The Sales Blog](https://www.thesalesblog.com/blog/improve-sales-forecasts-with-individually-weighted-pipelines)
- Weakness — depends on disciplined stage data; reps must be "disciplined and educated in determining the stage of a deal," and the method "doesn't account for how a representative is feeling about a deal" — [Clay glossary](https://www.clay.com/glossary/weighted-sales-pipeline)
- Weakness — historical probabilities may not match the current pipeline; forecasting "based only on historical data" is "attempting to predict the future without all the facts" — [Mediafly](https://www.mediafly.com/?p=63691)
- Weakness — may be the wrong model for some businesses; a Salesforce survey of 62 sales forces found 74% "should be basing their forecasts on something other than opportunities" (e.g. account-level forecasting for repeat-customer businesses) — [Salesforce blog](https://www.salesforce.com/ca/blog/?p=5424)
- Often recommended only for short cycles (under ~90 days) and small teams — [Forecastio](https://forecastio.ai/blog/weighted-pipeline-vs-ai-sales-forecasting)

### Inferences
- The fundamental limitation is structural, not fixable by better probabilities: a sum of amount×probability returns only the *expected value*. It cannot express "there is a 10% chance we miss by $2M," which is exactly what a bookings forecast needs for commit/risk decisions.
- A weighted-pipeline number equals the mean of the Monte Carlo distribution below when win probabilities are independent and deal amounts/timing are fixed. So weighted pipeline is a degenerate special case of the simulation approach, which makes the simulation a strict superset.

### Gaps
- The specific accuracy statistics in vendor blogs (Prospeo accuracy ranges, Forecastio's "15% improvement") are not independently verified; the conceptual weaknesses are better supported than any numeric accuracy claim.

---

## Monte Carlo over per-deal win/loss (Bernoulli) outcomes: setup, correlation/regime, why it beats a weighted point

### Takeaway
Instead of collapsing each deal to amount×probability, Monte Carlo draws an actual win/loss for
every open deal (a Bernoulli trial), sums the won amounts, and repeats N times to build an
empirical distribution of bookings from which P10/P50/P90 and probability-of-target are read.
The weighted-pipeline number is recovered as the mean; everything beyond the mean (spread, tail
risk, hit-probability) is new information. Treating deals as independent understates the tails,
so correlation/regime effects must be injected via a shared factor or copula.

### Cited Findings
- Core idea: run the model many times with random inputs and examine the spread; "after running 10,000 trials, you end up with 10,000 possible outcomes," then read percentiles — [Spreadsheet Planet](https://spreadsheetplanet.com/?p=30063)
- Supporting evidence (demand, not pipeline): a 2024 peer-reviewed study fit a theoretical distribution to historical sales and found "Monte Carlo simulation can outperform more straightforward methods such as averaging, particularly in the presence of uncertainty or randomness" — [European Research Studies Journal 2024](https://ideas.repec.org/a/ers/journl/vxxviiy2024ispecialap103-113.html)
- Pipeline framing: a SaaS forecasting brief models enterprise deals with "a probabilistic model" using "deal size, stage, probability," reads P10/P50/P90, and runs sensitivity to identify "key drivers of uncertainty" — [Ewance challenge](https://ewance.com/en/challenges/sales-forecasting-for-a-saas-scale-up-moving-upmarket-spreadsheet-modeling/)
- Correlation — the problem: simulating "dependent Bernoulli outcomes with set means and pairwise correlations is a common task in risk modeling" (e.g. correlated company defaults in a credit portfolio); deals sharing a common driver (one macro regime, one rep, one segment) have the same structure — [Wong & Ben Chaouch, arXiv 2026](https://arxiv.org/pdf/2607.16801)
- Correlation — the pitfall: the usual Gaussian-threshold / Gaussian-copula construction is such that "setting latent Gaussian correlations equal to target Bernoulli correlations is generally incorrect after thresholding," so the latent correlation must be calibrated, not passed through directly — [Wong & Ben Chaouch, arXiv 2026](https://arxiv.org/pdf/2607.16801)
- Correlation — feasibility: not every (marginal win-probability, correlation-matrix) combination is realizable; "problems may arise when the margins and the correlation matrix are not compatible," and an LP over the joint outcome probabilities matches target means and pairwise correlations "when feasible" — [Wong & Ben Chaouch, arXiv 2026](https://arxiv.org/pdf/2607.16801); [Characterization of multivariate Bernoulli, arXiv 1706.01357](https://arxiv.org/pdf/1706.01357)
- Dependence choice matters for tails: in correlated-input Monte Carlo, most implementations use the Iman–Conover method, but copula-based alternatives "may have a substantial effect on the output results" — noted in [Wong & Ben Chaouch, arXiv 2026](https://arxiv.org/pdf/2607.16801)
- Distribution choice is load-bearing and must be checked against data; a simple simulation that "ignores seasonality, trend, autocorrelation, and structural changes" can mislead — [Spreadsheet Planet](https://spreadsheetplanet.com/?p=30063)

### Inferences
- Why it beats a single weighted point: the Bernoulli simulation returns the entire bookings CDF. P(hit quota), P10 (conservative commit), and P90 (upside) all require the distribution; the weighted sum gives only its mean and literally cannot answer those questions.
- Practical regime/correlation implementation without solving an LP: draw one (or few) shared scenario factor(s) per trial — e.g. a market multiplier `m ~ Normal(1, σ)` or a latent "good/bad quarter" state — and shift every deal's win probability by it before the Bernoulli draw. This is the Gaussian-threshold / one-factor structure; independent draws are the σ=0 special case and produce artificially narrow tails. Because of the thresholding pitfall above, the factor's loading should be calibrated to reproduce an observed cohort-level win-rate variance, not set equal to a target pairwise correlation.
- Correlation widens the band without necessarily moving the mean: systematic (non-diversifiable) risk fattens both tails, which is exactly the tail risk a commit decision cares about. Independent draws tend to make the forecast look falsely precise.

### Gaps
- No single authoritative, end-to-end Python tutorial for deal-level bookings Monte Carlo surfaced; the search returned mostly vendor marketing. The mechanics are well supported in adjacent literatures (credit-portfolio default simulation, demand forecasting), which carry over directly.

---

## Survival / hazard / time-to-event models for CLOSE-DATE timing

### Takeaway
Survival analysis models *when* a deal closes, treating each opportunity as having a start (origin)
and an event (close), with still-open deals kept as right-censored observations rather than
discarded. Kaplan–Meier gives the non-parametric time-to-close curve, Cox proportional hazards
regresses the closing rate on deal covariates, and discrete-time hazard (logistic regression on a
deal-period panel) gives a per-period close probability that drops directly into a month/quarter
forecast. The timing *distribution* this produces is what lets a forecast allocate a deal's
bookings across future periods probabilistically.

### Cited Findings
- Why averages mislead: averaging days-to-close over only closed deals drops every open deal and "will usually under-estimate the expected lifetime of a deal"; the fix is to keep open deals as censored — [Gelman / statmodeling.stat.columbia.edu](https://statmodeling.stat.columbia.edu/2019/10/08/bizstat-modeling-performance-indicators-for-deals/)
- Censoring: survival analysis's "ability to handle censored data, where the event has not yet occurred for some subjects by the end of the observation period, without discarding those incomplete observations" — [InsertChat survival glossary](https://insertchat.com/glossary/survival-analysis-stats)
- Clock choice: analyze on "tenure, or time at risk for the event, and not calendar time" — i.e. measure from opportunity creation/first contact; lost deals often lack a clean close date and must be labeled at the point they "should have closed if it was going to close" — [Gelman / statmodeling](https://statmodeling.stat.columbia.edu/2019/10/08/bizstat-modeling-performance-indicators-for-deals/)
- Method menu: Kaplan–Meier (non-parametric survival curve), log-rank test (compare survival between segments like region/size/rep), Cox proportional hazards (regression of closing rate on covariates such as deal size, lead source, number of stakeholders); parametric (Weibull, log-normal) can be used to forecast timing but is a choice, not a default — [InsertChat survival glossary](https://insertchat.com/glossary/survival-analysis-stats); [Gelman / statmodeling](https://statmodeling.stat.columbia.edu/2019/10/08/bizstat-modeling-performance-indicators-for-deals/)
- Caveat specific to sales: deals are far more heterogeneous than clinical-trial patients; "if some deals are much more complicated than others ... we should expect some deals to take longer to close," so adjust for complexity/segment before reading curves — [Gelman / statmodeling](https://statmodeling.stat.columbia.edu/2019/10/08/bizstat-modeling-performance-indicators-for-deals/)
- Discrete-time hazard — definition and data layout: it targets "the conditional probability of the event at time point t given survival until t"; data are expanded to one row per at-risk interval, with the target 0 for pre-event periods and a final row set to 1 in the event period (a deal closing in interval 5 gets 5 rows: 0,0,0,0,1) — [bookdown discrete-time survival, Ch.5](https://bookdown.org/mpfoley1973/survival/discrete.html)
- Discrete-time hazard — estimation: it is fit as ordinary logistic regression with "one parameter for each possible event time" acting as the baseline hazard (time-specific intercepts), and is "a discretized version of the Cox proportional hazard model" (logit link ≈ proportional continuation-ratio; complementary log-log ≈ grouped proportional hazards) — [bookdown discrete-time survival, Ch.5](https://bookdown.org/mpfoley1973/survival/discrete.html)
- Discrete-time hazard — predictive strength: "any binary classification method can be applied to predict these conditional survival probabilities" (so gradient boosting etc. can replace logistic regression), and in benchmarks "some discrete-time models outperformed the continuous-time Cox model," with "limited loss in predictive accuracy" vs. continuous-time — [BMC Med Res Methodol 2022, doi 10.1186/s12874-022-01679-6](https://link.springer.com/doi/10.1186/s12874-022-01679-6)
- Discrete-time hazard — gotchas: use the most recent covariate values ("relevance of the data diminishes over time"), and pooling periods when covariate effects vary over time biases the logistic estimates away from period-specific effects — [bookdown](https://bookdown.org/mpfoley1973/survival/discrete.html); [arXiv 1704.04087](https://arxiv.org/pdf/1704.04087)
- Tools: Python `lifelines` and R `survival`/`cuRe`/`Epi`; `lifelines` offers `KaplanMeierFitter`, `CoxPHFitter`, parametric AFT fitters, and prediction methods `predict_survival_function`, `predict_median`, `predict_percentile`, `predict_expectation` — [lifelines Survival Regression docs](https://lifelines.readthedocs.io/en/latest/Survival%20Regression.html); scikit-survival also implements these models
- Expected residual lifetime concept (the quantity you want for an open deal): "the mean and median of the remaining lifetime after a given time t, conditional on survival up to that time," computed as S(t) integrated from t divided by S(t) — [cuRe calc.LL](https://rdrr.io/cran/cuRe/man/calc.LL.html); [UHasselt conditional residual life](https://documentserver.uhasselt.be/bitstream/1942/9010/1/CONDITIONAL%20RESIDUAL%20LIFE.pdf)

### Inferences
- Discrete-time hazard is the most natural fit for a *period-by-period* bookings forecast: it directly outputs h(t) = P(close in period t | still open at t), which is exactly the quantity you multiply through to allocate a deal's expected bookings across future months. Continuous Cox/KM need an extra discretization step to do the same.
- For open deals you condition on elapsed age (left-truncation / `conditional_after`, below). An open deal 60 days old is not drawn from the unconditional time-to-close distribution — it is drawn from the distribution conditional on having survived 60 days, which generally pushes the expected close later.

### Gaps
- The Gelman/statmodeling source returned HTTP 403 on direct fetch; its content here is from the search-engine extract and is directionally reliable but not fully verified line-by-line.

---

## Combining win-probability and close-timing into a forward bookings distribution; deal-amount uncertainty

### Takeaway
A full probabilistic bookings forecast draws three things per deal per simulation trial: (1) will
it close-won (Bernoulli), (2) *when* (sampled from the survival/hazard timing distribution), and
(3) how large (amount sampled from a distribution, not the CRM point value). Each trial places
won revenue into the period its sampled close date falls in; summing per period over N trials
yields a per-month/quarter bookings distribution. This marries the Monte Carlo (win/loss) and
survival (timing) components; amount uncertainty is a third independent (or correlated) draw.

### Cited Findings
- Combining win-prob and timing is established practice: one production system is "an end-to-end ML pipeline using Pipedrive data to estimate deal closing probabilities and expected contract start dates" — i.e. both whether and when — [RevOps practitioner profile](https://br.linkedin.com/in/alexandrabaez)
- Timing (slippage) is often the dominant source of quarter-level error, so close dates should be *sampled*, not fixed — [Ewance challenge](https://ewance.com/en/challenges/sales-forecasting-for-a-saas-scale-up-moving-upmarket-spreadsheet-modeling/)
- Deal-amount uncertainty: where CRM amounts are uncertain, sample from a distribution (e.g. lognormal) rather than using the point figure; lognormal keeps revenue positive and is a common deal-size assumption — [Spreadsheet Planet](https://spreadsheetplanet.com/?p=30063)
- Conditioning timing on a deal's current age in `lifelines`: "the `conditional_after` kwarg in all prediction methods" sets s = time already survived, giving the conditional survival S(t)/S(s); `predict_median(open_deals, conditional_after=age)` returns *remaining* time, and total duration = prediction + `conditional_after`; set `conditional_after=0` for already-closed deals — [lifelines Survival Regression docs](https://lifelines.readthedocs.io/en/latest/Survival%20Regression.html)
- Aggregation and reporting: sum won revenue within each target window per trial, then report P10/P50/P90 and probability-of-target rather than the mean alone — [Ewance challenge](https://ewance.com/en/challenges/sales-forecasting-for-a-saas-scale-up-moving-upmarket-spreadsheet-modeling/); [Spreadsheet Planet](https://spreadsheetplanet.com/?p=30063)

### Inferences
- Concrete per-trial algorithm (synthesizing the sources):
  1. For each open deal i, draw win_i ~ Bernoulli(p_i), where p_i is a calibrated win probability (optionally shifted by a shared regime factor for correlation).
  2. If win_i = 1, draw a close date: sample from the fitted survival/hazard model conditional on the deal's current age (`conditional_after`), e.g. invert a sampled survival quantile or draw period-by-period from the discrete hazard.
  3. Draw amount_i from its distribution (lognormal fit, or a triangular low/expected/high).
  4. Add amount_i to the bucket for the period containing the sampled close date.
  - Repeat N times; each period's vector of N sums is its bookings distribution.
- Win and timing can share drivers (a strong deal both closes and closes sooner), so modeling them with the same covariates — or letting a hazard model's "won" sub-event handle both at once (competing risks: won vs. lost) — is cleaner than assuming independence. Competing-risks / cause-specific hazards are the principled extension when you want "closes-won in period t" as the event rather than "closes (either way)."
- Deal-amount correlation with win probability matters for tails: large deals often have lower win rates, so drawing amount independently of win can understate downside; a joint draw (or covariate-shared model) is more faithful.

### Gaps
- No single cited source gives the complete three-draw (win × timing × amount) algorithm as one worked example; it is assembled here from the component sources. Competing-risks framing for won-vs-lost is an inference from standard survival theory, not drawn from a sales-specific cited source.

---

## Number of simulations, and how parameter uncertainty (not just outcome noise) enters the band

### Takeaway
Two distinct uncertainties must enter the band: (a) *outcome/aleatoric* noise (the Bernoulli
win/loss and timing draws) and (b) *parameter/epistemic* uncertainty (the win probabilities,
hazard coefficients, and amount parameters are themselves estimated from finite data). Monte Carlo
run count governs only how precisely you resolve (a)'s percentiles; tail percentiles need far more
runs than the mean. Parameter uncertainty must be added as an outer layer — resample model
parameters (bootstrap or from their estimated sampling distribution) on each trial — or the band
will be too narrow, especially with small samples or non-Gaussian errors.

### Cited Findings
- Mean converges as 1/√N: Monte Carlo standard error ≈ std(statistic)/√N, so "halving the error takes about four times as many simulations" — [SAS blog, monitoring MC convergence](https://blogs.sas.com/content/iml/?p=58261)
- Tail percentiles are the bottleneck: estimated 1% and 5% percentiles "still fluctuate noticeably at tens of thousands of runs"; the SE of a sample quantile at p is ≈ √(p(1−p)/n) divided by the outcome density at that quantile, so extreme tails need many more runs than the median/mean — [UiO STK2510 lecture notes](https://www.uio.no/studier/emner/matnat/math/nedlagte-emner/STK2510/v09/undervisningsmateriale/ch2b.pdf)
- Vendor run-count rules of thumb (built for std-dev, not percentiles): for 3% error at 95% confidence, ~2,137 runs; for 1% error at 99% confidence, ~33,178 runs — [3DCS convergence](https://community.3dcs.com/help_manual/3dcs-convergence.htm)
- Iterative stopping rule: run until the mean and std-dev change by less than ~0.15% across ~20 consecutive iterations — [RiskyProject / Intaver](https://www.intaver.com/IntaverFrm/viewtopic.php?p=2343)
- General convergence test: keep adding runs until "your designated goals (such as the descriptive statistic of measurements) are not affected by changing the number of samples" — [SAS blog](https://blogs.sas.com/content/iml/?p=58261)
- Parameter uncertainty improves interval coverage: Pascual, Romo & Ruiz (2001) show by Monte Carlo that "the average coverage of the intervals is closer to the nominal value when intervals are constructed incorporating parameter uncertainty," with the gap largest for small samples and non-Gaussian errors — [Pascual, Romo & Ruiz 2001 (UC3M working paper)](https://e-archivo.uc3m.es/bitstream/handle/10016/6527/ws100301.pdf?sequence=1)
- Two-layer simulation mechanics: "re-generate model parameters from the estimated joint asymptotic distributions to reflect estimation error, and then simulate ... given the ... re-estimated parameter"; a related approach samples "estimated principal component scores and model residuals ... with replacement" — [Disentangling uncertainties in default risk, arXiv 1804.09302](https://arxiv.org/pdf/1804.09302)
- Bootstrap intervals' appeal: they "do not rely on severe distributional assumptions" and "are able to incorporate the parameter uncertainty"; standard Kalman-filter intervals by contrast "do not incorporate the uncertainty due to parameter estimation" and assume Gaussian future innovations — [Ruiz forecasting work, UBC](https://www.stat.ubc.ca/node/4396)

### Inferences
- Practical run-count guidance for a bookings forecast: because the decision-relevant numbers are usually P10/P50/P90 (not 1%/99% extremes), low tens of thousands of trials (e.g. 10k–50k) generally stabilize those deciles; validate empirically by running several seeds and checking the P10/P90 spread across seeds is within tolerance, and/or bootstrap the simulation output to get a CI on each percentile. Use more runs only if you report deeper tails.
- The right overall structure is a nested (two-level) Monte Carlo: outer loop draws a parameter set — win probabilities from Beta posteriors or logistic-coefficient sampling distributions, hazard coefficients from their covariance, amount parameters from a bootstrap — and the inner loop does the per-deal win/timing/amount draws. Collapsing to a single level (fixed point-estimate parameters) reproduces outcome noise only and yields a band that is too tight, matching Pascual et al.'s finding that coverage falls short without the parameter layer.
- Simple, data-light way to get parameter uncertainty without asymptotic covariance math: nonparametric bootstrap — resample historical deals with replacement, re-fit the win-rate/hazard/amount models on each resample, and run one (or a few) inner simulations per resample. This directly propagates estimation error and needs no Gaussianity assumption.
- Calibration check: the sources repeatedly note CRM/stage probabilities are optimistic; backtest past forecast percentiles against realized bookings (coverage calibration — did ~80% of outcomes fall inside the P10–P90 band?) to confirm the band is neither too wide nor too narrow.

### Gaps
- The vendor run-count figures (2,137 / 33,178) assume a normal population and a chi-squared test on variance, so they are strictly for standard deviations, not for the revenue percentiles a bookings forecast cares about; no source gave a validated run-count target specifically for a bookings-distribution percentile. Treat them as order-of-magnitude only.
- The peer-reviewed ERSJ 2024 Monte Carlo demand paper could not be fetched (binary PDF); its conclusion ("MC can outperform averaging under uncertainty/randomness") is from the search extract and the abstract, not the full methodology.

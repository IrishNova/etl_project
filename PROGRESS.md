# ETL Lab — Progress Journal

> Recovery log so we're never sunk if the terminal closes. Updated continuously.

## Project in one line
A learning-lab ETL pipeline: take three messy sales sources → clean/align → one unified model → a dashboard. End goal: a polished GitHub repo to share with hiring managers.

## Ground rules
1. This is a **lab** — learning first, showing off second.
2. **One task at a time.** User is involved in every decision.
3. Re-explaining is fine — ask the same question as often as needed.
4. Keep this file updated (recovery safety).
5. **Do NOT commit to GitHub until explicitly told.** (Avoid work-hours commit timestamps.)
6. Python/pandas solid; **data-analytics skills are the growth area.**
7. Dashboard: Flask-hosted site OR Tableau — pick impressive + achievable.
8. **Default all judgement calls to the user.**
9. Short messages, small chunks.
10. Ask questions when they arise.

## Data (assessed — solid ✅)
- `_data/product_a_legacy_licenses.csv` — 2,676 rows. "NA" region ambiguity, 16 dup license_ids, renewals bill at 20% of value (business rule), ISO dates.
- `_data/product_b_cad_subscriptions.csv` — 1,119 rows. Mixed date formats, 3 currencies (USD/GBP/EUR), quoted embedded commas, dup contract_no, status/renewal flags.
- `_data/product_c_simulation_orders.xlsx` — 376 rows. 2 junk preamble rows, Excel serial dates, "4 seats" string contamination, blank reps.
- Note: customer keys differ per source; joining likely needs entity resolution on customer_name.

## Environment
- Python 3.12, venv at `.venv/` (nothing installed yet).
- Git initialized locally (no commits yet — see rule 5).
- Skeleton: `src/etl/{extract,transform,load}`, `config/`, `data/{raw,processed}`, `tests/`, `logs/`.

## Business understanding (planning)
- **End goal:** FP&A — demand projections + resource planning for an imaginary software vendor.
- **Why ETL first:** can't forecast or value the present until licenses are measured cleanly.
- Each source = a different PRODUCT, sold on a different model:
  - A = Product A, legacy perpetual/maintenance (SKUs IA-CORE/PRO/ENT)
  - B = Product B, CAD subscriptions (Standard/Premium)
  - C = Product C, simulation add-on orders (SIM-THERM/FLUID/STRUCT)
- A customer can hold multiple products → cross-sell is a key question.
- **License vs seat:** one license/contract = an agreement covering N seats; seat = per-user fee. Carry BOTH metrics (contract count + seat count) through the pipeline.
- Two headline charts: (1) stacked bar = outstanding licenses per company colored by product; (2) single- vs multi-product customers.

## Phasing
- **Phase 1 — Foundation (NOW):** messy sources → one clean, unified, currency-normalized dataset (the ETL).
- **Phase 2 — Snapshot dashboard:** point-in-time licensing + income position for FP&A.
- **Phase 3 — Projections:** demand/renewal forecasting, resource planning.

## Definitions still to lock (Phase 1 blockers)
- [ ] **Grain** of the bar: contracts vs seats (carrying both; decide default display).
- [ ] **"Outstanding/active"** rule — differs per source (B status+end_date; A perpetual; C orders).
- [ ] **Company identity** — match same customer across A/B/C (likely by name).

## Architecture (LOCKED) — the 4 levels
```
L1 EXTRACT   load 3 files as-is (csv/csv/xlsx). messy, separate, NO fixing.
L2 TRANSFORM clean each source on its own: dates→one format, numbers→float,
             currency→common, strip "4 seats", drop C's junk rows, tag revenue_type.
L3 UNIFY     stack all 3 into ONE long/tidy "fact" table. ★ single source of truth.
             one row = one contract; carries ALL measures (value, seats, count) + attrs.
L4 VIEWS     cheap GROUP BY / pivots on L3: daily panel, ARR snapshot, TTM, cross-sell, churn.
```
- Keep L1 and L2 separate so raw is always available for honest debugging.
- Foundation is LONG/tidy, not wide — a wide panel holds only one measure per cell.
- The daily MultiIndex panel (date index, Company→license cols) is a **L4 view**, not L3.
- Success test: any FP&A question = a GROUP BY on L3; never re-open `_data/`.

## Key concepts covered (plain-English recap)
- **license vs seat:** 1 license/contract = N seats; seat = per-user fee.
- **Three measures carried:** contract count, seat count, value.
- **snapshot vs flow:** snapshot = what's live now (ignores sale date); flow (TTM) = what we sold in last 12mo (ignores if still live).
- **ARR vs TTM booked:** ARR = annualized value of *active recurring* contracts (excludes perpetual + one-off). TTM booked = everything sold in trailing 12mo (incl one-time).
- **revenue_type:** recurring (B subs, A maintenance) vs one-time (A perpetual, C orders).
- **pipe vs view:** pipe = extract+clean (expensive). view = filter/aggregate on L3 (cheap). New question → new view, not new pipe.

## Decisions log
- Metrics of interest: ARR snapshot AND TTM booked value (both). Value is default bar height, stacked by product; seats carried for later stats.
- Architecture = 4-level L1→L4 above.

## Build log
- **L1 Extract — DONE ✅** (`src/etl/extract/sources.py`)
  - Approach A: read files directly (no SQL). pandas 3.0.6 + openpyxl 3.1.5 installed.
  - Design: load everything as TEXT (`dtype=str`), keep raw faithful, type in L2.
  - `load_product_a/b/c()` + `load_all()`; run: `PYTHONPATH=src python3 -m etl.extract.sources`
  - Row counts: A=2676, B=1119, C=381 (C incl. preamble+header as data).
  - Catch: C preamble is 3 junk rows (title, SalesOps, blank), NOT 2 → L2 must DETECT the header row, never hardcode a skip.
- **Product C findings (from NaN review):**
  - Real header is at row index 3 ("Order Ref" etc.); real order data = rows 4–378 (375 rows).
  - Junk to drop in L2: rows 0–1 (preamble), row 2 (blank), row 379 (blank), row 380 (`TOTAL` footer).
  - `Rep` column (col 7) has 83 legit blanks — optional field, keep as missing.
  - The NaNs the user saw are ALL from those junk rows + the optional Rep col — verified harmless.
  - ★ RECONCILIATION ANCHOR: C's footer TOTAL = 9,158,875. SUM(Order Total) over the 375 clean rows = 9,158,875 exactly. Use as a built-in L2 check for C.
  - Dates already resolved by openpyxl to real datetimes (e.g. 2023-03-09), not Excel serials — no serial conversion needed.

## Planned: reconciliation / validation (user-requested)
- Build a **reconciliation step**: compare each source raw (L1) vs cleaned (L2) to verify nothing broke.
  - Checks: row counts, SUM(seats), SUM(value), null rates, distinct customers, dup keys — before vs after.
  - Goal: any unintended change in a total = a caught bug. (This is the "comparative statistics, old vs new" the user wants.)
- Also: write each L2 output to a CSV so the user can eyeball it ("view a CSV").

- **L1 fix (NA coercion bug) — DONE ✅**
  - pandas was turning region `"NA"` (North America) into NaN, merging it with 48 truly-blank rows.
  - Fixed A & B loaders with `keep_default_na=False, na_values=[]` → load faithful text, decide missingness in L2.
  - Verified: A region NA=1327/EU=719/UK=582/blank=48; B NA=678/UK=240/EU=201.
  - Lesson: pandas treats literal "NA" as missing by default — always suspect this.

## L2 Transform — Product A (in progress)
Plan: Step 0 fix NA (done) → map to schema → clean/type → derive → reconcile → CSV dump.
Decisions: [1] NA fix = YES (done). [2] blank region = BACKFILL per-customer. [3] dupes = DROP exact (keep first). [4] arr rule — TBD.
- [2] Blank region (48 rows): BACKFILL from the same customer's known region. Verified all 48 recoverable, 0 conflicts, 0 unrecoverable. Keep an "Unknown" fallback in code for safety. No values invented.
- [3] Duplicate license_ids: all 16 are EXACT duplicate rows (identical every col, 0 conflicts). DROP with keep="first". A: 2676 → 2660 rows.
  - Reconciliation note: dropping dupes intentionally lowers SUM(seats)/SUM(value). Correct check = raw_total − (16 dupe rows' value) == clean_total. Prove only the intended rows changed.

- [4] revenue_type/arr rule LOCKED: Perpetual=one-time(arr 0); Maintenance Renewal=recurring(arr=net_amount). booking_value_usd=net_amount for both.
- **L2 Product A — DONE ✅** (`src/etl/transform/product_a.py`)
  - Also added `src/etl/schema.py` (UNIFIED_COLUMNS + `conform()`) and `src/etl/transform/validation.py` (`profile`/`compare`).
  - Run: `PYTHONPATH=src python3 -m etl.transform.product_a`
  - Output: `data/processed/clean_product_a.csv` (2,660 rows).
  - Reconciliation all PASS: rows 2660 (2676−16 dupes), seats=31,217, value=$40,385,112, customers=327, no blank regions, arr logic correct.
  - loaded as text in L1; typed here (seats int, money float, sold_date datetime).

- **L2 Product B — DONE ✅** (`src/etl/transform/product_b.py`) — 1,115 rows, all 15 reconciliation checks pass.
  - Decisions: [1] currency→USD at BOOKING-date rate; [2] mixed dates parsed by `/` vs `-`; [3] 4 exact dup contract_nos dropped (0 conflicts); [4] status normalized.
  - **FX** (`src/etl/fx.py`): yfinance pulled GBPUSD/EURUSD once → cached `data/reference/fx_rates.csv` (1828 daily rows, weekends ffill/bfill). `to_usd()` converts per-row at booking date. Reproducible, no live API on each run.
  - Lesson: EUR dipped below USD parity in 2022 → conversions can go DOWN; reconcile against the rate table, not a directional assumption.
  - **Renewal inference** ([[etl-lab-ground-rules]] "default to me / be certain"): 36 blank `is_renewal` filled by rule "customer has a prior contract ending within 1 day of this start". Validated vs 1,079 known labels: precision 98.76%, recall 100%, 6 FPs. Known labels kept verbatim; only blanks filled; flagged via new `is_renewal_inferred` col. 21→new, 15→renewal.
  - Schema additions: `cancel_date`, `is_renewal`, `is_renewal_inferred` (A/C carry nulls via superset principle). Re-ran A → both CSVs now identical 22-col schema.
- Caught a boolean-dtype bug mid-analysis (`~` on object column) that gave fake precision 0.50; recomputed correctly → 98.76%. Lesson: cast to bool before set ops.

- **L2 Product C — DONE ✅** (`src/etl/transform/product_c.py`) — 375 rows, all 10 reconciliation checks pass.
  - Detect header row dynamically (not hardcoded); keep only `SO-` rows → drops preamble/blanks/TOTAL footer.
  - Seats: strip "4 seats"→4 (103 rows). Discounts exist (0/5/10/15%) so order_total != seats*unit; check is total<=seats*unit. Footer TOTAL 9,158,875 reconciles exactly.
  - Decision: C has NO customer_name/region cols → left null, ENRICH in L3 from A by Customer ID (195/206 match; 11 C-only customers TBD in L3).
  - **Date imputation (B-style rigor):** 16 blank Order Dates filled by interpolating against order-ref sequence (corr 0.98; LOO median err ~9d, p90 20d). Flagged `booking_date_inferred=True`. User explored ffill/bfill but 148 inversions + 2 inverted brackets → interpolation chosen. Not day-exact; fine at quarter grain.
  - Schema additions: `booking_date_inferred`. Made both `_inferred` flags explicit (False by default) across A/B/C.
- **L2 COMPLETE.** All 3 clean CSVs in data/processed, identical 23-col schema. Rows: A=2660, B=1115, C=375 (total 4150).

## L3 prep — customer identity (explored, not yet built)
Problem: report "by company" but IDs don't align. A↔C share `C-100xx` (easy). B uses numeric `account_number` → must match B↔A by NAME (dirty: casing, legal suffixes, typos like "Cascade Aerosace").
User's plan (validated as textbook fuzzy entity resolution): normalize → high-threshold (95-99%) match → manual-review the gray band.
Findings from exploration:
- Normalization (lowercase, strip punct, strip legal suffixes corp/inc/llc/gmbh/ltd/...) → **145/184 B customers EXACT-match A**; ~39 left for fuzzy/review.
- ⚠️ FALSE-MERGE trap: 93 norm-name collision GROUPS in A (distinct ids → same norm), e.g. Cascade Tooling Corp/GmbH/Ltd = different regional entities. Suffixes track REGION.
- Fix: match on **normalized_name + region** (we have region both sides) → collisions 93 → **10**.
- 🐛 FOUND: A's `customer_name` has the SAME blank-backfill gap as region — 83 blank cells / 71 customers, ALL recoverable from the same customer's other rows (0 conflicts, 0 truly nameless). We backfilled region in A but FORGOT customer_name. Mirror the region backfill.
- Reminder: reading the clean CSVs re-triggers the "NA"→NaN bug → always read with keep_default_na=False, na_values=[].
- rapidfuzz NOT installed yet (needed for the ~39 fuzzy matches).

## Current status / next step (identity, in order)
1. ✅ DONE — A `customer_name` backfilled (71 recovered, 0 blank, 0 invented, 327 ids↔327 names). Generalized `_backfill_from_customer(df,col,fallback)` now serves both region & name. +2 reconciliation checks.
2. ✅ DONE — matcher built (`src/etl/unify/names.py`, `customer_match.py`). Match B→A on (norm_name, region). Result: **83 exact / 35 ambiguous / 66 unmatched** (crosswalk → data/processed/customer_crosswalk.csv).
   - KEY FINDING: A has distinct customers sharing base-name+region, differing only by legal suffix (e.g. Quantum Aerospace Corp/Inc/LLC all NA). Suffix-stripping erases the only distinguisher → those 35 are GENUINELY ambiguous (B's suffix isn't among A's variants), correctly flagged for review not guessed. Full-name+region is unique in A (0 collisions) but doesn't resolve the 35 either.
   - Canonical key = A's customer_id; matched B adopts it. Crosswalk has match_method for audit.
3. ✅ DONE — rapidfuzz fuzzy pass (token_sort_ratio, within-region). Clean score gap (real typos ≥96, different-cos ≤83, nothing between) → threshold = 90.
4. ✅ DONE — **MODEL DECISION: adopted Model 2 (company grain).** Tested both end-to-end: Model 1 (legal entity) = 97.3% resolved, 5 stuck ambiguous; **Model 2 (company = normalized base name + region) = 100% resolved, 0 ambiguous.** Model 2 matches the "by company" reporting goal; legal entity kept as detail.
   - Rebuilt `customer_match.py` for Model 2. `build_customer_crosswalk()` → `data/processed/customer_crosswalk.csv` (717 customer rows → **334 companies**).
     - A: 327 exact. B: 118 exact / 5 fuzzy / 61 B-only. C: 195 id-join (inherit A company by customer_id) / 11 c_only_unmatched.
     - `company_id = norm_base|region`; cols: company_name, match_method, match_score, needs_review, company_legal_entities.
   - **needs_review flag = 16** (5 fuzzy + 11 C-only with no name anywhere). This is the HOOK for the future build to trigger a manual-review notification on ambiguous names (user-requested).

## Customer identity — DONE ✅ (Model 2).

## active-rule — DONE ✅
KEY INSIGHT (user-driven): `is_active` is NOT a stored fact — it depends on the
date you ask about. Same license is active in June, expired in Dec. So we store
only the immutable coverage window in L3 and COMPUTE is_active at view time (L4).
- Decisions locked: maintenance (A) `end_date = start + 1yr`; perpetual (A) + one-time
  (C) have no window → is_active = <NA> ("n/a"). Only recurring rows can be active.
- Product A updated (`product_a.py`): built `end_date` for Maintenance Renewal rows
  (+1yr), NaT for perpetual. +2 reconciliation checks. is_active/status stay <NA>
  (derived at view time, not baked). Re-ran, all 11 checks pass.
- **NEW L4 helper** `src/etl/views/active.py` → `active_as_of(df, as_of)` returns
  `status_asof` {future/active/expired/cancelled/n/a} + nullable-bool `is_active`.
  Rule: future < start; cancelled if cancel_date<=as_of; active if start<=as_of<=end;
  else expired. Non-recurring → n/a.
- Only B has cancellation (source: 489 active / 604 expired / 26 cancelled, cancel_date
  on the 26). A/C have none. B's `status` = vendor ground truth.
- VALIDATED: B's snapshot date reverse-engineered to **2026-09-30** (expired ends
  <=09-29, active ends >=10-01, clean gap). `validate_against_b()` runs the rule at
  that date → reproduces B's labels **1115/1115, zero mismatch**. Rule is trusted.
  (Note: today 2026-10-15 is OUTSIDE B's window — proves as-of must be a parameter.)

## L3 UNIFY — DONE ✅  (`src/etl/unify/build_fact.py`)
THE SINGLE SOURCE OF TRUTH: `data/processed/unified_fact.csv` — **4,146 rows x 26 cols**,
one row per contract. All 8 reconciliation checks pass; $83,035,467 reconciles exactly.
- Stack = concat of the 3 conformed clean CSVs (schema-checked), then 2 enrichments:
  1. company_id via crosswalk join on (product, customer_id). Every A/B row + 360 C rows
     get one; only the 11 C-only stay null (flagged needs_review).
  2. C's customer_name/region inherited from A by shared C-100xx customer_id.
- status/is_active left AS STATED by source (B=vendor label; A/C=<NA>). NOT the canonical
  activity answer — use views.active.active_as_of(df, date) for any date. Stored window
  (start/end/cancel) is what powers that.
- 47 rows flagged needs_review (B fuzzy-matched + C-only) — the manual-review hook.

### Bugs caught & fixed building L3
- 🐛 Product C never de-duplicated (A & B both do)! Found 4 exact-dup order rows (same SO-
  ref = primary key). DROPPED → C 375→371 rows, total $9,158,875→$9,029,085. Footer still
  reconciles: raw SO rows == footer; clean == footer - dup_total ($129,790). User OK'd drop.
  Rebuilt C + crosswalk. Added `contract_id now unique` check.
- 🐛 Join dtype: B customer_id reads as int64, crosswalk source_customer_id is str → no
  match (all B company_id null). Fix: cast fact customer_id to str before merge.
- 🐛 crosswalk NA company_id -> "" in CSV; we read na_values=[] (to protect region "NA"),
  so "" came back as string not NaN -> 11 C-only looked "matched". Fix: replace ""->NA
  after merge for company_id/company_name.

## ARCHITECTURE DECISION (post-L3): go "live", full build
Goal: a portfolio gem — real end-to-end system, not just a notebook. Pieces:
  pipeline (incremental ingest) -> **Postgres** (source of truth) -> metrics/quant
  layer -> Flask API -> front end (Tableau Public OR custom JS — decided later).
- **Store = PostgreSQL** (user chose: strongest "ingest from ERP/CRM" signal).
- **Deployment = fully dockerized, built incrementally.** 3 roles: db (long-run),
  api (long-run, Flask), pipeline (batch job). One Dockerfile shared by api+pipeline,
  one docker-compose orchestrating all 3. 12-FACTOR from day one: all config via env
  vars so identical code runs on host (dev) and in-container (deploy).
- Tableau reality check: Tableau connects to DB/extracts, NOT a live REST API. So
  front end is either Tableau Public (on a published extract) or a JS dash hitting
  Flask. Decide once metrics exist.
- QUANT side flagged by user as SUPER important.

## LOAD (L) phase — the real "L" we'd skipped (src/etl/load/ was empty)
Plan: (1) stand up Postgres ✅  (2) connection layer  (3) schema/DDL  (4) load+upsert
(idempotent INSERT..ON CONFLICT = the "add new data" mechanism)  (5) prove incremental
ingest with a 2nd mock batch.

### Steps 2-4 — connection, star schema, load+upsert ✅
- **Step 2 — connection layer** (`src/etl/load/db.py`): `get_engine()` builds a pooled
  SQLAlchemy engine from `DATABASE_URL` (loaded via python-dotenv; no-op in Docker).
  `pool_pre_ping=True`. `ping()` + __main__ smoke test (password masked). Works.
- **Step 3 — star schema** (`src/etl/load/tables.py`, SQLAlchemy Core so schema lives
  in Python, not a drifting .sql): `dim_company` (PK company_id), `fact_contracts`
  (PK (product,contract_id), FK company_id->dim), `map_customer` (PK (source,src_id),
  FK company_id, the match-audit/review table). dates=date, money=numeric(18,6),
  flags=boolean, loaded_at=timestamptz. Indexes on company_id/booking_date/revenue_type.
  `create_schema(engine, drop=)`. Verified in psql.
- **Step 4 — load + upsert** (`src/etl/load/load_fact.py`): reads clean CSVs, builds
  dim_company (groupby crosswalk; needs_review=any-member-flagged, n_legal_entities),
  loads dim FIRST (FK parent) then fact + map. Upsert = `pg_insert(...).on_conflict_
  do_update` on the PK → idempotent. Row coercion is TYPE-DRIVEN off the Table columns
  (dates/int/numeric/bool, ""->NULL, numpy->native). Loaded **334 companies / 4,146
  contracts / 717 mappings**; reconciles vs source ($83,035,467), 0 orphan FKs.
  **Idempotency proven: ran twice, counts unchanged.**
  - 🐛 pandas reads "True"/"False" text as real bool dtype even with keep_default_na=
    False, so mapping string keys gave all-NaN. Fix: leave needs_review as bool.

### Step 5 — incremental ingest (Pattern B, landing zone = mock API) ✅
Operational design (user): fast loop pulls from "APIs" every n min (config) and upserts;
nightly loop materializes is_active/status (only flips at day boundaries). Flask API
later projects CSV/JSON on front-end request.
- **is_active design LOCKED**: `active_as_of()` stays the single rule; the NIGHTLY job
  calls it with as_of=today and WRITES is_active/status into fact_contracts. (Refines
  the earlier "never store" — we store a nightly-materialized snapshot of the function.)
- `config/pipeline.yml` + `src/etl/config.py` (load_config, resolve_path). Settings:
  ingest.interval_minutes=15, landing_zone, archive_zone, active_refresh.as_of=today.
  Chose YAML (PyYAML 6.0.2 added).
- `src/etl/extract/mock_api.py`: `iter_incoming_batches()` reads batch files from the
  landing zone (stand-in for an API poll); `archive_batch()` moves them out = watermark.
- `src/etl/ingest_incremental.py` (FAST LOOP entrypoint): fetch batch -> transform_
  product_b (reused) -> resolve company (norm+region; new->dim insert-only so existing
  company attrs aren't clobbered) -> upsert dim/fact/map -> archive. `upsert(update=)`
  gained DO NOTHING mode.
- **DEMONSTRATED** with `product_b_batch_20261015_0900.csv` (3 recs): facts 4146->4148
  (2 new, 1 update-in-place), companies 334->335 (novatech new; cascade reused), total
  $83,035,467->$83,222,002.85 (+USD50k +EUR120k->USD136,535.85 via batch-date FX).
  SUB001026 active->cancelled in place (no dupe). Re-run = "no batches" (watermark holds).
- Wrinkles noted for later: B renewal inference vs warehouse history (API supplies
  is_renewal for now); incremental path does exact company match else create (no fuzzy/
  needs_review yet).

### Step 5 chunk 3 — nightly is_active/status refresh ✅ (`src/etl/refresh_active.py`)
SLOW LOOP entrypoint. Reads every contract's window from fact_contracts, runs
`active_as_of(as_of)` (as_of from config, default today), writes is_active+status back
via a bulk UPDATE (bindparam executemany). active_as_of stays the single rule; this
materializes it on the cadence it changes.
- Ran as of 2026-10-15: all 4,148 rows now have a status (no more NULLs). recurring ->
  active 1067 / expired 1645 / cancelled 27; non-recurring -> n/a 1409. The 17 B subs
  ending Oct 1-15 flipped active->expired (point of nightly). Idempotent (recompute+overwrite).
- NOTE: stored `status` now means "as of last nightly refresh", not the source's
  09-30 snapshot. active_as_of is pure, so validate_against_b(09-30) still passes.

### Step 5 chunk 2+3 — cron wrappers ✅  (LOAD PHASE COMPLETE)
- `scripts/ingest.sh` (fast) + `scripts/refresh_active.sh` (nightly): self-locating
  (resolve repo root from script path, activate venv, set PYTHONPATH), timestamped logs,
  `set -euo pipefail`. Executable. Both smoke-tested OK.
- `scripts/crontab.example`: template with <SCHEDULE>/<REPO_PATH> placeholders — NOT
  installed (user wants it enabled on deployment, not now). README "Scheduled jobs —
  ENABLE ON DEPLOYMENT" section documents how to flip it on.
- Decision: do NOT touch the real crontab; just hand over ready scripts + template.

## ===== FULL E-T-L PIPELINE COMPLETE =====
Extract (incl. mock-API incremental) -> Transform (A/B/C) -> Unify (star-ready) ->
Load (Postgres star schema, idempotent upsert) -> incremental ingest + nightly active
refresh, both cron-ready. Warehouse: 4,148 contracts / 335 companies, reconciled.

## L2 HYGIENE FIX — product_subtype normalized ✅ (caught by the renewal audit)
Audit pass-1 exposed dirty `product_subtype`: A's SKU had case drift (ia-core vs
IA-CORE, 118 rows) and B's plan had trailing spaces ("Standard ", 52 rows). Fixed at
SOURCE (L2): product_a strips+uppers sku; product_b strips plan. +reconcile checks in
both. Regenerated clean CSVs + unified_fact (all checks pass). Backfilled already-loaded
warehouse rows via `scripts/migrations/001_normalize_subtype.sql` (idempotent; 118 A +
52 B updated) rather than a full reload (which would collide with the incremental batch
state + load_fact's seed-only reconcile). Warehouse now clean: A {IA-CORE,IA-PRO,IA-ENT},
B {Standard,Premium,+Pro/Enterprise from the mock batch}. product (A/B/C) + region were
already clean -> GRR will segment on product x region.

## RENEWAL AUDIT (step 0) — DONE ✅  (`src/etl/metrics/audit_renewals.py`)
Pass 1 (lay of land): 2,739 recurring (A=1622, B=1117), ~5yr history, 1,667 expired,
291 multi-contract companies. Caught dirty subtype -> fixed (see L2 hygiene above).
Pass 2 (reconstruction): chain-match within company×product.
- Renewal window [−30,+60]d justified by gap distribution (880 at 0d, 488 at 1-7d, valley
  by 30-60d, p90=29d).
- CENSORING shown: naive GRR 48.3% vs MATURED 86.5% (maturation lag 60d). The key control.
- Segment by product×region: all 6 cells 111-475 events; A ~89-91% GRR, B ~80-86% (product
  = primary driver).
- Validated 92.5% vs B's is_renewal flag.
**DECISIONS LOCKED** (window [−30,+60]d, maturation lag 60d, segment product×region) —
all documented in `docs/methodology.md` (portfolio justification doc, linked from README).

## MODELING APPROACH (locked): closed-form mean + Monte Carlo band
- Bar height (expected renewals) = closed-form geometric survival (X*p, p^2, ...). MC overkill for the mean.
- Band (whisker on the stack TOTAL) = Monte Carlo. MC also VALIDATES the closed form (mean must match) — the Black-Scholes×MC pattern (user's GameTheoryModel MC chops reused: path loop, convergence test, CoV stop, bootstrap CIs).
- KEY: band is driven by PARAMETER/REGIME uncertainty (sample p per path + stress draws), NOT per-contract Bernoulli coin-flips (those average out -> fake-tight band).
- Keep per-path dynamics SIMPLE (renewal survival), not GameTheory-level.

## Model step 1 — GRR + uncertainty DONE ✅ (`src/etl/metrics/retention.py`)
Per product×region segment: logo rate + Wilson CI; revenue-weighted GRR + bootstrap 90% CI;
pooled-to-product fallback if n<N_MIN=30. Reuses audit reconstruct(); matured-only.
Result: A ~89-91% GRR, B ~80-86%; ALL 86.5% [83.9,88.8]. Band widens as n shrinks
(B·EU n=111 -> 71.8-87.2 vs A·NA n=475 -> 84.7-92.4). This is what the MC samples.

## Model step 2a — expected-renewal layer (closed-form mean) DONE ✅ (`src/etl/metrics/projection.py`)
Geometric survival: each active contract renews at segment p, contributing p,p^2,... terms,
recognized straight-line, 3y horizon. No double-count (only project future expiries; cancelled
excluded). `rates` is a pluggable {(product,region):p} map (flat now; recency-weighted later —
backtest picks). Reconciles to the cent. Result: $32.1M expected renewals over 3y on top of
the $15.8M floor. STACK crossover: near-term ~all guaranteed, by 2029 ~all expected (floor->0).
Decision noted: trend handling = recency-weighting, documented in methodology.md.

## Model step 2 — projection DONE ✅
- 2a refactored to a RECOGNITION TENSOR A[seg,gen,week] (recognized $ at p=1) in
  `projection.py`; closed-form = reduce at point p. Still reconciles ($32.08M).
- 2b Monte Carlo band (`band.py`): each path draws segment p from bootstrap (retention.
  _boot_grr), PERSISTS across generations, reduces the tensor: exp_paths = Σ_g (P**g).T @ A.
  Band = parameter uncertainty only (correlated regime + stress = labelled overlay, later).
  - VALIDATED: fixed-p MC == closed form exactly. Jensen gap +$18.5k (+0.06%, convex p^g) as
    predicted. Converged: 2000 paths, CoV 2.5%, P90 half==full.
  - Whisker WIDENS right: ±$39 now -> ±$12,120 at 3y (~300x). Honest cone.
MODEL CORE COMPLETE: floor + expected + band, reconciled & cross-validated.

## Model step 3 — walk-forward BACKTEST + band recalibration DONE ✅ (`backtest.py`)
Scope: validate ONE-CYCLE (gen-1) renewal only (compounding has no future to test). Quarterly
cohorts, matured-only, censoring lag inside loop. 11 windows (limited power, stated).
- FINDING 1: point forecast sound — bias -0.3/-0.5%, MAE ~$81k (~6%). Recency > flat on all
  metrics. PRODUCTION CONFIG = rolling + recency.
- FINDING 2: bootstrap band WAY too tight — coverage 18-36% vs 80%. Backtest caught our
  overconfidence (missing drift + cohort idiosyncrasy).
- FIX: calibrate band to realized errors (actual-pred)/pred = ±~7%/quarter-cycle. LOO coverage
  ~73%; NOT chasing 80% (8/11 indistinguishable from 80% at n=11 — would overfit metric).
- WIRED into forward band (`band.py` rewritten): each path draws per-cycle error from the
  empirical residual pool, COMPOUNDS (F_g=prod(1+e)); gen-g revenue scaled by F_g. Uses
  rolling+recency production rates (`backtest.segment_rates`). Zero-error path == closed form
  (validation PASS). Whisker: ±0.1% now -> ±12% at 3y (~2.7x the old bootstrap). Honest cone.
- ALL documented in docs/methodology.md (section 8 results + decisions-table rows + risks).

## Stacked-bar CHART DONE ✅ (`src/etl/metrics/chart.py`)
matplotlib (added matplotlib==3.9.2). Weekly stacked bars: guaranteed (solid blue) +
expected renewals (hatched orange = projected) + grey P10-P90 band widening right.
Dataviz skill followed: validated palette (slots 1/2, CVD ΔE 24.7), fill=certainty
encoding, recessive grid, legend, eyeballed (fixed title/subtitle collision + legend order).
Writes `reports/projection.png` + `data/processed/projection_series.json` (weekly:
guaranteed/expected/p10/p50/p90) — the JSON is what Flask will serve.
Story: floor melts, renewals fill, band fans out; crossover ~Sep 2027.

## New-business layer (3rd) + 3-layer chart DONE ✅
- `audit_newbiz.py`: new = not-a-renewal (B via is_renewal, A via chain, one-time always new).
  $55M/5y, 72% one-time (A perp+C), 28% new recurring. Growing ~+11%/yr.
- `new_business.py`: quarterly forecast flat/damped/trend + 12-window walk-forward (no
  maturation lag). DAMPED chosen (bias -83k vs flat -259k; trend worst/over-predicts).
  forward_quarterly/forward_new_weekly (recognized≈booked run-rate) + newbiz_errors.
- `band.py` v3: 3-layer MC — floor(certain) + renewals(±7%/cycle compounding) + new-biz
  (±18% PERSISTENT level error, NOT compounded — compounding exploded to ±87%, fixed).
  Band now 11-17% growing as floor melts. Seeded (stable).
- `chart.py`: 3 stacked layers (blue solid / orange hatch / aqua dots = certainty ranking),
  validated 3-colour palette, grey P10-P90. reports/projection.png + projection_series.json.
  Story: floor melts, renewals fill, new-biz steady on top (~$300k/wk), total ~$650k->$585k/wk.
- Docs: methodology §5b (new-biz) + §10 (ops: scheduled refresh + self-adjust + circuit-breaker)
  + decisions rows + risks. All traceable.
- DECISIONS (user): damped OK given guardrails; circuit-breaker + scheduled refresh = planned ops.

## REFINEMENT (user Qd the downtrend): expansion + trend-uncertainty ✅
- B — EXPANSION/NRR: added succ_arr to reconstruct; `retention.nrr_audit()`. GRR 86.5% ->
  NRR 92.0% (+5.5% expansion; 13% expand/7% contract/80% flat; A 94%, B 91%). Still <100%
  so base decays ~8%/yr (not 14%) — softens, doesn't reverse. SWITCHED projection to NRR
  (succ_arr via backtest.RETAIN_COL); GRR kept as KPI. Re-backtested: bias -1.2%, recency
  best, cov ~73%; production config -> EXPANDING+recency (edged rolling under NRR).
- A — NEW-BIZ TREND UNCERTAINTY: center stays data-derived damped (NO judgment call — growth
  unknowable, +2..+24%/yr by window). `new_business.trend_sigma()` = 9.4%/yr (spread across
  windows). band.py: per-path persistent growth deviation N(0,σ) compounding over years +
  ±18% level error. Whisker now 13% -> 27% at 3y, asymmetric upside.
- RESULT: central flatter (~$663k->$632k/wk vs old $650->586), band honestly spans
  $502k-$845k at 3y. No longer a confident decline. Re-charted + re-emitted JSON.
- Docs: methodology §5 (NRR), §5b (trend band), decisions rows, §8 config. PROGRESS here.
- TEACHING MOMENT: user pushed back on arbitrary "pick a growth %"; corrected to "center =
  data-derived, band carries uncertainty; override only with info data lacks (labelled scenario)".

## FIXES (user eyeballed the chart):
- Partial-week t0 bar was distorted (floor day-prorated, new-biz not) -> drop the current
  partial week; chart/JSON start at first FULL week. (band.run_mc)
- Near-term cone width (±10.6%) explained + verified: floor 54% CERTAIN, new business 45%
  UNSOLD (±18% measured) -> near-term uncertainty is entirely the unsold new-biz slice;
  cone grows ±10.6% -> ±27% (right shape). Data gap noted: no pipeline/bookings-forward data
  to tighten near-term new business.

## PIPELINE DATA (weekend drop) — mini-ETL DONE ✅
New data in _data: pipeline_opportunities.csv (8143, 2 CRMs) + pipeline_stage_history.csv (30k
events). Support data parked. Answer keys + generators QUARANTINED in _answer_key/ (gitignored,
not read until final scoring). Deep-research methodology brief at reports/Sales pipeline
forecasting methods.md (calibrate CRM prob via isotonic; MC over win×timing×amount + bootstrap;
lead-time reliable-horizon blend; point-in-time backtest).
- Extract: `src/etl/extract/pipeline.py` (load_opportunities, load_stage_history; raw text).
- Transform: `src/etl/transform/pipeline.py` — conform 2 CRMs: product 12->A/B/C, opp_type 9->
  new/renewal/expansion, stage (typos/case, 2 vocabs)->{Qualify,Proposal,Negotiate,Contract,Won,
  Lost}+rank1-4, amount strip $/commas+FX, prob 25/25%/0.25->[0,1], mixed dates, drop 40 dup ids.
  raise-on-unmapped. 8103 clean (2585 won/4917 lost/601 open). VERIFIED: mappings correct (cross-
  tab), 0 silent parse losses, 100% of 1708 won erp_refs link to real fact_contracts.
- Load: `fact_opportunity` + `pipeline_stage_history` tables (load/tables.py); `load_pipeline.py`
  upsert (idempotent). company_id = SOFT link (prospects not in dim_company -> no hard FK).
- NOTE: 877 won opps have NO erp_ref -> handle opp<->contract linkage as a VALIDATED reconciliation
  step (not transform; same principle as C-name enrichment). 1708 known links = ground-truth anchor.

## PIPELINE FORECAST MODEL — built (calibration -> timing -> MC) ✅
- opp<->contract reconciliation: matcher (product+amount~10%+date~7d, company tiebreak) VALIDATED
  92.8% on 1708 known; ~48% unambiguous. NOT needed for forecast (only blend-time double-count),
  so parked. 1708 known links = ground truth.
- Step 1 CALIBRATION (`pipeline_calibration.py`): empirical stage win-rate from stage_history
  (reached-stage, resolved only, open censored): Qualify 35% / Proposal 47% / Negotiate 70% /
  Contract 72% vs CRM 25/50/75/75 -> CRM UNDER-states early deals. Data-derived, answer key untouched.
- Step 2 TIMING (`pipeline_timing.py`, lifelines KM per product): median close 39/41/24d A/B/C;
  open deals right-censored; conditional sampling S(t)/S(age) (old deals pushed later).
- Step 3 MC (`pipeline_forecast.py`): per trial Beta(won+1,lost+1) p per stage (= param uncertainty
  + cross-deal correlation) x Bernoulli win x survival close-month x opp amount -> monthly dist.
  Result: 577 open deals -> P50 $5.0M/6mo [$4.0-6.2M]; converts Oct-Nov then RUNS DRY by ~month 3
  (= empirical reliable horizon -> hand off to run-rate). lifelines==0.29.0 added.

## Step 4 BACKTEST — point-in-time walk-forward DONE ✅ (`pipeline_backtest.py`)
Reconstruct pipeline as-of T from stage_history (stage = last to_stage <= T); refit calibration
+ timing on resolved-BEFORE-T only (no leakage); forecast [T,T+2mo]; vs actual won-in-window.
24 monthly origins. RESULTS: WAPE 13.5%, coverage 79% (target 80 -> band well-calibrated out of
the box, no recalibration needed), mean bias +9.6% (slight over-forecast), pinball $72k.
Known limit: only current amount (no historical amount snapshots) -> amount not point-in-time
(affects both sides equally; flagged).
BIAS RESOLVED: empirical debias (user chose). factor = sum(actual)/sum(p50) = 0.912, validated
LEAVE-ONE-OUT (honest): debiased WAPE 11.7% (from 13.5), bias +0.0% (from +9.6), coverage 79% held.
Wired into live forecast (pipeline_forecast applies debias_factor()). Live: P50 $4.57M/6mo
[$3.62-5.68M]. `debias_factor()` in pipeline_backtest (lru_cached).
PIPELINE MODEL COMPLETE: calibration -> timing -> MC -> backtest -> debias. Pure statistical.

## NEXT: (5) BLEND near-term pipeline (converts ~2mo, runs dry ~mo3) + far-term run-rate at the
## reliable horizon -> swap into the new-business layer (pure statistical, replaces hand-tuned).
## Still pending: Flask API serve projection_series.json.
Then front end. BACKLOG ops: nightly/weekly projection-refresh cron (3rd loop) + circuit-breaker
+ "growth falling off" monitor charts. Plus the mock-API data generator (earlier backlog).

## METRICS (L4) — started (teaching mode, go slow)
Target artifact (user design): weekly STACKED bar — bottom=GUARANTEED (contracted)
revenue, top=EXPECTED (renewal projection). Build certain floor first, exact; projection
is Phase 3 (model as a range/scenario band per Shackle/Taleb, not a false-precision line).
- Revenue measure = recognized revenue, straight-line (ASC 606): arr_usd/365.25 per active
  DAY. Taught recognized(earned) vs collected(cash) distinction; chose recognized.
- **Metric 1 — weekly guaranteed runoff DONE ✅** (`src/etl/metrics/runoff.py`):
  `weekly_runoff(as_of=today)` -> per-week [week_start, active_licenses, guaranteed_usd],
  recurring only, clipped today-forward, cancel ends recognition, day-level overlap.
  Result: **$15,769,335 contracted revenue still to recognize**, 155 weeks to 2029-09.
  Reconciles to the cent (buckets == direct remaining value).
  - Cross-check: week-0 active_licenses = 1067 = nightly is_active count (independent agree).
  - 🐛 LESSON: rounded each bucket then summed -> 4c drift. Fix: full precision internally,
    round only for display, reconcile with np.isclose tolerance.

## NEXT: serving + quant (the L4 / metrics payoff)
- Flask API: project CSV/JSON from the warehouse on front-end request (user leans CSV).
- Metrics/quant layer: licenses outstanding + churn (reads materialized is_active), ARR,
  cohorts, retention/NRR, then Phase 3 projections.
- Front end: Tableau Public (on a published extract) OR custom JS hitting Flask — decide
  once metrics exist. Dockerize api+pipeline into the compose later.
- README full refresh when packaging for portfolio (status still says "scaffolding").

## BACKLOG (parked, build later)
- **Mock-API data GENERATOR (option 1, user-approved)**: the demo batch was a single
  hand-made static file (now archived) — there is NO live data source yet. Build a
  generator that synthesizes a small realistic mix of new records each poll (mostly new
  sales, some renewals, occasional cancellations), dated ~now, so the dashboard actually
  moves. Dependency: FX cache ends 2026-10-02 — live "today"-dated FX rows need the cache
  refreshed (or ffill latest rate). This is what makes the n-minute loop meaningful.

### Step 1 — Postgres up ✅
- `docker-compose.yml`: `db` service (postgres:16, named vol `pgdata`, healthcheck,
  restart). Written to grow into api/pipeline services later.
- Host **5433** -> container 5432 (system Postgres already owns host 5432).
- `.env` (git-ignored, confirmed) + `.env.example`: POSTGRES_* + `DATABASE_URL`
  (`postgresql+psycopg2://etl:...@localhost:5433/etl_warehouse`).
- requirements += SQLAlchemy 2.0.36, psycopg2-binary 2.9.10, python-dotenv 1.0.1.
- Verified: psql connects, PG 16.10, db `etl_warehouse` live. Commands in compose header.

## Also pending: L4 VIEWS / metrics (the quant payoff)
- licenses-outstanding + churn (uses active_as_of at a chosen snapshot), ARR, cohorts,
  retention/NRR, then Phase 3 projections. Sits on top of Postgres.

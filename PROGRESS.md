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
1. FIX A transform: backfill `customer_name` per customer_id (mirror region). Re-run A.
2. Build normalizer; match B→A on (norm_name, region); auto-accept exact.
3. Install rapidfuzz; fuzzy-match the ~39 residual; route gray band to review.
4. Assign a canonical customer_id/key across sources; enrich C's name/region from A by Customer ID.
Then: **active-rule** (status/is_active for A & C) → **L3 UNIFY** (concat A+B+C).
- Still to lock before L3 stack: active-rule, company identity.

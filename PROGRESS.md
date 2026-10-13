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

## Current status / next step
- A is clean. Next: **L2 Product B** (CAD subscriptions) — harder: multi-currency (USD/GBP/EUR → need FX), mixed date formats, quoted commas, status/is_renewal, dup contract_no.
- Decisions likely needed for B: FX rates/as-of, date parsing strategy, dup policy, active/status mapping.
- Still parked for L3: active-rule (end_date/is_active), customer identity across sources.
- Still to lock before L3 stack: active-rule, company identity.

"""Level 2 — Transform: conform the two-CRM pipeline into one clean opportunity table.

Raw all-text from L1 -> a tidy `fact_opportunity`-shaped frame. The two CRMs (HS-ACQ,
SF-LEG) disagree on everything, so we map each dirty dimension to a canonical form and
raise loudly on anything unmapped (so a new variant can never slip through silently).

Decisions:
  - product   : 12 spellings -> A / B / C
  - opp_type  : 9 variants  -> new / renewal / expansion
  - stage     : per-CRM vocab + typos/case -> {Qualify,Proposal,Negotiate,Contract,Won,Lost}
                with an open-stage rank 1-4 (the ladder the win-calibration model will use)
  - amount    : strip thousands commas -> float; FX->USD at created date (clamped to cache)
  - probability: '25' / '25%' / '0.25' -> 0.25 in [0,1]  (the CRM's STATED prob — calibrated later)
  - dates     : mixed ISO + US m/d/Y -> datetime
  - 40 duplicate opportunity_id rows -> dropped (keep first)
  - company_id: Model-2 scheme (normalized account name + region) to tie to dim_company
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from etl.extract.pipeline import OPPORTUNITIES_PATH, load_opportunities
from etl.fx import load_fx_rates, to_usd
from etl.unify.names import normalize_name

PRODUCT_MAP = {
    "automation suite": "A", "ia suite": "A", "industrial automation": "A",
    "cad subscription": "B", "cad sub": "B", "cad": "B",
    "simulation add-on": "C", "simulation addon": "C", "simulation": "C", "sim module": "C",
}
OPP_TYPE_MAP = {
    "new business": "new", "new": "new", "new biz": "new",
    "renewal": "renewal",
    "expansion": "expansion", "add-on": "expansion", "upsell": "expansion",
}
# canonical stage, open-ladder rank (None = terminal)
STAGE_MAP = {
    "qualification": ("Qualify", 1), "discovery": ("Qualify", 1),
    "proposal": ("Proposal", 2), "proposal/quote": ("Proposal", 2),
    "quote sent": ("Proposal", 2), "demo done": ("Proposal", 2),
    "negotiation": ("Negotiate", 3), "negociation": ("Negotiate", 3),
    "contract out": ("Contract", 4),
    "won": ("Won", None), "closed won": ("Won", None), "closed-won": ("Won", None),
    "lost": ("Lost", None), "closed lost": ("Lost", None),
    "closed-lost": ("Lost", None), "lost - closed": ("Lost", None),
}


def _norm(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().str.replace(r"\s+", " ", regex=True)


def _map_strict(series: pd.Series, mapping: dict, name: str):
    out = _norm(series).map(mapping)
    if out.isna().any():
        bad = sorted(series[out.isna()].unique())
        raise ValueError(f"Unmapped {name}: {bad}")
    return out


def _parse_amount(s: pd.Series) -> pd.Series:
    # Strip thousands commas, currency symbols ($, EUR, GBP), and whitespace.
    cleaned = s.str.replace(r"[^0-9.\-]", "", regex=True).str.strip().replace("", np.nan)
    return pd.to_numeric(cleaned, errors="raise")


def _parse_prob(s: pd.Series) -> pd.Series:
    v = pd.to_numeric(s.str.replace("%", "", regex=False).str.strip().replace("", np.nan),
                      errors="raise")
    v = v.where(v <= 1, v / 100.0)          # 25 -> 0.25 ; 0.25 stays
    return v.clip(0, 1)


def _parse_mixed_date(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    iso = s.str.contains("-", na=False)
    us = s.str.contains("/", na=False)
    out[iso] = pd.to_datetime(s[iso], format="%Y-%m-%d", errors="coerce")
    out[us] = pd.to_datetime(s[us], format="%m/%d/%Y", errors="coerce")
    return out


def transform_pipeline(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.drop_duplicates("opportunity_id", keep="first").copy()

    stage_can, stage_rank = zip(*_map_strict(df["stage"], STAGE_MAP, "stage"))
    stage_can = pd.Series(stage_can, index=df.index)
    status = np.where(stage_can == "Won", "won",
                      np.where(stage_can == "Lost", "lost", "open"))

    currency = df["currency"].str.strip().replace("", "USD")
    amount = _parse_amount(df["amount"])
    created = _parse_mixed_date(df["created_date"])
    close = _parse_mixed_date(df["close_date"])

    # FX at created date, clamped to the cached rate range (open deals close in the future).
    rates = load_fx_rates()
    lo, hi = rates.index.min(), rates.index.max()
    fx_date = created.fillna(close).dt.normalize().clip(lower=lo, upper=hi)
    amount_usd = to_usd(amount, currency, fx_date)

    out = pd.DataFrame({
        "opportunity_id": df["opportunity_id"],
        "crm_source": df["crm_source"],
        "company_id": [f"{normalize_name(n)}|{r}" for n, r in zip(df["account_name"], df["region"])],
        "account_id": df["account_id"],
        "account_name": df["account_name"].str.strip(),
        "region": df["region"].str.strip(),
        "product": _map_strict(df["product"], PRODUCT_MAP, "product"),
        "product_subtype": df["sku_or_plan"].str.strip(),
        "opp_type": _map_strict(df["opp_type"], OPP_TYPE_MAP, "opp_type"),
        "stage": stage_can,
        "stage_rank": pd.array(stage_rank, dtype="Int64"),
        "status": status,
        "amount_orig": amount,
        "currency": currency,
        "amount_usd": amount_usd,
        "crm_probability": _parse_prob(df["probability"]),
        "forecast_category": df["forecast_category"].str.strip().replace("", pd.NA),
        "created_date": created,
        "close_date": close,
        "seats": pd.to_numeric(df["seats"], errors="coerce").astype("Int64"),
        "term_months": pd.to_numeric(df["term_months"], errors="coerce").astype("Int64"),
        "owner": df["owner"].str.strip(),
        "lead_source": df["lead_source"].str.strip().replace("", pd.NA),
        "loss_reason": df["loss_reason"].str.strip().replace("", pd.NA),
        "erp_ref": df["erp_ref"].str.strip().replace("", pd.NA),
        "source_file": OPPORTUNITIES_PATH.name,
        "loaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return out


def _canon_stage(series: pd.Series) -> pd.Series:
    """Lenient canonical stage (keeps unknown stage names rather than raising —
    the history log can contain stages not in the opportunity snapshot)."""
    n = _norm(series)
    return n.map(lambda x: STAGE_MAP[x][0] if x in STAGE_MAP else (x.title() if x else pd.NA))


def transform_stage_history(raw: pd.DataFrame) -> pd.DataFrame:
    """Stage-change event log -> parsed timestamps + canonical stages, deduped.
    This is the basis for point-in-time ('as of T') pipeline reconstruction."""
    df = raw.copy()
    changed = pd.to_datetime(df["changed_on"].str.strip(), format="mixed", errors="coerce")
    out = pd.DataFrame({
        "opportunity_id": df["opportunity_id"].str.strip(),
        "from_stage": _canon_stage(df["from_stage"]),
        "to_stage": _canon_stage(df["to_stage"]),
        "changed_on": changed,
        "changed_by": df["changed_by"].str.strip().replace("", pd.NA),
    })
    out = out.dropna(subset=["changed_on", "to_stage"])
    return out.drop_duplicates(subset=["opportunity_id", "changed_on", "to_stage"], keep="first")


def reconcile(raw: pd.DataFrame, clean: pd.DataFrame) -> None:
    n_dupes = len(raw) - raw["opportunity_id"].nunique()
    checks = {
        "dropped only duplicate ids": len(clean) == raw["opportunity_id"].nunique(),
        "opportunity_id unique": not clean["opportunity_id"].duplicated().any(),
        "every stage mapped": clean["stage"].notna().all(),
        "status partitions won/lost/open": set(clean["status"]) <= {"won", "lost", "open"},
        "open stages have rank 1-4": bool(
            clean.loc[clean["status"] == "open", "stage_rank"].between(1, 4).all()
        ),
        "terminal stages have no rank": bool(
            clean.loc[clean["status"] != "open", "stage_rank"].isna().all()
        ),
        "amount_usd present where amount present": bool(
            (clean["amount_orig"].notna() == clean["amount_usd"].notna()).all()
        ),
        "probability in [0,1]": bool(clean["crm_probability"].dropna().between(0, 1).all()),
        "erp_ref only on won": bool(clean.loc[clean["status"] != "won", "erp_ref"].isna().all()),
    }
    print(f"raw rows {len(raw):,} | duplicate-id rows {n_dupes} | clean rows {len(clean):,}\n")
    print("status:", clean["status"].value_counts().to_dict())
    print("product:", clean["product"].value_counts().to_dict())
    print("opp_type:", clean["opp_type"].value_counts().to_dict())
    print("open by stage:", clean.loc[clean['status']=='open', 'stage'].value_counts().to_dict())
    print("\nCHECKS")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not all(checks.values()):
        raise SystemExit("Pipeline transform reconciliation FAILED.")
    print("\nAll checks passed. ✅")


if __name__ == "__main__":
    raw = load_opportunities()
    clean = transform_pipeline(raw)
    reconcile(raw, clean)

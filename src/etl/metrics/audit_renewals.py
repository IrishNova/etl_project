"""Step 0 — renewal data audit. READ-ONLY diagnostics, no modeling yet.

Purpose: let the DATA tell us how sophisticated a retention model it can honestly
support, before we build GRR. Pass 1 (this file) is the lay of the land: the recurring
universe, the time span, and whether segment sample sizes are large enough to estimate
a rate per segment or force us to pool.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from etl.load.db import get_engine

TODAY = pd.Timestamp(date.today()).normalize()


def _load_recurring() -> pd.DataFrame:
    sql = """
        SELECT product, product_subtype, region, company_id,
               start_date, end_date, cancel_date, arr_usd, is_renewal
        FROM fact_contracts
        WHERE revenue_type = 'recurring'
    """
    df = pd.read_sql(sql, get_engine())
    for c in ("start_date", "end_date", "cancel_date"):
        df[c] = pd.to_datetime(df[c])
    return df


def pass1_lay_of_the_land() -> None:
    df = _load_recurring()
    n = len(df)
    print(f"=== RECURRING UNIVERSE: {n:,} contracts ===\n")

    print("by product:")
    print(df["product"].value_counts().to_string(), "\n")

    print("time span:")
    print(f"  earliest start : {df['start_date'].min().date()}")
    print(f"  latest start   : {df['start_date'].max().date()}")
    print(f"  earliest end   : {df['end_date'].min().date()}")
    print(f"  latest end     : {df['end_date'].max().date()}")
    span_yrs = (df["end_date"].max() - df["start_date"].min()).days / 365.25
    print(f"  total span     : {span_yrs:.1f} years\n")

    expired = df["end_date"] < TODAY
    active = (df["start_date"] <= TODAY) & (df["end_date"] >= TODAY)
    future = df["start_date"] > TODAY
    print(f"status as of {TODAY.date()}:")
    print(f"  expired (end < today) : {int(expired.sum()):,}")
    print(f"  active                : {int(active.sum()):,}")
    print(f"  future start          : {int(future.sum()):,}\n")

    print("is_renewal availability (flag only exists on B):")
    print(f"  populated : {int(df['is_renewal'].notna().sum()):,}")
    print(f"  null      : {int(df['is_renewal'].isna().sum()):,}")
    pop = df[df["is_renewal"].notna()]
    if len(pop):
        print(f"  of populated -> renewals: {int(pop['is_renewal'].sum()):,} "
              f"/ {len(pop):,} ({pop['is_renewal'].mean():.1%})\n")

    print("segment sizes — by REGION (recurring):")
    print(df["region"].value_counts().to_string(), "\n")

    print("segment sizes — by PLAN/subtype (recurring):")
    print(df["product_subtype"].value_counts().to_string(), "\n")

    print("contracts per company (how many renewal chains exist):")
    per_co = df.groupby("company_id").size()
    print(f"  companies with recurring contracts : {per_co.size:,}")
    print(f"  companies with >1 contract         : {int((per_co > 1).sum()):,}")
    print(f"  max contracts for one company      : {int(per_co.max())}")
    print(f"  median contracts per company       : {per_co.median():.1f}")


def _effective_end(df: pd.DataFrame) -> pd.Series:
    """A contract's coverage ends at its end_date, or earlier if cancelled."""
    return df["end_date"].where(df["cancel_date"].isna(),
                                df[["end_date", "cancel_date"]].min(axis=1))


def reconstruct(df: pd.DataFrame, win_before: int = 30, win_after: int = 60,
                search_after: int = 400) -> pd.DataFrame:
    """One row per expiry EVENT: did the same company (same product) start a
    successor contract near this one's expiry?

    Matching is within (company_id, product) — A-maintenance renews A, B renews B.
    A successor is the nearest un-claimed contract whose start falls in
    [eff_end - win_before, eff_end + win_after]; greedy claiming stops one successor
    from "renewing" two predecessors. search_after only widens the view for the gap
    histogram, not the renewal decision.
    """
    df = df.copy()
    df["eff_end"] = _effective_end(df)
    df = df.sort_values(["company_id", "product", "eff_end"]).reset_index(drop=True)

    recs = []
    for (co, prod), g in df.groupby(["company_id", "product"], sort=False):
        starts = g["start_date"].to_numpy("datetime64[D]")
        ends = g["eff_end"].to_numpy("datetime64[D]")
        arrs = g["arr_usd"].astype(float).fillna(0).to_numpy()
        isren = g["is_renewal"].to_numpy()
        region = g["region"].to_numpy()
        claimed: set[int] = set()
        for pi in range(len(g)):
            E = ends[pi]
            best_j, best_gap = None, None
            for j in range(len(g)):
                if j == pi or j in claimed:
                    continue
                gap = int((starts[j] - E).astype(int))
                if -win_before <= gap <= search_after:
                    if best_gap is None or abs(gap) < abs(best_gap):
                        best_gap, best_j = gap, j
            renewed = best_j is not None and (-win_before <= best_gap <= win_after)
            if renewed:
                claimed.add(best_j)
            recs.append({
                "company_id": co, "product": prod, "region": region[pi],
                "eff_end": pd.Timestamp(E), "pred_arr": arrs[pi],
                "nearest_gap_days": best_gap,
                "renewed": bool(renewed),
                "retained_arr": float(min(arrs[best_j], arrs[pi])) if renewed else 0.0,
                "succ_arr": float(arrs[best_j]) if renewed else 0.0,  # uncapped -> NRR/expansion
                "succ_is_renewal": (bool(isren[best_j]) if renewed and isren[best_j] is not None
                                    and not pd.isna(isren[best_j]) else None),
            })
    return pd.DataFrame(recs)


def _grr(ev: pd.DataFrame) -> tuple[float, float, float]:
    """Return (logo renewal rate, gross revenue retention, n)."""
    n = len(ev)
    if n == 0:
        return (float("nan"), float("nan"), 0)
    logo = ev["renewed"].mean()
    grr = ev["retained_arr"].sum() / ev["pred_arr"].sum() if ev["pred_arr"].sum() else float("nan")
    return (logo, grr, n)


def pass2_reconstruct(win_before: int = 30, win_after: int = 60) -> None:
    df = _load_recurring()
    ev = reconstruct(df, win_before=win_before, win_after=win_after)

    print("=== A. GAP DISTRIBUTION — nearest successor start minus this expiry ===")
    gaps = ev["nearest_gap_days"].dropna()
    print(f"events with a nearby successor (<=400d): {len(gaps):,} of {len(ev):,}")
    buckets = pd.cut(gaps, bins=[-999, -1, 0, 7, 30, 60, 90, 180, 400],
                     labels=["<0", "0", "1-7", "8-30", "31-60", "61-90", "91-180", "181-400"])
    print(buckets.value_counts().sort_index().to_string())
    print(f"percentiles (days): p50={gaps.median():.0f}  p90={gaps.quantile(.9):.0f}  "
          f"p99={gaps.quantile(.99):.0f}\n")

    print(f"=== B. RENEWAL EVENTS (window: -{win_before}d .. +{win_after}d) ===")
    logo, grr, n = _grr(ev)
    print(f"all expiry events: {n:,}   renewed: {int(ev['renewed'].sum()):,}   "
          f"logo rate: {logo:.1%}   gross rev retention: {grr:.1%}\n")

    print(f"=== C. MATURED ONLY (eff_end < today - {win_after}d maturation lag) ===")
    cutoff = TODAY - pd.Timedelta(days=win_after)
    mat = ev[ev["eff_end"] < cutoff]
    mlogo, mgrr, mn = _grr(mat)
    print(f"matured events: {mn:,} (dropped {len(ev) - mn:,} too recent/future to resolve)")
    print(f"  logo renewal rate     : {mlogo:.1%}")
    print(f"  gross revenue retention: {mgrr:.1%}  <-- the honest GRR\n")

    print("=== D. SEGMENT FEASIBILITY — matured events by product x region ===")
    seg = (mat.groupby(["product", "region"])
              .apply(lambda g: pd.Series({"n": len(g), "logo": g["renewed"].mean(),
                                          "grr": g["retained_arr"].sum() / g["pred_arr"].sum()}),
                     include_groups=False)
              .reset_index())
    seg["n"] = seg["n"].astype(int)
    seg["logo"] = (seg["logo"] * 100).round(1)
    seg["grr"] = (seg["grr"] * 100).round(1)
    print(seg.to_string(index=False))

    print("\n=== E. CROSS-CHECK vs B's own is_renewal flag ===")
    b_ren = mat[(mat["product"] == "B") & (mat["renewed"])]
    flagged = b_ren["succ_is_renewal"].dropna()
    if len(flagged):
        print(f"B renewed events with a flagged successor: {flagged.mean():.1%} "
              f"carry is_renewal=True ({int(flagged.sum())}/{len(flagged)})")
    else:
        print("no B renewed events with a usable flag")


if __name__ == "__main__":
    pass2_reconstruct()

"""C-suite metric — the ARR bridge (waterfall).

Decomposes the change in active recurring ARR over a period into the flows execs expect:
  starting ARR + NEW + EXPANSION − CONTRACTION − CHURN = ending ARR.

All flows come from ONE consistent predecessor->successor pairing (same company+product,
successor starting near a predecessor's expiry), so the bridge reconciles:
  - churn       : a contract expiring in-period with no successor (ARR leaves the book)
  - expansion   : renewal where successor ARR > predecessor ARR (the uplift)
  - contraction : renewal where successor ARR < predecessor ARR (the drop)
  - new         : a contract active at end, started in-period, that is NOT a renewal of a
                  predecessor still live at the period start (a genuinely new ARR entry)
A reconciliation residual is reported; a large one means the decomposition is wrong.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from etl.metrics.audit_renewals import _effective_end, _load_recurring

WIN_BEFORE, WIN_AFTER = 30, 60


def _pairs(rec: pd.DataFrame):
    """Return pred_of {successor_idx: predecessor_idx} using a single greedy chain match."""
    pred_of = {}
    for _, g in rec.groupby(["company_id", "product"]):
        rows = list(g.sort_values("start_date").itertuples())
        used = set()
        for i, succ in enumerate(rows):
            best, best_gap = None, None
            for j in range(i):
                pr = rows[j]
                if pr.Index in used:
                    continue
                gap = (succ.start_date - pr.eff_end).days
                if -WIN_BEFORE <= gap <= WIN_AFTER and (best_gap is None or abs(gap) < abs(best_gap)):
                    best, best_gap = pr, gap
            if best is not None:
                pred_of[succ.Index] = best.Index
                used.add(best.Index)
    return pred_of


def _active_arr(rec, T):
    m = (rec["start_date"] <= T) & (rec["eff_end"] >= T)
    return float(rec.loc[m, "arr_usd"].sum())


def arr_bridge(t0: pd.Timestamp, t1: pd.Timestamp) -> dict:
    rec = _load_recurring()
    rec["eff_end"] = _effective_end(rec)
    arr = rec["arr_usd"]
    start, end = _active_arr(rec, t0), _active_arr(rec, t1)

    pred_of = _pairs(rec)
    succ_of = {p: s for s, p in pred_of.items()}
    renewed = set(pred_of.values())            # predecessor idxs that got a successor

    churn = expansion = contraction = 0.0
    for idx in rec.index[(rec["eff_end"] > t0) & (rec["eff_end"] <= t1)]:
        if idx in renewed:
            d = arr[succ_of[idx]] - arr[idx]
            expansion += max(d, 0.0)
            contraction += max(-d, 0.0)
        else:
            churn += float(arr[idx])

    # new = active at t1, started in-period, and not a renewal of a predecessor live at t0
    pred_end = rec.index.to_series().map(lambda i: rec.at[pred_of[i], "eff_end"] if i in pred_of else pd.NaT)
    fresh = (~rec.index.isin(pred_of)) | (pred_end <= t0)
    new_mask = fresh & (rec["start_date"] > t0) & (rec["start_date"] <= t1) & (rec["eff_end"] >= t1)
    new = float(arr[new_mask].sum())

    computed = start + new + expansion - contraction - churn
    return {"t0": t0.date(), "t1": t1.date(), "start": start, "new": new,
            "expansion": expansion, "contraction": contraction, "churn": churn,
            "end": end, "computed_end": computed, "residual": end - computed}


def render_waterfall(b: dict, path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    BLUE, AQUA, ORANGE = "#2a78d6", "#1baf7a", "#eb6834"
    INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
    steps = [("Start", b["start"], BLUE, True), ("New", b["new"], AQUA, False),
             ("Expansion", b["expansion"], AQUA, False), ("Contraction", -b["contraction"], ORANGE, False),
             ("Churn", -b["churn"], ORANGE, False), ("End", b["end"], BLUE, True)]

    plt.rcParams.update({"font.size": 10, "text.color": INK, "axes.edgecolor": MUTED})
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=150)
    fig.patch.set_facecolor(SURFACE); ax.set_facecolor(SURFACE)
    cum = 0.0
    for i, (name, val, color, total) in enumerate(steps):
        bottom = 0 if total else (cum if val >= 0 else cum + val)
        height = val if total else abs(val)
        ax.bar(i, height, bottom=bottom, color=color, width=0.62, zorder=3)
        if not total and i > 0:
            ax.plot([i - 1 + 0.31, i - 0.31], [cum, cum], color=MUTED, lw=0.8, ls=":", zorder=2)
        top = (val if total else cum + val)
        lbl = f"${val/1e6:+.1f}M" if not total else f"${val/1e6:.1f}M"
        ax.text(i, max(bottom + height, top) + b["end"] * 0.015, lbl, ha="center",
                fontsize=9, color=INK, fontweight="bold")
        cum = val if total else cum + val

    ax.set_title("ARR Bridge", fontsize=14, fontweight="bold", loc="left", pad=26)
    ax.annotate(f"{b['t0']} → {b['t1']}   ·   GRR "
                f"{(b['start']-b['churn']-b['contraction'])/b['start']*100:.0f}%  ·  "
                f"NRR {(b['start']-b['churn']-b['contraction']+b['expansion'])/b['start']*100:.0f}%",
                xy=(0, 1), xytext=(0, 11), xycoords="axes fraction", textcoords="offset points",
                fontsize=9, color=MUTED, va="bottom")
    ax.set_xticks(range(len(steps)))
    ax.set_xticklabels([s[0] for s in steps])
    ax.yaxis.set_major_formatter(lambda v, _: f"${v/1e6:,.0f}M")
    ax.set_ylabel("Active recurring ARR", color=MUTED)
    ax.set_ylim(0, b["end"] * 1.12)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.tick_params(colors=MUTED)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    from pathlib import Path
    t1 = pd.Timestamp(date.today()).normalize()
    t0 = t1 - pd.DateOffset(years=1)
    b = arr_bridge(t0, t1)
    render_waterfall(b, Path(__file__).resolve().parents[3] / "reports" / "arr_bridge.png")
    print(f"ARR Bridge {b['t0']} -> {b['t1']} ($):\n")
    for k in ("start", "new", "expansion", "contraction", "churn", "end"):
        s = "+" if k in ("new", "expansion") else ("-" if k in ("contraction", "churn") else " ")
        print(f"  {s} {k:<12} ${b[k]:>14,.0f}")
    print(f"\n  computed end ${b['computed_end']:,.0f}  vs actual ${b['end']:,.0f}  "
          f"residual ${b['residual']:,.0f}")
    grr = (b["start"] - b["churn"] - b["contraction"]) / b["start"] * 100
    nrr = (b["start"] - b["churn"] - b["contraction"] + b["expansion"]) / b["start"] * 100
    print(f"  GRR {grr:.1f}%   NRR {nrr:.1f}%")

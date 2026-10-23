"""C-suite dashboard metrics — retention/churn trend, revenue concentration, logo flow.

Each is computed from the recurring book (reusing the ARR-bridge pairing for renewals).
Every metric is split into a ``*_data`` function that returns a JSON-ready structure and a
renderer that draws it with the validated palette, so the PNG charts and the web JSON
(see ``emit.py``) share one source of truth. Charts land in reports/.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from etl.load.db import get_engine  # noqa: E402
from etl.metrics.arr_bridge import _pairs  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "reports"
TODAY = pd.Timestamp(date.today()).normalize()
MATURITY = pd.Timedelta(days=60)

BLUE, AQUA, ORANGE, RED = "#2a78d6", "#1baf7a", "#eb6834", "#e34948"
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"


def _rec() -> pd.DataFrame:
    rec = pd.read_sql(
        "SELECT company_id, customer_name, product, region, arr_usd, start_date, end_date, cancel_date "
        "FROM fact_contracts WHERE revenue_type='recurring'", get_engine())
    for c in ("start_date", "end_date", "cancel_date"):
        rec[c] = pd.to_datetime(rec[c])
    rec["eff_end"] = rec["end_date"].where(rec["cancel_date"].isna(),
                                           rec[["end_date", "cancel_date"]].min(axis=1))
    return rec.reset_index(drop=True)


def _frame(figsize=(10, 5.2)):
    plt.rcParams.update({"font.size": 10, "text.color": INK, "axes.edgecolor": MUTED})
    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    fig.patch.set_facecolor(SURFACE); ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.tick_params(colors=MUTED)
    return fig, ax


def _title(ax, title, sub):
    ax.set_title(title, fontsize=14, fontweight="bold", loc="left", pad=26, color=INK)
    ax.annotate(sub, xy=(0, 1), xytext=(0, 11), xycoords="axes fraction",
                textcoords="offset points", fontsize=9, color=MUTED, va="bottom")


# ---------------------------------------------------------------- retention / churn trend
def retention_trend_data(rec) -> list[dict]:
    pred_of = _pairs(rec)
    succ_of = {p: s for s, p in pred_of.items()}
    renewed = set(pred_of.values())
    arr = rec["arr_usd"]
    rec = rec.assign(q=rec["eff_end"].dt.to_period("Q"))
    rows = []
    for q, g in rec.groupby("q"):
        if q.end_time >= TODAY - MATURITY:
            continue  # not yet resolved
        pred = g["arr_usd"].sum()
        ret = net = 0.0
        churn_logos = 0
        for idx in g.index:
            if idx in renewed:
                s = arr[succ_of[idx]]
                ret += min(s, arr[idx]); net += s
            else:
                churn_logos += 1
        rows.append({"q": str(q), "grr": (pred - (pred - ret)) / pred * 100,
                     "nrr": net / pred * 100 if pred else float("nan"),
                     "logo_churn": churn_logos / len(g) * 100})
    return rows


def retention_trend(rec):
    df = pd.DataFrame(retention_trend_data(rec))
    fig, ax = _frame()
    x = range(len(df))
    ax.plot(x, df["nrr"], color=AQUA, lw=2, marker="o", ms=4, label="Net retention (NRR)")
    ax.plot(x, df["grr"], color=BLUE, lw=2, marker="o", ms=4, label="Gross retention (GRR)")
    ax.axhline(100, color=MUTED, lw=0.8, ls="--")
    _title(ax, "Retention Trend", "Revenue retained from renewing cohorts, by expiry quarter")
    ax.set_xticks(list(x)); ax.set_xticklabels(df["q"], rotation=45, ha="right", fontsize=8)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    fig.tight_layout(); fig.savefig(REPORTS / "retention_trend.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- revenue concentration
def concentration_data(rec, topn=10) -> dict:
    active = rec[(rec["start_date"] <= TODAY) & (rec["eff_end"] >= TODAY)]
    by_co = active.groupby("company_id")["arr_usd"].sum().sort_values(ascending=False)
    total = float(by_co.sum())
    top = by_co.head(topn)
    return {
        "topn": topn,
        "total_usd": total,
        "n_customers": int(len(by_co)),
        "share_pct": float(top.sum() / total * 100) if total else 0.0,
        "top": [{"name": c.split("|")[0].title()[:24], "arr_usd": float(v)}
                for c, v in top.items()],
    }


def concentration(rec, topn=10):
    d = concentration_data(rec, topn)
    labels = [t["name"] for t in d["top"]][::-1]
    vals = (np.array([t["arr_usd"] for t in d["top"]]) / 1e6)[::-1]

    fig, ax = _frame(figsize=(10, 5.6))
    ax.barh(range(len(vals)), vals, color=BLUE, zorder=3)
    for i, v in enumerate(vals):
        ax.text(v, i, f" ${v:.2f}M", va="center", fontsize=8, color=INK)
    _title(ax, "Revenue Concentration",
           f"Top {topn} customers = {d['share_pct']:.0f}% of ${d['total_usd']/1e6:.0f}M active ARR  "
           f"({d['n_customers']} customers total)")
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels, fontsize=8)
    ax.xaxis.set_major_formatter(lambda v, _: f"${v:.1f}M")
    ax.grid(axis="y", linewidth=0); ax.grid(axis="x", color=GRID, linewidth=0.8)
    fig.tight_layout(); fig.savefig(REPORTS / "concentration.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- logo flow (new vs churned)
def logos_data(rec) -> list[dict]:
    pred_of = _pairs(rec)
    renewed = set(pred_of.values())
    first = rec.groupby("company_id")["start_date"].min()
    new_q = first.dt.to_period("Q").value_counts()
    # churned logo: company whose LAST contract expired (not renewed) in the past
    last_idx = rec.loc[rec.groupby("company_id")["eff_end"].idxmax()]
    churned = last_idx[(last_idx["eff_end"] < TODAY - MATURITY) & (~last_idx.index.isin(renewed))]
    churn_q = churned["eff_end"].dt.to_period("Q").value_counts()

    qs = sorted(set(new_q.index) | set(churn_q.index))
    qs = [q for q in qs if q.end_time < TODAY]
    return [{"q": str(q), "new": int(new_q.get(q, 0)), "churned": int(churn_q.get(q, 0))}
            for q in qs]


def logos(rec):
    rows = logos_data(rec)
    qs = [r["q"] for r in rows]
    new_v = [r["new"] for r in rows]
    churn_v = [-r["churned"] for r in rows]

    fig, ax = _frame()
    x = range(len(qs))
    ax.bar(x, new_v, color=AQUA, width=0.8, zorder=3, label="New logos")
    ax.bar(x, churn_v, color=ORANGE, width=0.8, zorder=3, label="Churned logos")
    ax.axhline(0, color=MUTED, lw=0.8)
    _title(ax, "Customer Logo Flow", "New vs churned customers per quarter")
    step = max(1, len(qs) // 16)
    ax.set_xticks(list(x)[::step]); ax.set_xticklabels(qs[::step], rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Customers", color=MUTED)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout(); fig.savefig(REPORTS / "logos.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- cohort retention heatmap
def cohort_retention_data(rec, min_members=5, max_off=12) -> dict:
    """Gross ARR retention by signing cohort.

    For each cohort (quarter of a company's first contract), the retained share of the
    cohort's *starting ARR* at each quarter offset. Active ARR is capped per member at
    its baseline (so expansion can't mask churn — gross, like GRR), giving a 0–100% decay
    curve instead of logo counts. Baseline = the cohort's active ARR at quarter 0.
    """
    first = rec.groupby("company_id")["start_date"].min()
    cohort = first.dt.to_period("Q")
    # per company: (start, effective end, arr) for every contract
    intervals = {c: list(zip(g["start_date"], g["eff_end"], g["arr_usd"]))
                 for c, g in rec.groupby("company_id")}

    def active_arr(member, d):
        return sum(a for s, e, a in intervals[member] if s <= d <= e)

    cohorts = sorted(c for c in cohort.unique() if (cohort == c).sum() >= min_members)
    out = []
    for c in cohorts:
        members = cohort[cohort == c].index
        baseline = {m: active_arr(m, c.end_time) for m in members}   # ARR at quarter 0
        base_total = sum(baseline.values())
        values: list[float | None] = []
        for k in range(max_off + 1):
            d = (c + k).end_time            # end of the quarter k after joining
            if d > TODAY or base_total == 0:
                values.append(None)
                continue
            retained = sum(min(active_arr(m, d), baseline[m]) for m in members)
            values.append(retained / base_total * 100)
        out.append({"cohort": str(c), "members": int(len(members)), "values": values})
    return {"offsets": list(range(max_off + 1)), "cohorts": out}


def cohort_retention(rec, min_members=5, max_off=12):
    d = cohort_retention_data(rec, min_members, max_off)
    cohorts = [c["cohort"] for c in d["cohorts"]]
    mat = np.array([[np.nan if v is None else v for v in c["values"]] for c in d["cohorts"]])

    fig, ax = _frame(figsize=(9, 6))
    ax.grid(False)
    im = ax.imshow(mat, aspect="auto", cmap="GnBu", vmin=0, vmax=100)
    for i in range(mat.shape[0]):
        for k in range(mat.shape[1]):
            if not np.isnan(mat[i, k]):
                ax.text(k, i, f"{mat[i,k]:.0f}", ha="center", va="center", fontsize=7,
                        color="white" if mat[i, k] > 55 else INK)
    _title(ax, "Cohort Retention", "% of each signing cohort's customers still active, by quarters since start")
    ax.set_xticks(d["offsets"]); ax.set_xticklabels([f"Q{k}" for k in d["offsets"]], fontsize=8)
    ax.set_yticks(range(len(cohorts))); ax.set_yticklabels(cohorts, fontsize=8)
    ax.set_xlabel("Quarters since first contract", color=MUTED)
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, format=lambda v, _: f"{v:.0f}%")
    fig.tight_layout(); fig.savefig(REPORTS / "cohort_retention.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- revenue mix by product x region
def revenue_mix_data(rec) -> dict:
    active = rec[(rec["start_date"] <= TODAY) & (rec["eff_end"] >= TODAY)]
    piv = active.groupby(["product", "region"])["arr_usd"].sum().unstack(fill_value=0)
    regions = [r for r in ["NA", "EU", "UK"] if r in piv.columns]
    rows = []
    for product, r in piv.iterrows():
        row = {"product": str(product), "total_usd": float(r.sum())}
        for reg in regions:
            row[reg] = float(r[reg])
        rows.append(row)
    return {"regions": regions, "rows": rows, "total_usd": float(piv.to_numpy().sum())}


def revenue_mix(rec):
    d = revenue_mix_data(rec)
    region_color = {"NA": BLUE, "EU": AQUA, "UK": ORANGE}
    products = [r["product"] for r in d["rows"]]

    fig, ax = _frame(figsize=(8, 5))
    bottom = np.zeros(len(products))
    for reg in d["regions"]:
        vals = np.array([r.get(reg, 0.0) for r in d["rows"]]) / 1e6
        ax.bar(products, vals, bottom=bottom, color=region_color[reg], label=reg, width=0.6, zorder=3)
        bottom += vals
    for i, tot in enumerate(bottom):
        ax.text(i, tot, f" ${tot:.1f}M", ha="center", va="bottom", fontsize=9, color=INK, fontweight="bold")
    _title(ax, "Active ARR by Product & Region", f"Total active recurring ARR ${bottom.sum():.1f}M")
    ax.set_ylabel("Active ARR", color=MUTED)
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:.0f}M")
    ax.legend(frameon=False, fontsize=9, title="Region")
    fig.tight_layout(); fig.savefig(REPORTS / "revenue_mix.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- new bookings & win-rate
def bookings_winrate_data() -> list[dict]:
    opp = pd.read_sql("SELECT status, close_date, amount_usd FROM fact_opportunity "
                      "WHERE status IN ('won','lost')", get_engine())
    opp["close_date"] = pd.to_datetime(opp["close_date"])
    opp = opp[opp["close_date"].notna()]
    opp["q"] = opp["close_date"].dt.to_period("Q")
    rows = []
    for q, g in opp.groupby("q"):
        if q.end_time >= TODAY:
            continue
        rows.append({"q": str(q),
                     "bookings_usd": float(g.loc[g["status"] == "won", "amount_usd"].sum()),
                     "winrate_pct": float((g["status"] == "won").mean() * 100)})
    return rows


def bookings_winrate():
    rows = bookings_winrate_data()
    keep = [r["q"] for r in rows]
    bookings = np.array([r["bookings_usd"] for r in rows]) / 1e6
    winrate = np.array([r["winrate_pct"] for r in rows])
    x = range(len(keep))

    plt.rcParams.update({"font.size": 10, "text.color": INK, "axes.edgecolor": MUTED})
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), dpi=150, sharex=True,
                                   gridspec_kw={"height_ratios": [2, 1]})
    for ax in (ax1, ax2):
        ax.set_facecolor(SURFACE)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0); ax.tick_params(colors=MUTED)
    fig.patch.set_facecolor(SURFACE)
    ax1.bar(x, bookings, color=BLUE, width=0.8, zorder=3)
    ax1.set_title("New Bookings & Win Rate", fontsize=14, fontweight="bold", loc="left", pad=26)
    ax1.annotate("Won-deal bookings and win rate by close quarter", xy=(0, 1), xytext=(0, 11),
                 xycoords="axes fraction", textcoords="offset points", fontsize=9, color=MUTED, va="bottom")
    ax1.set_ylabel("Bookings", color=MUTED); ax1.yaxis.set_major_formatter(lambda v, _: f"${v:.1f}M")
    ax2.plot(x, winrate, color=AQUA, lw=2, marker="o", ms=4)
    ax2.set_ylabel("Win rate", color=MUTED); ax2.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax2.set_ylim(0, max(winrate.max() * 1.15, 50))
    ax2.set_xticks(list(x)); ax2.set_xticklabels(keep, rotation=45, ha="right", fontsize=8)
    fig.tight_layout(); fig.savefig(REPORTS / "bookings_winrate.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    rec = _rec()
    retention_trend(rec)
    concentration(rec)
    logos(rec)
    cohort_retention(rec)
    revenue_mix(rec)
    bookings_winrate()
    print("wrote 6 dashboard charts to reports/")

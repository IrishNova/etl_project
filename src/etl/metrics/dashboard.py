"""C-suite dashboard metrics — retention/churn trend, revenue concentration, logo flow.

Each is computed from the recurring book (reusing the ARR-bridge pairing for renewals) and
rendered with the validated palette. Charts land in reports/.
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
def retention_trend(rec):
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
        rows.append({"q": str(q), "GRR": (pred - (pred - ret)) / pred * 100,
                     "NRR": net / pred * 100 if pred else np.nan,
                     "logo_churn": churn_logos / len(g) * 100})
    df = pd.DataFrame(rows)

    fig, ax = _frame()
    x = range(len(df))
    ax.plot(x, df["NRR"], color=AQUA, lw=2, marker="o", ms=4, label="Net retention (NRR)")
    ax.plot(x, df["GRR"], color=BLUE, lw=2, marker="o", ms=4, label="Gross retention (GRR)")
    ax.axhline(100, color=MUTED, lw=0.8, ls="--")
    _title(ax, "Retention Trend", "Revenue retained from renewing cohorts, by expiry quarter")
    ax.set_xticks(list(x)); ax.set_xticklabels(df["q"], rotation=45, ha="right", fontsize=8)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    fig.tight_layout(); fig.savefig(REPORTS / "retention_trend.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- revenue concentration
def concentration(rec, topn=10):
    active = rec[(rec["start_date"] <= TODAY) & (rec["eff_end"] >= TODAY)]
    by_co = active.groupby("company_id")["arr_usd"].sum().sort_values(ascending=False)
    total = by_co.sum()
    top = by_co.head(topn)
    share = top.sum() / total * 100
    labels = [c.split("|")[0].title()[:24] for c in top.index][::-1]
    vals = (top.to_numpy() / 1e6)[::-1]

    fig, ax = _frame(figsize=(10, 5.6))
    ax.barh(range(len(vals)), vals, color=BLUE, zorder=3)
    for i, v in enumerate(vals):
        ax.text(v, i, f" ${v:.2f}M", va="center", fontsize=8, color=INK)
    _title(ax, "Revenue Concentration",
           f"Top {topn} customers = {share:.0f}% of ${total/1e6:.0f}M active ARR  "
           f"({len(by_co)} customers total)")
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels, fontsize=8)
    ax.xaxis.set_major_formatter(lambda v, _: f"${v:.1f}M")
    ax.grid(axis="y", linewidth=0); ax.grid(axis="x", color=GRID, linewidth=0.8)
    fig.tight_layout(); fig.savefig(REPORTS / "concentration.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- logo flow (new vs churned)
def logos(rec):
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
    new_v = [int(new_q.get(q, 0)) for q in qs]
    churn_v = [-int(churn_q.get(q, 0)) for q in qs]

    fig, ax = _frame()
    x = range(len(qs))
    ax.bar(x, new_v, color=AQUA, width=0.8, zorder=3, label="New logos")
    ax.bar(x, churn_v, color=ORANGE, width=0.8, zorder=3, label="Churned logos")
    ax.axhline(0, color=MUTED, lw=0.8)
    _title(ax, "Customer Logo Flow", "New vs churned customers per quarter")
    step = max(1, len(qs) // 16)
    ax.set_xticks(list(x)[::step]); ax.set_xticklabels([str(q) for q in qs][::step], rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Customers", color=MUTED)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout(); fig.savefig(REPORTS / "logos.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- cohort retention heatmap
def cohort_retention(rec, min_members=5, max_off=12):
    first = rec.groupby("company_id")["start_date"].min()
    cohort = first.dt.to_period("Q")
    intervals = {c: list(zip(g["start_date"], g["eff_end"]))
                 for c, g in rec.groupby("company_id")}

    cohorts = sorted(c for c in cohort.unique() if (cohort == c).sum() >= min_members)
    mat = np.full((len(cohorts), max_off + 1), np.nan)
    for i, c in enumerate(cohorts):
        members = cohort[cohort == c].index
        for k in range(max_off + 1):
            d = (c + k).end_time            # end of the quarter k after joining
            if d > TODAY:
                break
            active = sum(any(s <= d <= e for s, e in intervals[m]) for m in members)
            mat[i, k] = active / len(members) * 100

    fig, ax = _frame(figsize=(9, 6))
    ax.grid(False)
    im = ax.imshow(mat, aspect="auto", cmap="GnBu", vmin=0, vmax=100)
    for i in range(mat.shape[0]):
        for k in range(mat.shape[1]):
            if not np.isnan(mat[i, k]):
                ax.text(k, i, f"{mat[i,k]:.0f}", ha="center", va="center", fontsize=7,
                        color="white" if mat[i, k] > 55 else INK)
    _title(ax, "Cohort Retention", "% of each signing cohort's customers still active, by quarters since start")
    ax.set_xticks(range(max_off + 1)); ax.set_xticklabels([f"Q{k}" for k in range(max_off + 1)], fontsize=8)
    ax.set_yticks(range(len(cohorts))); ax.set_yticklabels([str(c) for c in cohorts], fontsize=8)
    ax.set_xlabel("Quarters since first contract", color=MUTED)
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, format=lambda v, _: f"{v:.0f}%")
    fig.tight_layout(); fig.savefig(REPORTS / "cohort_retention.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- revenue mix by product x region
def revenue_mix(rec):
    active = rec[(rec["start_date"] <= TODAY) & (rec["eff_end"] >= TODAY)]
    piv = (active.groupby(["product", "region"])["arr_usd"].sum().unstack(fill_value=0) / 1e6)
    region_color = {"NA": BLUE, "EU": AQUA, "UK": ORANGE}

    fig, ax = _frame(figsize=(8, 5))
    bottom = np.zeros(len(piv))
    for reg in [r for r in ["NA", "EU", "UK"] if r in piv.columns]:
        ax.bar(piv.index, piv[reg], bottom=bottom, color=region_color[reg], label=reg, width=0.6, zorder=3)
        bottom += piv[reg].to_numpy()
    for i, tot in enumerate(bottom):
        ax.text(i, tot, f" ${tot:.1f}M", ha="center", va="bottom", fontsize=9, color=INK, fontweight="bold")
    _title(ax, "Active ARR by Product & Region", f"Total active recurring ARR ${bottom.sum():.1f}M")
    ax.set_ylabel("Active ARR", color=MUTED)
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:.0f}M")
    ax.legend(frameon=False, fontsize=9, title="Region")
    fig.tight_layout(); fig.savefig(REPORTS / "revenue_mix.png", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- new bookings & win-rate
def bookings_winrate():
    opp = pd.read_sql("SELECT status, close_date, amount_usd FROM fact_opportunity "
                      "WHERE status IN ('won','lost')", get_engine())
    opp["close_date"] = pd.to_datetime(opp["close_date"])
    opp = opp[opp["close_date"].notna()]
    opp["q"] = opp["close_date"].dt.to_period("Q")
    g = opp.groupby("q")
    bookings = g.apply(lambda d: d.loc[d["status"] == "won", "amount_usd"].sum(), include_groups=False) / 1e6
    winrate = g.apply(lambda d: (d["status"] == "won").mean() * 100, include_groups=False)
    keep = [q for q in bookings.index if q.end_time < TODAY]
    bookings, winrate = bookings[keep], winrate[keep]
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
    ax1.bar(x, bookings.to_numpy(), color=BLUE, width=0.8, zorder=3)
    ax1.set_title("New Bookings & Win Rate", fontsize=14, fontweight="bold", loc="left", pad=26)
    ax1.annotate("Won-deal bookings and win rate by close quarter", xy=(0, 1), xytext=(0, 11),
                 xycoords="axes fraction", textcoords="offset points", fontsize=9, color=MUTED, va="bottom")
    ax1.set_ylabel("Bookings", color=MUTED); ax1.yaxis.set_major_formatter(lambda v, _: f"${v:.1f}M")
    ax2.plot(x, winrate.to_numpy(), color=AQUA, lw=2, marker="o", ms=4)
    ax2.set_ylabel("Win rate", color=MUTED); ax2.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax2.set_ylim(0, max(winrate.max() * 1.15, 50))
    ax2.set_xticks(list(x)); ax2.set_xticklabels([str(q) for q in keep], rotation=45, ha="right", fontsize=8)
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

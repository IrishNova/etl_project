"""Render the 3-layer revenue-projection stacked bar (matplotlib) + emit JSON for Flask.

Layers, ranked by certainty (fill texture encodes it, so it survives grayscale/CVD):
  Guaranteed (contracted)   — solid blue      — certain
  Expected renewals (GRR)   — hatched orange   — projected
  New business (net-new)    — dotted aqua      — most speculative

Plus the backtest-calibrated P10-P90 band on the total.

Writes reports/projection.png and data/processed/projection_series.json (what Flask serves).
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from etl.metrics.band import run_mc  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PNG = ROOT / "reports" / "projection.png"
JSON = ROOT / "data" / "processed" / "projection_series.json"

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"


def emit_json(out: pd.DataFrame) -> None:
    records = [
        {"week_start": r.week_start.isoformat(),
         "guaranteed": round(r.guaranteed, 2),
         "expected_renewals": round(r.renewals_p50, 2),
         "new_business": round(r.newbiz_p50, 2),
         "total_p10": round(r.total_p10, 2),
         "total_p50": round(r.total_p50, 2),
         "total_p90": round(r.total_p90, 2)}
        for r in out.itertuples()
    ]
    JSON.parent.mkdir(parents=True, exist_ok=True)
    JSON.write_text(json.dumps({"weekly": records}, indent=2))


def render(out: pd.DataFrame, warning: str | None = None) -> None:
    plt.rcParams.update({"font.size": 10, "hatch.linewidth": 0.6,
                         "axes.edgecolor": MUTED, "text.color": INK})
    x = pd.to_datetime(out["week_start"])
    w = 5.5
    g = out["guaranteed"].to_numpy()
    r = out["renewals_p50"].to_numpy()
    n = out["newbiz_p50"].to_numpy()

    fig, ax = plt.subplots(figsize=(12, 5.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    b1 = ax.bar(x, g, width=w, color=BLUE, edgecolor=SURFACE, linewidth=0.2, zorder=2)
    b2 = ax.bar(x, r, width=w, bottom=g, facecolor=ORANGE, alpha=0.55, hatch="////",
                edgecolor=ORANGE, linewidth=0.0, zorder=2)
    b3 = ax.bar(x, n, width=w, bottom=g + r, facecolor=AQUA, alpha=0.5, hatch="....",
                edgecolor=AQUA, linewidth=0.0, zorder=2)
    fb = ax.fill_between(x, out["total_p10"], out["total_p90"], color=MUTED, alpha=0.16,
                         step="mid", linewidth=0, zorder=3)

    ax.set_title("3-Year Weekly Revenue Projection", fontsize=14, fontweight="bold",
                 loc="left", color=INK, pad=30)
    ax.annotate("Contracted floor + expected renewals + new business, with a "
                "backtest-calibrated uncertainty band", xy=(0, 1), xytext=(0, 13),
                xycoords="axes fraction", textcoords="offset points",
                fontsize=9, color=MUTED, va="bottom")
    if warning:
        ax.annotate(warning, xy=(0, 0.965), xycoords="axes fraction", fontsize=9,
                    color="#b45309", fontweight="bold")  # amber caution

    ax.yaxis.set_major_formatter(lambda v, _: f"${v/1000:,.0f}k")
    ax.set_ylabel("Recognized revenue / week", color=MUTED)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    ax.margins(x=0.01)
    ax.set_ylim(bottom=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.tick_params(colors=MUTED)
    ax.legend([b1, b2, b3, fb],
              ["Guaranteed (contracted)", "Expected renewals (projected)",
               "New business (speculative)", "P10–P90 (uncertainty)"],
              loc="upper right", frameon=False, fontsize=9, ncol=2)

    fig.tight_layout()
    PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(PNG, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    from etl.metrics.pipeline_forecast import pipeline_anomaly

    out, _, _ = run_mc()
    emit_json(out)
    a = pipeline_anomaly()
    warn = (f"⚠ Pipeline {a['ratio']:.1f}x normal — near-term elevated, treat with caution"
            if a["level"] != "NORMAL" else None)
    render(out, warning=warn)
    print(f"wrote {PNG.relative_to(ROOT)}  and  {JSON.relative_to(ROOT)}")
    print(f"pipeline anomaly: {a['level']}  (now {a['now']} open, typical ~{a['median']}, max {a['max']})")

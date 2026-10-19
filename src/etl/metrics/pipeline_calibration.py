"""Pipeline model, step 1 — calibrate win probability by stage from history.

The CRM's stated probability is an untested default; we measure the TRUE win rate per
stage empirically. "Reached stage k" comes from the stage-change log (not the current
stage, which for a resolved deal is just Won/Lost), and only RESOLVED deals count in the
rate — open deals that reached stage k are right-censored and reported alongside, never
silently dropped (dropping them would inflate the rate: survivorship).

  empirical P(win | reached stage k) = won / (won + lost)  among deals that ever reached k

Compared against what the CRM *claims* for deals at that stage, this is the calibration
the forecast will use instead of the CRM field.
"""

from __future__ import annotations

import pandas as pd

from etl.load.db import get_engine

RANK = {"Qualify": 1, "Proposal": 2, "Negotiate": 3, "Contract": 4}
RANK_NAME = {1: "Qualify", 2: "Proposal", 3: "Negotiate", 4: "Contract"}


def _load():
    eng = get_engine()
    opp = pd.read_sql(
        "SELECT opportunity_id, status, stage, stage_rank, crm_probability FROM fact_opportunity", eng)
    hist = pd.read_sql("SELECT opportunity_id, to_stage FROM pipeline_stage_history", eng)
    return opp, hist


def stage_win_rates() -> pd.DataFrame:
    opp, hist = _load()

    # Max open-stage rank each opp ever reached (from the event log).
    hist["rank"] = hist["to_stage"].map(RANK)
    reached = hist.dropna(subset=["rank"]).groupby("opportunity_id")["rank"].max()
    opp = opp.join(reached.rename("max_reached"), on="opportunity_id")

    resolved = opp[opp["status"].isin(["won", "lost"])]
    rows = []
    for k in (1, 2, 3, 4):
        cohort = resolved[resolved["max_reached"] >= k]
        n = len(cohort)
        won = int((cohort["status"] == "won").sum())
        open_at_k = opp[(opp["status"] == "open") & (opp["max_reached"] >= k)]
        # what the CRM claims for OPEN deals currently sitting at this stage
        crm = opp[(opp["status"] == "open") & (opp["stage_rank"] == k)]["crm_probability"]
        rows.append({
            "stage": RANK_NAME[k], "rank": k,
            "resolved_reached": n, "won": won,
            "empirical_win_rate": won / n if n else float("nan"),
            "crm_stated": crm.median() if len(crm) else float("nan"),
            "open_censored": len(open_at_k),
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = stage_win_rates()
    show = df.copy()
    show["empirical_win_rate"] = (show["empirical_win_rate"] * 100).round(1)
    show["crm_stated"] = (show["crm_stated"] * 100).round(0)
    print("Empirical stage win-rate vs the CRM's stated probability:\n")
    print(show[["stage", "rank", "resolved_reached", "won", "empirical_win_rate",
                "crm_stated", "open_censored"]].to_string(index=False))
    print("\nGap (CRM stated - empirical) = the miscalibration the forecast corrects.")

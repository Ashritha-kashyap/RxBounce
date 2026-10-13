"""Step 6 - Turn model outputs into the tables the pharmacy uses every day."""
import math
import pandas as pd

import config
from src.simulate import policy_levels
from src.train_risk import score_today

P, R = config.PROCESSED, config.REPORTS


def run():
    as_of = pd.Timestamp(config.AS_OF)
    drugs = pd.read_csv(P / "drugs.csv").set_index("drug_id")
    ds = pd.read_csv(P / "drug_supplier.csv").set_index("drug_id")
    soh = pd.read_csv(P / "stock_on_hand.csv").set_index("drug_id")
    fc = pd.read_csv(P / "forecasts.csv")
    nxt = fc[fc.is_future == 1].set_index("drug_id")
    risk = score_today().set_index("drug_id").stockout_risk

    rows = []
    for drug in ds.index:
        abc = drugs.at[drug, "abc_class"]
        mu = nxt.at[drug, "predicted_qty"] / 7
        sigma = max(nxt.at[drug, "sigma_weekly"] / math.sqrt(7), math.sqrt(mu))
        pack = ds.at[drug, "min_order_qty"]
        ss, rop, s_level = policy_levels(mu, sigma, ds.at[drug, "lead_time_mean"], ds.at[drug, "lead_time_sd"],
                                         config.Z_BY_ABC[abc], config.REVIEW_DAYS_BY_ABC[abc], pack,
                                         7 / len(config.REVIEW_WEEKDAYS_BY_ABC[abc]))
        position = soh.at[drug, "qty_on_hand"] + soh.at[drug, "on_order_qty"]
        qty = int(math.ceil(max(s_level - position, 0) / pack) * pack) if position <= rop else 0
        p = float(risk.get(drug, 0))
        rows.append({"drug_id": drug, "avg_daily_forecast": round(mu, 3), "safety_stock": round(ss, 2),
                     "reorder_point": max(rop, 0), "order_up_to": s_level, "suggested_order_qty": qty,
                     "stockout_risk": p,
                     "risk_band": "High" if p >= config.RISK_THRESHOLD else ("Medium" if p >= 0.2 else "Low"),
                     "updated_at": as_of})
    policy = pd.DataFrame(rows)
    policy.to_csv(P / "reorder_policy.csv", index=False)

    alerts = []
    for r in policy.itertuples():
        name = drugs.at[r.drug_id, "drug_name"]
        if r.risk_band == "High":
            alerts.append((r.drug_id, "Stockout risk", "High", f"{name}: {r.stockout_risk:.0%} chance of running short in 7 days"))
        if r.suggested_order_qty > 0:
            alerts.append((r.drug_id, "Reorder", "Medium", f"{name}: order {r.suggested_order_qty} units"))
    b = pd.read_csv(P / "inventory_batches.csv", parse_dates=["expiry_date"])
    b["days_left"] = (b.expiry_date - as_of).dt.days
    for r in b[b.days_left <= config.NEAR_EXPIRY_DAYS].itertuples():
        name = drugs.at[r.drug_id, "drug_name"]
        if r.days_left <= 0:
            alerts.append((r.drug_id, "Expired stock", "High", f"{name}: lot {r.lot_no} expired, remove {r.qty_remaining} units"))
        else:
            alerts.append((r.drug_id, "Near expiry", "Low", f"{name}: lot {r.lot_no} expires in {r.days_left} days"))
    alerts = pd.DataFrame(alerts, columns=["drug_id", "alert_type", "severity", "message"])
    alerts.insert(0, "alert_id", range(1, len(alerts) + 1))
    alerts["created_at"] = as_of
    alerts["is_resolved"] = 0
    alerts.to_csv(P / "alerts.csv", index=False)

    mm = []
    for f in ["forecast_metrics.csv", "risk_metrics.csv"]:
        m = pd.read_csv(R / f)
        for c in [c for c in m.columns if c not in ("model", "task", "is_selected")]:
            mm.append(m[["task", "model", "is_selected"]].assign(metric=c, value=m[c]))
    pd.concat(mm).to_csv(P / "model_metrics.csv", index=False)

    sim = pd.read_csv(R / "simulation_results.csv")
    sim.melt(id_vars="scenario", var_name="metric", value_name="value").to_csv(P / "simulation_results.csv", index=False)
    pd.read_csv(R / "simulation_breakdown.csv").to_csv(P / "simulation_breakdown.csv", index=False)
    pd.read_csv(R / "ablation.csv").to_csv(P / "model_ablation.csv", index=False)
    pd.read_csv(R / "sensitivity.csv").to_csv(P / "sensitivity_results.csv", index=False)
    fi = pd.concat([pd.read_csv(R / "risk_shap.csv").assign(model="Stockout risk"),
                    pd.read_csv(R / "forecast_feature_importance.csv").assign(model="Demand forecast",
                                                                             method="split importance")])
    fi.to_csv(P / "feature_importance.csv", index=False)
    print(f"[decisions] reorder suggestions={int((policy.suggested_order_qty > 0).sum())}, "
          f"high-risk drugs={int((policy.risk_band == 'High').sum())}, alerts={len(alerts)}")


if __name__ == "__main__":
    run()

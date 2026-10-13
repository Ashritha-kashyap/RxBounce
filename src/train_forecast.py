"""Step 3 - Weekly demand forecasting per drug.

Target = TRUE demand (quantity requested on prescriptions), not just what was sold.
Forecasting only on sales would learn the stockouts and keep repeating them.
Trained on weeks before go-live, tested on the weeks after it.
"""
import joblib
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.ensemble import RandomForestRegressor

import config

FEATURES = ["lag_1", "lag_2", "lag_3", "lag_4", "roll_mean_4", "roll_mean_8", "roll_std_8", "nonzero_share_8",
            "week_of_year", "month", "holidays_in_week", "abc_code", "subcat_code", "log_unit_cost",
            "lead_time_mean"]
START = pd.Timestamp(config.DATA_START)
LAST_WEEK = (pd.Timestamp(config.DATA_END) - START).days // 7
TEST_START_WEEK = -(-(pd.Timestamp(config.GO_LIVE) - START).days // 7)
TRAIN_WEEKS = (8, TEST_START_WEEK - 2)


def weekly_panel():
    P = config.PROCESSED
    lines = pd.read_csv(P / "demand_lines.csv", parse_dates=["date"])
    drugs = pd.read_csv(P / "drugs.csv")
    ds = pd.read_csv(P / "drug_supplier.csv")
    hol = pd.read_csv(P / "holidays.csv", parse_dates=["holiday_date"])
    stocked = drugs[drugs.drug_id.isin(ds.drug_id)]
    lines = lines[lines.drug_id.isin(stocked.drug_id)]
    lines["week"] = (lines.date - START).dt.days // 7
    wk = lines.groupby(["drug_id", "week"]).qty.sum()
    idx = pd.MultiIndex.from_product([stocked.drug_id, range(LAST_WEEK + 2)], names=["drug_id", "week"])
    panel = wk.reindex(idx, fill_value=0).rename("demand").reset_index().astype({"demand": float})
    panel.loc[panel.week == LAST_WEEK + 1, "demand"] = np.nan          # next week (future)
    panel["week_start"] = START + pd.to_timedelta(panel.week * 7, unit="D")

    g = panel.groupby("drug_id").demand
    for k in (1, 2, 3, 4):
        panel[f"lag_{k}"] = g.shift(k)
    shifted = g.shift(1)
    grp = shifted.groupby(panel.drug_id)
    panel["roll_mean_4"] = grp.rolling(4, min_periods=1).mean().reset_index(level=0, drop=True)
    panel["roll_mean_8"] = grp.rolling(8, min_periods=1).mean().reset_index(level=0, drop=True)
    panel["roll_std_8"] = grp.rolling(8, min_periods=2).std().reset_index(level=0, drop=True).fillna(0)
    panel["nonzero_share_8"] = ((shifted > 0).astype(float).where(shifted.notna())
                                .groupby(panel.drug_id).rolling(8, min_periods=1).mean()
                                .reset_index(level=0, drop=True))
    panel["week_of_year"] = panel.week_start.dt.isocalendar().week.astype(int)
    panel["month"] = panel.week_start.dt.month
    hol_week = ((hol.holiday_date - START).dt.days // 7).value_counts()
    panel["holidays_in_week"] = panel.week.map(hol_week).fillna(0)
    meta = stocked.set_index("drug_id")
    panel["abc_code"] = panel.drug_id.map(meta.abc_class.map({"A": 0, "B": 1, "C": 2}))
    panel["subcat_code"] = panel.drug_id.map(meta.subcat.astype("category").cat.codes)
    panel["log_unit_cost"] = np.log1p(panel.drug_id.map(meta.unit_cost))
    panel["lead_time_mean"] = panel.drug_id.map(ds.set_index("drug_id").lead_time_mean)
    return panel


def metrics(y, p):
    y, p = np.asarray(y), np.asarray(p)
    return {"MAE": float(np.mean(np.abs(y - p))), "RMSE": float(np.sqrt(np.mean((y - p) ** 2))),
            "WAPE": float(np.sum(np.abs(y - p)) / max(np.sum(y), 1))}


def train():
    panel = weekly_panel()
    train = panel[panel.week.between(*TRAIN_WEEKS)]
    test = panel[panel.week.between(TEST_START_WEEK, LAST_WEEK - 1)]     # last week is partial
    X, y = train[FEATURES], train.demand

    models = {
        "LightGBM (Tweedie)": lgb.LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3, n_estimators=400,
                                                learning_rate=0.03, num_leaves=31, min_child_samples=20,
                                                subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                                                random_state=config.SEED, verbose=-1),
        "Random Forest": RandomForestRegressor(n_estimators=200, min_samples_leaf=5, n_jobs=-1,
                                               random_state=config.SEED),
    }
    rows = [{"model": "Naive (last week)", **metrics(test.demand, test.lag_1.fillna(0))},
            {"model": "Moving average (4 weeks)", **metrics(test.demand, test.roll_mean_4.fillna(0))}]
    fitted = {}
    for name, m in models.items():
        m.fit(X, y)
        fitted[name] = m
        rows.append({"model": name, **metrics(test.demand, np.clip(m.predict(test[FEATURES]), 0, None))})
    res = pd.DataFrame(rows).sort_values("WAPE").reset_index(drop=True)
    best_name = next(n for n in res.model if n in fitted)
    res["is_selected"] = (res.model == best_name).astype(int)
    res["task"] = "Demand forecasting"
    print("[forecast] accuracy on weeks after go-live:")
    print(res[["model", "MAE", "RMSE", "WAPE"]].round(3).to_string(index=False))

    best = fitted[best_name]
    version = f"forecast-{best_name.split()[0].lower()}-v1"
    joblib.dump({"model": best, "features": FEATURES, "name": best_name, "version": version},
                config.MODELS / "forecast_model.joblib")
    res.to_csv(config.REPORTS / "forecast_metrics.csv", index=False)

    scored = panel[panel.week >= 4].copy()
    scored["predicted_qty"] = np.clip(best.predict(scored[FEATURES]), 0, None).round(2)
    scored["is_future"] = scored.demand.isna().astype(int)
    scored["model_version"] = version
    scored["sigma_weekly"] = scored.roll_std_8.round(3)
    out = scored.rename(columns={"demand": "actual_qty"})[
        ["drug_id", "week_start", "actual_qty", "predicted_qty", "sigma_weekly", "is_future", "model_version"]]
    out.to_csv(config.PROCESSED / "forecasts.csv", index=False)

    imp = pd.DataFrame({"feature": FEATURES, "importance": best.feature_importances_})
    imp.sort_values("importance", ascending=False).to_csv(config.REPORTS / "forecast_feature_importance.csv", index=False)
    return res


if __name__ == "__main__":
    train()

"""Step 4 - 7-day stockout risk classifier.

For every drug at the end of every day: will it run short (a bounce or an emergency purchase)
in the next 7 days?  Trained on the old-policy history before go-live, tested after it.
"""
import joblib
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, average_precision_score, precision_score, recall_score, f1_score

import config

FEATURES = ["closing_qty", "on_order_qty", "demand_7d", "demand_28d", "days_of_cover", "position_cover",
            "demand_trend", "unmet_28d", "emergency_28d", "days_since_receipt", "lead_time_mean", "lead_time_sd",
            "abc_code", "log_unit_cost", "day_of_week", "month", "holidays_next_7"]
HORIZON = 7


def build_panel(daily_file="daily_stock_baseline.csv", tail_days=None):
    P = config.PROCESSED
    daily = pd.read_csv(P / daily_file, parse_dates=["stock_date"])
    if tail_days:
        daily = daily[daily.stock_date > daily.stock_date.max() - pd.Timedelta(days=tail_days)]
    lines = pd.read_csv(P / "demand_lines.csv", parse_dates=["date"])
    drugs = pd.read_csv(P / "drugs.csv").set_index("drug_id")
    ds = pd.read_csv(P / "drug_supplier.csv").set_index("drug_id")
    hol = pd.read_csv(P / "holidays.csv", parse_dates=["holiday_date"])

    dem = lines.groupby(["drug_id", "date"]).qty.sum().rename("demand")
    df = daily.merge(dem, left_on=["drug_id", "stock_date"], right_index=True, how="left").fillna({"demand": 0})
    df = df.sort_values(["drug_id", "stock_date"]).reset_index(drop=True)
    g = df.groupby("drug_id", sort=False)

    def roll(col, w):
        return g[col].rolling(w, min_periods=1).sum().reset_index(level=0, drop=True)

    df["demand_7d"] = roll("demand", 7)
    df["demand_28d"] = roll("demand", 28)
    df["unmet_28d"] = roll("unmet_qty", 28)
    df["emergency_28d"] = roll("emergency_qty", 28)
    daily_rate = df.demand_28d / 28 + 0.01
    df["days_of_cover"] = (df.closing_qty / daily_rate).clip(upper=365)
    df["position_cover"] = ((df.closing_qty + df.on_order_qty) / daily_rate).clip(upper=365)
    df["demand_trend"] = df.demand_7d / (df.demand_28d / 4 + 0.1)
    rec_day = df.stock_date.where(df.received_qty > 0)
    df["days_since_receipt"] = (df.stock_date - rec_day.groupby(df.drug_id).ffill()).dt.days.fillna(60).clip(upper=60)
    df["lead_time_mean"] = df.drug_id.map(ds.lead_time_mean)
    df["lead_time_sd"] = df.drug_id.map(ds.lead_time_sd)
    df["abc_code"] = df.drug_id.map(drugs.abc_class.map({"A": 0, "B": 1, "C": 2}))
    df["log_unit_cost"] = np.log1p(df.drug_id.map(drugs.unit_cost))
    df["day_of_week"] = df.stock_date.dt.weekday
    df["month"] = df.stock_date.dt.month
    hd = set(hol.holiday_date)
    days = pd.date_range(df.stock_date.min(), df.stock_date.max() + pd.Timedelta(days=7))
    nxt = {d: sum((d + pd.Timedelta(days=k)) in hd for k in range(1, 8)) for d in days}
    df["holidays_next_7"] = df.stock_date.map(nxt)

    short = ((df.unmet_qty > 0) | (df.emergency_qty > 0)).astype(int)
    sg = short.groupby(df.drug_id)
    fut = sum(sg.shift(-k) for k in range(1, HORIZON + 1))
    df["label"] = (fut > 0).astype(float).where(fut.notna())
    return df


def evaluate(y, p, thr=config.RISK_THRESHOLD):
    pred = (p >= thr).astype(int)
    return {"ROC_AUC": roc_auc_score(y, p), "PR_AUC": average_precision_score(y, p),
            "Precision": precision_score(y, pred, zero_division=0), "Recall": recall_score(y, pred),
            "F1": f1_score(y, pred)}


def train():
    df = build_panel()
    lab = df[df.label.notna()]
    go = pd.Timestamp(config.GO_LIVE)
    train = lab[lab.stock_date < go - pd.Timedelta(days=HORIZON)]
    test = lab[lab.stock_date >= go]
    Xtr, ytr, Xte, yte = train[FEATURES], train.label.astype(int), test[FEATURES], test.label.astype(int)
    pos_w = (ytr == 0).sum() / max((ytr == 1).sum(), 1)
    print(f"[risk] train rows={len(train):,} test rows={len(test):,} positive share={ytr.mean():.1%}")

    sub = train.sample(min(80000, len(train)), random_state=config.SEED)
    models = {
        "Logistic Regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced")),
        "Random Forest": RandomForestClassifier(n_estimators=200, max_depth=12, min_samples_leaf=20,
                                                class_weight="balanced", n_jobs=-1, random_state=config.SEED),
        "LightGBM": lgb.LGBMClassifier(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=50,
                                       subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                                       scale_pos_weight=pos_w, random_state=config.SEED, verbose=-1),
    }
    rows, fitted = [], {}
    for name, m in models.items():
        if name == "LightGBM":
            m.fit(Xtr, ytr)
        else:
            m.fit(sub[FEATURES], sub.label.astype(int))
        fitted[name] = m
        rows.append({"model": name, **evaluate(yte, m.predict_proba(Xte)[:, 1])})
    res = pd.DataFrame(rows).sort_values("PR_AUC", ascending=False).reset_index(drop=True)
    best_name = res.model.iat[0]
    res["is_selected"] = (res.model == best_name).astype(int)
    res["task"] = "Stockout risk (7 days)"
    print(res.round(3).to_string(index=False))
    best = fitted[best_name]
    version = f"risk-{best_name.split()[0].lower()}-v1"
    joblib.dump({"model": best, "features": FEATURES, "name": best_name, "version": version},
                config.MODELS / "risk_model.joblib")
    res.to_csv(config.REPORTS / "risk_metrics.csv", index=False)

    try:
        import shap
        sample = Xte.sample(min(3000, len(Xte)), random_state=config.SEED)
        if hasattr(best, "steps"):
            vals = np.abs(best[-1].coef_[0] * best[0].transform(sample)).mean(axis=0)
        else:
            sv = shap.TreeExplainer(best).shap_values(sample)
            sv = sv[1] if isinstance(sv, list) else sv
            sv = sv[..., 1] if sv.ndim == 3 else sv
            vals = np.abs(sv).mean(axis=0)
        method = "mean |SHAP value|"
    except Exception:
        vals, method = getattr(best, "feature_importances_", np.zeros(len(FEATURES))), "split importance"
    pd.DataFrame({"feature": FEATURES, "importance": vals, "method": method}).sort_values(
        "importance", ascending=False).to_csv(config.REPORTS / "risk_shap.csv", index=False)
    return res


def score_today():
    """Score every drug on the last day of the live stock history."""
    bundle = joblib.load(config.MODELS / "risk_model.joblib")
    df = build_panel("daily_stock.csv", tail_days=45)
    last = df[df.stock_date == df.stock_date.max()].copy()
    last["stockout_risk"] = bundle["model"].predict_proba(last[bundle["features"]])[:, 1].round(4)
    return last[["drug_id", "stockout_risk"]]


if __name__ == "__main__":
    train()

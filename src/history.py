"""Step 1b - Pharmacy transaction history, Jan 2024 to Jan 2026.

Every month re-uses that calendar month's bills from the cleaned client file, so seasonality,
basket mix, department mix and return behaviour carry over. Prescription volume grows and drug
prices rise year on year (see config.py).
"""
import numpy as np
import pandas as pd

import config
from src.clean import load_clean


def build_history(verbose=True):
    src = load_clean(verbose=verbose).reset_index(drop=True)
    rng = np.random.default_rng(config.SEED)
    src["bill"] = src.groupby(["date", "patient_id", "specialisation"]).ngroup()
    rows_of = src.groupby("bill").indices
    first = src.groupby("bill").agg(date=("date", "first"), patient_id=("patient_id", "first"))
    bills_by_month = {m: g.index.values for m, g in first.groupby(first.date.dt.month)}
    bill_day = first.date.dt.day
    start, end = pd.Timestamp(config.DATA_START), pd.Timestamp(config.DATA_END)
    next_pid = int(src.patient_id.max()) + 1

    parts = []
    for ms in pd.date_range(start, end, freq="MS"):
        yrs = (ms - start).days / 365.25
        pool = bills_by_month[ms.month]
        n = int(rng.poisson(len(pool) * (1 + config.VOLUME_GROWTH) ** yrs * rng.uniform(0.96, 1.04)))
        pick = rng.choice(pool, n, replace=True)
        day = np.clip(bill_day.loc[pick].values + rng.integers(-3, 4, n), 1, ms.days_in_month)
        dates = ms + pd.to_timedelta(day - 1, unit="D")
        new = rng.random(n) < config.NEW_PATIENT_SHARE
        pid = first.patient_id.loc[pick].values.astype("int64")
        pid[new] = next_pid + np.arange(new.sum())
        next_pid += int(new.sum())
        sizes = np.array([len(rows_of[b]) for b in pick])
        idx = np.concatenate([rows_of[b] for b in pick])
        part = src.loc[idx].copy()
        owner = np.repeat(np.arange(n), sizes)
        part["date"] = dates.values[owner]
        part["patient_id"] = pid[owner]
        f = (1 + config.PRICE_INFLATION) ** yrs
        for c in ("final_cost", "final_sales", "rtnmrp"):
            part[c] = (part[c] * f).round(3)
        parts.append(part)

    hist = pd.concat(parts).drop(columns="bill").sort_values("date").reset_index(drop=True)
    hist.to_csv(config.PROCESSED / "transactions.csv", index=False)
    if verbose:
        print(f"[history] {len(hist):,} transaction rows, {hist.date.min():%d %b %Y} to {hist.date.max():%d %b %Y}")
    return hist


if __name__ == "__main__":
    build_history()

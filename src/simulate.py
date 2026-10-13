"""Step 5 - Impact study and live operation after go-live.

From go-live to the end of the data, the same patients and prescriptions are run three ways,
starting from the same shelf:
  1. Old policy               - monthly top-up to last month's consumption (what the store did)
  2. ML reorder               - reorder point / order-up-to levels from the demand forecast
  3. ML reorder + substitutes - plus the substitute recommender at the counter

Scenario 3 is what the pharmacy ran after go-live, so its outcomes become the live records
(prescription outcomes, stock, purchase orders and batches) in the database.

Two robustness checks follow:
  * Ablation    - the same reorder rules driven by a 4-week moving average instead of LightGBM,
                  to show how much the ML forecast itself contributes.
  * Sensitivity - the old policy and RxBounce rerun under harder conditions (lower substitute
                  acceptance, unexpected extra demand, slower suppliers) to check the 30% target still holds.
"""
import math
import numpy as np
import pandas as pd

import config
from src.inventory_engine import replay

P = config.PROCESSED
Q_START, Q_END = pd.Timestamp(config.GO_LIVE), pd.Timestamp(config.DATA_END)
N_DAYS = (Q_END - Q_START).days + 1
SHELF = {"TABLETS & CAPSULES": 36, "DROPS": 18, "NUTRITIONAL SUPPLEMENTS": 18, "VACCINE": 12}
BOUNCE = ("Bounced", "Partial")


def load():
    d = {n: pd.read_csv(P / f"{n}.csv") for n in ["drugs", "drug_supplier", "drug_substitutes", "prescription_items",
                                                  "prescriptions", "sales_transactions"]}
    d["daily"] = pd.read_csv(P / "daily_stock_baseline.csv", parse_dates=["stock_date"])
    d["lines"] = pd.read_csv(P / "demand_lines.csv", parse_dates=["date"])
    d["returns"] = pd.read_csv(P / "returns.csv", parse_dates=["return_date"])
    d["fc"] = pd.read_csv(P / "forecasts.csv", parse_dates=["week_start"])
    d["orders"] = pd.read_csv(P / "replay_orders.csv", parse_dates=["order_date", "arrival_date"])
    return d


def policy_levels(mu, sigma, lt, lt_sd, z, review, pack, interval=7):
    """Safety stock, reorder point and order-up-to level. Protection period = lead time + review interval."""
    protect = lt + interval
    ss = z * math.sqrt(protect * sigma ** 2 + (mu ** 2) * lt_sd ** 2)
    rop = mu * protect + ss
    s_level = rop + mu * review
    if mu > 0:
        rop = max(1, math.ceil(rop))
        s_level = max(rop + pack, math.ceil(s_level))
    else:
        rop, s_level = -1, 0
    return ss, rop, s_level


def ml_plan(d, stocked, fc=None):
    fc = (d["fc"] if fc is None else fc).sort_values("week_start")
    ds = d["drug_supplier"].set_index("drug_id")
    meta = d["drugs"].set_index("drug_id")
    days = pd.date_range(Q_START, Q_END)
    fc_by = {k: v for k, v in fc.groupby("drug_id")}
    plan = {}
    for drug in stocked:
        f = fc_by[drug]
        pos = np.searchsorted(f.week_start.values, days.values, side="right") - 1
        mu_w, sd_w = f.predicted_qty.values[pos], f.sigma_weekly.values[pos]
        abc = meta.at[drug, "abc_class"]
        wd = config.REVIEW_WEEKDAYS_BY_ABC[abc]
        review = np.array([day.weekday() in wd for day in days])
        interval = 7 / len(wd)
        lt, lt_sd, pack = ds.at[drug, "lead_time_mean"], ds.at[drug, "lead_time_sd"], ds.at[drug, "min_order_qty"]
        rop, sl = np.zeros(N_DAYS), np.zeros(N_DAYS)
        for t in range(N_DAYS):
            mu = mu_w[t] / 7
            sigma = max(sd_w[t] / math.sqrt(7), math.sqrt(mu))
            _, rop[t], sl[t] = policy_levels(mu, sigma, lt, lt_sd, config.Z_BY_ABC[abc],
                                             config.REVIEW_DAYS_BY_ABC[abc], pack, interval)
        plan[drug] = (rop, sl, review)
    return plan


def summarise(name, lines, daily, orders, meta):
    unmet_units = (lines.qty - lines.qty_dispensed).clip(lower=0)
    rec_units = lines["recovered_units"].sum() if "recovered_units" in lines else 0
    rec_rev = lines["recovered_revenue"].sum() if "recovered_revenue" in lines else 0
    lost = (unmet_units * lines.drug_id.map(meta.unit_mrp)).sum() - rec_rev
    bounced = lines.status.isin(BOUNCE).sum()
    inv_value = (daily.closing_qty * daily.drug_id.map(meta.unit_cost)).groupby(daily.stock_date).sum().mean()
    rate = config.HOLDING_RATE + config.COLD_CHAIN_SURCHARGE * daily.drug_id.map(meta.is_cold_chain)
    holding = (daily.closing_qty * daily.drug_id.map(meta.unit_cost) * rate).sum() / 365
    emerg = orders[orders.po_type == "Emergency"]
    reg = orders[orders.po_type == "Regular"]
    n_po = reg[["supplier_id", "order_date"]].drop_duplicates().shape[0]
    return {"scenario": name, "prescription_lines": len(lines), "bounced_lines": int(bounced),
            "bounce_rate": bounced / len(lines),
            "unit_fill_rate": 1 - (unmet_units.sum() - rec_units) / lines.qty.sum(),
            "lost_revenue_inr": lost,
            "emergency_purchases": len(emerg),
            "emergency_premium_inr": (emerg.qty * emerg.drug_id.map(meta.unit_cost) * config.EMERGENCY_PREMIUM).sum(),
            "avg_inventory_value_inr": inv_value, "holding_cost_inr": holding,
            "regular_order_lines": len(reg), "purchase_orders": n_po, "ordering_cost_inr": n_po * config.ORDER_COST}


def apply_substitution(lines, daily, subs, meta, rng, acceptance=None):
    acceptance = acceptance or config.SUBSTITUTE_ACCEPTANCE
    stock = daily.set_index(["drug_id", "stock_date"]).closing_qty
    lines = lines.copy()
    lines["recovered_units"] = 0
    lines["recovered_revenue"] = 0.0
    lines["substitute_drug_id"] = pd.Series([None] * len(lines), index=lines.index, dtype=object)
    sub_map = {k: v.sort_values("rank_no") for k, v in subs.groupby("drug_id")}
    for i in lines.index[lines.status.isin(BOUNCE)]:
        drug, day = lines.at[i, "drug_id"], lines.at[i, "date"]
        need = lines.at[i, "qty"] - lines.at[i, "qty_dispensed"]
        for s in sub_map.get(drug, pd.DataFrame()).itertuples():
            if stock.get((s.substitute_drug_id, day), 0) >= need:
                if rng.random() < acceptance[s.match_type]:
                    lines.at[i, "status"] = "Fulfilled (substitute)"
                    lines.at[i, "recovered_units"] = need
                    lines.at[i, "recovered_revenue"] = need * meta.at[s.substitute_drug_id, "unit_mrp"]
                    lines.at[i, "substitute_drug_id"] = s.substitute_drug_id
                break
    return lines


def outcome(lines, out):
    """Turn replay results into per-line dispensed quantities and statuses."""
    disp = dict(zip(out.req_id, out.qty_dispensed))
    l = lines.copy()
    l["qty_dispensed"] = [disp.get(r, q if h else 0) for r, q, h in zip(l.req_id, l.qty, l.is_hist)]
    l.loc[l.drug_id == "DRG0000", "qty_dispensed"] = l.qty
    l["status"] = np.where(l.qty_dispensed >= l.qty, "Fulfilled", np.where(l.qty_dispensed > 0, "Partial", "Bounced"))
    return l


def moving_average_forecast():
    """Same panel as the ML model, but the forecast is simply the mean of the last 4 weeks."""
    from src.train_forecast import weekly_panel
    p = weekly_panel()
    p = p[p.week >= 4]
    return pd.DataFrame({"drug_id": p.drug_id, "week_start": p.week_start,
                         "predicted_qty": p.roll_mean_4.fillna(0), "sigma_weekly": p.roll_std_8.fillna(0)})


def sensitivity(d, meta, lines, rets, params, opening, pipeline, prior30, plan, stocked):
    """Rerun old policy and RxBounce side by side under harder conditions."""
    rng = np.random.default_rng(config.SEED + 5)
    half = {k: v / 2 for k, v in config.SUBSTITUTE_ACCEPTANCE.items()}
    extra = lines[lines.drug_id.isin(stocked)].sample(frac=0.20, random_state=config.SEED).copy()
    extra["req_id"] = ["SENS" + str(i) for i in range(len(extra))]
    extra["is_hist"] = False
    extra["date"] = (extra.date + pd.to_timedelta(rng.integers(-3, 4, len(extra)), unit="D")).clip(Q_START, Q_END)
    slow = params.copy()
    slow["lead_time_mean"] = (slow.lead_time_mean * 1.5).round()

    cases = [("Base case", lines, params, None),
             ("Patients accept half as many substitutes", lines, params, half),
             ("20% more demand than forecast", pd.concat([lines, extra], ignore_index=True), params, None),
             ("Suppliers 50% slower than planned", lines, slow, None)]
    rows = []
    for name, l, prm, acc in cases:
        st = l[l.drug_id.isin(stocked)][["req_id", "date", "drug_id", "qty", "is_hist"]]
        _, b_out, _ = replay(st, rets, prm, Q_START, Q_END, opening, policy="baseline", pipeline=pipeline,
                             prior30=prior30, seed=config.SEED + 11)
        m_daily, m_out, _ = replay(st, rets, prm, Q_START, Q_END, opening, policy="ml", pipeline=pipeline,
                                   ml_plan=plan, seed=config.SEED + 11)
        old = outcome(l, b_out)
        new = apply_substitution(outcome(l, m_out), m_daily, d["drug_substitutes"], meta,
                                 np.random.default_rng(config.SEED), acc)
        ob, nb = old.status.isin(BOUNCE).mean(), new.status.isin(BOUNCE).mean()
        rows.append({"case_name": name, "old_bounce_rate": ob, "rxbounce_bounce_rate": nb,
                     "bounce_reduction_pct": 1 - nb / ob, "meets_target": int(1 - nb / ob >= 0.30)})
    return pd.DataFrame(rows)


def finalize(d, meta, ml_daily, ml_orders, live):
    """Write the live records: what the pharmacy actually experienced with RxBounce after go-live."""
    rng = np.random.default_rng(config.SEED + 99)
    as_of = pd.Timestamp(config.AS_OF)
    nf_ids = set(d["drugs"][d["drugs"].is_formulary == 0].drug_id)

    # prescription outcomes
    pi = d["prescription_items"].set_index("rx_item_id")
    for c in ("bounce_reason", "substitute_drug_id", "txn_id", "status"):
        pi[c] = pi[c].astype(object)
    lv = live.set_index("req_id")
    pi.loc[lv.index, "status"] = lv.status
    pi.loc[lv.index, "qty_dispensed"] = np.where(lv.status == "Fulfilled (substitute)", lv.qty, lv.qty_dispensed)
    pi.loc[lv.index, "substitute_drug_id"] = lv.substitute_drug_id
    pi.loc[lv.index, "bounce_reason"] = np.select(
        [lv.status.isin(["Fulfilled", "Fulfilled (substitute)"]), lv.drug_id.isin(nf_ids), lv.status == "Partial"],
        [None, "Not stocked", "Insufficient quantity"], default="Out of stock")
    pi = pi.reset_index()

    # sales rows for every dispensed line not yet in the sales records
    rx = d["prescriptions"].set_index("rx_id")
    spec_dept = pd.read_csv(P / "specialisations.csv").set_index("spec_id").dept_id
    sub_part = lv.recovered_units.reindex(pi.rx_item_id).fillna(0).values
    new_txn, n = [], len(d["sales_transactions"])
    txn_ids = pi.txn_id.copy()
    for i, r in pi[pi.txn_id.isna() & (pi.qty_dispensed > 0)].iterrows():
        own = int(r.qty_dispensed - sub_part[i])
        p = rx.loc[r.rx_id]
        for drug, q in ((r.drug_id, own), (r.substitute_drug_id, int(sub_part[i]))):
            if q > 0 and isinstance(drug, str):
                n += 1
                tid = f"TXN{n:06d}"
                if pd.isna(txn_ids.at[i]):
                    txn_ids.at[i] = tid
                new_txn.append((tid, r.rx_id, p.patient_id, drug, p.spec_id, spec_dept.get(p.spec_id), p.rx_date, q,
                                round(q * meta.at[drug, "unit_cost"], 3), round(q * meta.at[drug, "unit_mrp"], 3)))
    pi["txn_id"] = txn_ids
    sales = pd.concat([d["sales_transactions"], pd.DataFrame(new_txn, columns=d["sales_transactions"].columns)])

    # stock history, stock on hand, orders
    base = d["daily"]
    daily = pd.concat([base[base.stock_date < Q_START], ml_daily]).sort_values(["drug_id", "stock_date"])
    last = ml_daily[ml_daily.stock_date == as_of].set_index("drug_id")
    stock_on_hand = pd.DataFrame({"drug_id": last.index, "qty_on_hand": last.closing_qty.values,
                                  "on_order_qty": last.on_order_qty.values, "updated_at": as_of})
    pos = pd.concat([d["orders"][d["orders"].order_date < Q_START], ml_orders], ignore_index=True)
    purchase_orders = pd.DataFrame({
        "po_id": pos.po_id, "supplier_id": pos.supplier_id, "order_date": pos.order_date,
        "expected_date": pos.arrival_date, "received_date": pos.arrival_date.where(pos.arrival_date <= as_of),
        "po_type": pos.po_type, "status": np.where(pos.arrival_date <= as_of, "Received", "Open")})
    po_items = pd.DataFrame({"po_item_id": [f"POI{i+1:06d}" for i in range(len(pos))], "po_id": pos.po_id,
                             "drug_id": pos.drug_id, "order_qty": pos.qty,
                             "unit_cost": (pos.drug_id.map(meta.unit_cost) *
                                           np.where(pos.po_type == "Emergency", 1 + config.EMERGENCY_PREMIUM, 1)).round(2)})

    # batches on the shelf today
    batches, b = [], 0
    for drug, q in zip(stock_on_hand.drug_id, stock_on_hand.qty_on_hand):
        if q <= 0:
            continue
        k = 1 if q < 5 else int(rng.integers(1, 4))
        cuts = sorted(rng.choice(np.arange(1, q), k - 1, replace=False)) if k > 1 else []
        shelf = SHELF.get(meta.at[drug, "subcat"], 24)
        for part in np.diff([0, *cuts, q]):
            b += 1
            recv = as_of - pd.Timedelta(days=int(rng.integers(3, 120)))
            age = int(rng.uniform(0.1, 0.75) * shelf * 30.4)
            if rng.random() < 0.06:                     # a few old lots close to or past expiry
                age = int(shelf * 30.4 - rng.integers(-20, 140)) - (as_of - recv).days
            mfg = recv - pd.Timedelta(days=max(age, 15))
            batches.append((f"BAT{b:05d}", drug, f"L{rng.integers(10000, 99999)}", recv, mfg,
                            mfg + pd.DateOffset(months=shelf), int(part), float(meta.at[drug, "unit_cost"])))
    inventory_batches = pd.DataFrame(batches, columns=["batch_id", "drug_id", "lot_no", "received_date", "mfg_date",
                                                       "expiry_date", "qty_remaining", "unit_cost"])

    for name, t in [("prescription_items", pi), ("sales_transactions", sales), ("daily_stock", daily),
                    ("stock_on_hand", stock_on_hand), ("purchase_orders", purchase_orders), ("po_items", po_items),
                    ("inventory_batches", inventory_batches)]:
        t.to_csv(P / f"{name}.csv", index=False)
    print(f"[live] {len(new_txn):,} new sales rows, {len(purchase_orders):,} purchase orders, "
          f"{len(inventory_batches):,} batches on the shelf")


def run():
    d = load()
    meta = d["drugs"].set_index("drug_id")
    stocked = list(d["drug_supplier"].drug_id)
    lines = d["lines"][d["lines"].date.between(Q_START, Q_END)].copy()
    q_lines_st = lines[lines.drug_id.isin(stocked)]
    rets = d["returns"].rename(columns={"return_date": "date", "return_qty": "qty"})
    rets = rets[rets.drug_id.isin(stocked)]

    # 1. old policy
    base_daily = d["daily"][d["daily"].stock_date.between(Q_START, Q_END)]
    base_orders = d["orders"][d["orders"].order_date.between(Q_START, Q_END)]
    base_lines = lines.copy()
    results = [summarise("Current policy", base_lines, base_daily, base_orders, meta)]

    # 2. ML reorder, starting from the same shelf and the same open orders
    start_state = d["daily"][d["daily"].stock_date == Q_START - pd.Timedelta(days=1)]
    opening = dict(zip(start_state.drug_id, start_state.closing_qty))
    open_orders = d["orders"][(d["orders"].po_type == "Regular") & (d["orders"].order_date < Q_START)
                              & (d["orders"].arrival_date >= Q_START)]
    pipeline = {k: list(zip(v.arrival_date, v.qty, v.po_id)) for k, v in open_orders.groupby("drug_id")}
    params = d["drug_supplier"].set_index("drug_id")
    params["pack_size"] = params.min_order_qty
    plan = ml_plan(d, stocked)
    ml_daily, ml_out, ml_orders = replay(q_lines_st[["req_id", "date", "drug_id", "qty", "is_hist"]], rets, params,
                                         Q_START, Q_END, opening, policy="ml", pipeline=pipeline, ml_plan=plan,
                                         seed=config.SEED + 7, po_prefix="ML")
    disp = dict(zip(ml_out.req_id, ml_out.qty_dispensed))
    ml_lines = lines.copy()
    ml_lines["qty_dispensed"] = [disp.get(r, q if h else 0) for r, q, h in zip(ml_lines.req_id, ml_lines.qty, ml_lines.is_hist)]
    ml_lines.loc[ml_lines.drug_id == "DRG0000", "qty_dispensed"] = ml_lines.qty
    ml_lines["status"] = np.where(ml_lines.qty_dispensed >= ml_lines.qty, "Fulfilled",
                                  np.where(ml_lines.qty_dispensed > 0, "Partial", "Bounced"))
    results.append(summarise("ML reorder policy", ml_lines, ml_daily, ml_orders, meta))

    # 3. ML reorder + substitutes
    sub_lines = apply_substitution(ml_lines, ml_daily, d["drug_substitutes"], meta, np.random.default_rng(config.SEED))
    results.append(summarise("ML reorder + substitutes", sub_lines, ml_daily, ml_orders, meta))

    res = pd.DataFrame(results)
    base = res.iloc[0]
    res["bounce_reduction_pct"] = 1 - res.bounce_rate / base.bounce_rate
    res["bounces_prevented"] = base.bounced_lines - res.bounced_lines
    res["revenue_recovered_inr"] = base.lost_revenue_inr - res.lost_revenue_inr
    res["revenue_recovered_annual_inr"] = res.revenue_recovered_inr * 365 / N_DAYS
    res["inventory_cost_change_inr"] = (res.holding_cost_inr + res.ordering_cost_inr + res.emergency_premium_inr) - (
        base.holding_cost_inr + base.ordering_cost_inr + base.emergency_premium_inr)
    res["net_benefit_annual_inr"] = res.revenue_recovered_annual_inr - res.inventory_cost_change_inr * 365 / N_DAYS
    res["window_days"] = N_DAYS
    res.to_csv(config.REPORTS / "simulation_results.csv", index=False)

    monthly = []
    for name, l in [("Current policy", base_lines), ("ML reorder policy", ml_lines),
                    ("ML reorder + substitutes", sub_lines)]:
        unmet = (l.qty - l.qty_dispensed).clip(lower=0) * l.drug_id.map(meta.unit_mrp)
        if "recovered_revenue" in l:
            unmet = unmet - l.recovered_revenue
        grp = l.assign(lost=unmet).groupby(l.date.dt.to_period("M"))
        for month, gm in grp:
            monthly.append({"scenario": name, "month": str(month),
                            "bounce_rate": gm.status.isin(BOUNCE).mean(), "lost_revenue": gm.lost.sum()})
    pd.DataFrame(monthly).to_csv(config.REPORTS / "simulation_breakdown.csv", index=False)

    # ---- ablation: same reorder rules, moving-average forecast instead of LightGBM ----
    plan_ma = ml_plan(d, stocked, moving_average_forecast())
    ma_daily, ma_out, ma_orders = replay(q_lines_st[["req_id", "date", "drug_id", "qty", "is_hist"]], rets, params,
                                         Q_START, Q_END, opening, policy="ml", pipeline=pipeline, ml_plan=plan_ma,
                                         seed=config.SEED + 7, po_prefix="MA")
    ma = summarise("Reorder rules + moving average", outcome(lines, ma_out), ma_daily, ma_orders, meta)
    abl = pd.DataFrame([{**results[0], "step": "Old policy"}, {**ma, "step": "Reorder rules + moving-average forecast"},
                        {**results[1], "step": "Reorder rules + LightGBM forecast"},
                        {**results[2], "step": "LightGBM + substitutes"}])
    abl["bounce_reduction_pct"] = 1 - abl.bounce_rate / base.bounce_rate
    abl["revenue_recovered_annual_inr"] = (base.lost_revenue_inr - abl.lost_revenue_inr) * 365 / N_DAYS
    abl = abl[["step", "bounce_rate", "bounce_reduction_pct", "revenue_recovered_annual_inr", "avg_inventory_value_inr"]]
    abl.to_csv(config.REPORTS / "ablation.csv", index=False)
    print("[ablation] contribution of each part:")
    print(abl.round(3).to_string(index=False))

    # ---- sensitivity: harder conditions ----
    prior = d["daily"][d["daily"].stock_date.between(Q_START - pd.Timedelta(days=30), Q_START - pd.Timedelta(days=1))]
    prior30 = prior.groupby("drug_id").dispensed_qty.sum().to_dict()
    sens = sensitivity(d, meta, lines, rets, params, opening, pipeline, prior30, plan, stocked)
    sens.to_csv(config.REPORTS / "sensitivity.csv", index=False)
    print("[sensitivity] bounce reduction under harder conditions:")
    print(sens.round(3).to_string(index=False))

    show = res[["scenario", "bounce_rate", "bounce_reduction_pct", "unit_fill_rate", "lost_revenue_inr",
                "revenue_recovered_annual_inr", "emergency_purchases", "avg_inventory_value_inr",
                "net_benefit_annual_inr"]]
    print(f"[impact] {Q_START:%d %b %Y} to {Q_END:%d %b %Y}, same demand for every scenario:")
    print(show.round(3).to_string(index=False))

    finalize(d, meta, ml_daily, ml_orders, sub_lines)
    return res


if __name__ == "__main__":
    run()

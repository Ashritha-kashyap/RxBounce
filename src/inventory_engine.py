"""Day-by-day inventory engine.

For every drug and every day:
  1. receive purchase orders that arrive today
  2. add patient returns back to stock
  3. serve prescription lines in arrival order
       - lines that were dispensed in the pharmacy records are always served
         (a local emergency purchase covers any shortfall, as the pharmacy did)
       - other requested lines are served only from shelf stock -> otherwise a bounce
  4. apply the replenishment policy
       - "baseline": on the 1st of each month top stock up to last 30 days' dispensed quantity
       - "ml":       on review days (Mon/Thu for A items, Mon for B/C) order up to S
                     when inventory position <= forecast-based reorder point
"""
import math
import numpy as np
import pandas as pd


def _round_pack(q, pack):
    return int(math.ceil(max(q, 0) / pack) * pack)


def replay(requests, returns, params, start, end, opening, policy="baseline",
           pipeline=None, ml_plan=None, seed=42, po_prefix="PO", prior30=None):
    """prior30: optional dict drug -> units dispensed in the 30 days before `start` (old policy's first order)."""
    days = pd.date_range(start, end, freq="D")
    n_days = len(days)
    day_idx = {d: i for i, d in enumerate(days)}
    pipeline = pipeline or {}

    req = requests[(requests.date >= days[0]) & (requests.date <= days[-1])]
    req_by_drug = {k: v for k, v in req.groupby("drug_id")}
    ret = returns[(returns.date >= days[0]) & (returns.date <= days[-1])]
    ret_by_drug = {k: v.groupby("date").qty.sum() for k, v in ret.groupby("drug_id")}

    daily, outcomes, pos = [], [], []
    po_no = 0
    for k, drug in enumerate(params.index):
        p = params.loc[drug]
        rng = np.random.default_rng(seed + k)
        stock = int(opening.get(drug, 0))
        pending = [(day_idx.get(a, n_days + 999) if a >= days[0] else 0, q, pid)
                   for a, q, pid in pipeline.get(drug, [])]
        dispensed_hist = np.zeros(n_days)

        todays = {}
        if drug in req_by_drug:
            r = req_by_drug[drug]
            for rid, dt, q, h in zip(r.req_id, r.date, r.qty, r.is_hist):
                todays.setdefault(day_idx[dt], []).append((rid, int(q), bool(h)))
        rets = ret_by_drug.get(drug, pd.Series(dtype=float))

        for t, day in enumerate(days):
            opening_qty = stock
            received = sum(q for a, q, _ in pending if a == t)
            pending = [x for x in pending if x[0] != t]
            stock += received
            returned = int(rets.get(day, 0))
            stock += returned

            emergency = dispensed = unmet = 0
            lines = todays.get(t, [])
            if lines:
                for i in rng.permutation(len(lines)):
                    rid, q, is_hist = lines[i]
                    if is_hist:
                        if stock < q:
                            short = q - stock
                            emergency += short
                            stock += short
                            po_no += 1
                            pos.append((f"{po_prefix}E{po_no:06d}", drug, "SUP09", day, day, short, "Emergency"))
                        stock -= q
                        dispensed += q
                        outcomes.append((rid, q))
                    else:
                        give = min(stock, q)
                        stock -= give
                        dispensed += give
                        unmet += q - give
                        outcomes.append((rid, give))
            dispensed_hist[t] = dispensed
            on_order = sum(q for _, q, _ in pending)

            qty = 0
            if policy == "baseline":
                if day.day == 1:
                    if t > 0:
                        last_month = dispensed_hist[max(0, t - 30):t].sum()
                    else:
                        last_month = prior30.get(drug, opening_qty) if prior30 else opening_qty
                    qty = last_month - stock - on_order
                    qty = _round_pack(qty, p.pack_size) if qty > 0 else 0
            elif policy == "ml":
                rop, s_level, review = ml_plan[drug]
                position = stock + on_order
                if review[t] and position <= rop[t]:
                    qty = _round_pack(s_level[t] - position, p.pack_size)
            if qty > 0:
                lt = max(1, int(round(rng.normal(p.lead_time_mean, p.lead_time_sd))))
                po_no += 1
                pid = f"{po_prefix}R{po_no:06d}"
                pending.append((t + lt, int(qty), pid))
                pos.append((pid, drug, p.supplier_id, day, day + pd.Timedelta(days=lt), int(qty), "Regular"))
                on_order += int(qty)

            daily.append((drug, day, opening_qty, received, emergency, returned, dispensed, unmet, stock, on_order))

    daily = pd.DataFrame(daily, columns=["drug_id", "stock_date", "opening_qty", "received_qty", "emergency_qty",
                                         "returned_qty", "dispensed_qty", "unmet_qty", "closing_qty", "on_order_qty"])
    outcomes = pd.DataFrame(outcomes, columns=["req_id", "qty_dispensed"])
    pos = pd.DataFrame(pos, columns=["po_id", "drug_id", "supplier_id", "order_date", "arrival_date", "qty", "po_type"])
    return daily, outcomes, pos

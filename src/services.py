"""Service layer: every database read/write the Streamlit app needs."""
import hashlib
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import text

import config
from src.db import get_engine, query

AS_OF = pd.Timestamp(config.AS_OF)
GO_LIVE = pd.Timestamp(config.GO_LIVE)
DATA_START = pd.Timestamp(config.DATA_START)
BOUNCE = ("Bounced", "Partial")


def _dates(df, cols):
    for c in cols:
        if c in df:
            df[c] = pd.to_datetime(df[c])
    return df


# ---------------- authentication ----------------
def hash_password(pw):
    return hashlib.sha256(("rxbounce::" + pw).encode()).hexdigest()


def authenticate(username, password):
    u = query("SELECT username, full_name, role, password_hash FROM users WHERE username = :u", {"u": username})
    if len(u) and u.password_hash.iat[0] == hash_password(password):
        return u.iloc[0][["username", "full_name", "role"]].to_dict()
    return None


def list_users():
    return query("SELECT user_id, username, full_name, role FROM users ORDER BY user_id")


def add_user(username, full_name, role, password):
    with get_engine().begin() as con:
        uid = con.execute(text("SELECT COALESCE(MAX(user_id), 0) + 1 FROM users")).scalar()
        con.execute(text("INSERT INTO users (user_id, username, password_hash, full_name, role) "
                         "VALUES (:i, :u, :p, :f, :r)"),
                    {"i": uid, "u": username, "p": hash_password(password), "f": full_name, "r": role})


# ---------------- reference data ----------------
def drugs():
    return query("SELECT * FROM drugs ORDER BY drug_name")


def doctors():
    return query("SELECT d.doctor_id, d.doctor_name, s.spec_id, s.spec_name, s.dept_id FROM doctors d "
                 "JOIN specialisations s ON s.spec_id = d.spec_id ORDER BY d.doctor_name")


def patient_ids():
    return query("SELECT patient_id FROM patients ORDER BY patient_id").patient_id.tolist()


# ---------------- prescription lines (bounce analytics) ----------------
def prescription_lines():
    df = query("""
        SELECT pi.rx_item_id, p.rx_id, p.rx_date, p.patient_id, s.spec_name, dp.dept_name,
               dr.drug_id, dr.drug_name, dr.subcat, dr.abc_class, dr.unit_mrp, pi.qty_requested,
               pi.qty_dispensed, pi.status, pi.bounce_reason, pi.substitute_drug_id
        FROM prescription_items pi
        JOIN prescriptions p ON p.rx_id = pi.rx_id
        JOIN drugs dr ON dr.drug_id = pi.drug_id
        LEFT JOIN specialisations s ON s.spec_id = p.spec_id
        LEFT JOIN departments dp ON dp.dept_id = s.dept_id""")
    df = _dates(df, ["rx_date"])
    df["is_bounce"] = df.status.isin(BOUNCE).astype(int)
    df["unmet_qty"] = (df.qty_requested - df.qty_dispensed).clip(lower=0)
    df["lost_revenue"] = df.unmet_qty * df.unit_mrp.astype(float)
    df["month"] = df.rx_date.dt.to_period("M").dt.to_timestamp()
    return df


# ---------------- stock, policy and alerts ----------------
def stock_view():
    df = query("""
        SELECT dr.drug_id, dr.drug_name, dr.subcat, dr.abc_class, dr.unit_cost, dr.unit_mrp, dr.is_cold_chain,
               s.qty_on_hand, s.on_order_qty, rp.avg_daily_forecast, rp.safety_stock, rp.reorder_point,
               rp.order_up_to, rp.suggested_order_qty, rp.stockout_risk, rp.risk_band,
               ds.supplier_id, sp.supplier_name, ds.lead_time_mean, ds.min_order_qty
        FROM stock_on_hand s
        JOIN drugs dr ON dr.drug_id = s.drug_id
        LEFT JOIN reorder_policy rp ON rp.drug_id = s.drug_id
        LEFT JOIN drug_supplier ds ON ds.drug_id = s.drug_id
        LEFT JOIN suppliers sp ON sp.supplier_id = ds.supplier_id""")
    for c in ["unit_cost", "unit_mrp", "avg_daily_forecast", "safety_stock", "stockout_risk"]:
        df[c] = df[c].astype(float)
    df["days_of_cover"] = np.where(df.avg_daily_forecast > 0,
                                   df.qty_on_hand / df.avg_daily_forecast.replace(0, np.nan), np.inf)
    df["stock_value"] = df.qty_on_hand * df.unit_cost
    return df


def batches():
    df = query("SELECT b.*, d.drug_name, d.abc_class, d.subcat FROM inventory_batches b "
               "JOIN drugs d ON d.drug_id = b.drug_id WHERE b.qty_remaining > 0")
    df = _dates(df, ["received_date", "mfg_date", "expiry_date"])
    df["days_to_expiry"] = (df.expiry_date - AS_OF).dt.days
    df["value"] = df.qty_remaining * df.unit_cost.astype(float)
    return df


def create_purchase_orders(rows):
    """rows: DataFrame with drug_id, supplier_id, order_qty, unit_cost, lead_time_mean. One PO per supplier."""
    if rows.empty:
        return []
    created = []
    with get_engine().begin() as con:
        n_po = con.execute(text("SELECT COUNT(*) FROM purchase_orders WHERE po_type = 'Manual'")).scalar()
        n_item = con.execute(text("SELECT COUNT(*) FROM po_items")).scalar()
        for sup, grp in rows.groupby("supplier_id"):
            n_po += 1
            po_id = f"POM{n_po:06d}"
            lt = int(grp.lead_time_mean.max()) if "lead_time_mean" in grp else 5
            con.execute(text("INSERT INTO purchase_orders (po_id, supplier_id, order_date, expected_date, "
                             "received_date, po_type, status) VALUES (:p, :s, :o, :e, NULL, 'Manual', 'Open')"),
                        {"p": po_id, "s": sup, "o": AS_OF.date(), "e": (AS_OF + pd.Timedelta(days=lt)).date()})
            for r in grp.itertuples():
                n_item += 1
                con.execute(text("INSERT INTO po_items (po_item_id, po_id, drug_id, order_qty, unit_cost) "
                                 "VALUES (:i, :p, :d, :q, :c)"),
                            {"i": f"POM-{n_item:06d}", "p": po_id, "d": r.drug_id, "q": int(r.order_qty),
                             "c": float(r.unit_cost)})
                con.execute(text("UPDATE stock_on_hand SET on_order_qty = on_order_qty + :q WHERE drug_id = :d"),
                            {"q": int(r.order_qty), "d": r.drug_id})
                con.execute(text("UPDATE reorder_policy SET suggested_order_qty = 0 WHERE drug_id = :d"),
                            {"d": r.drug_id})
                con.execute(text("UPDATE alerts SET is_resolved = 1 WHERE drug_id = :d AND alert_type = 'Reorder'"),
                            {"d": r.drug_id})
            created.append(po_id)
    return created


def manual_orders():
    df = query("""SELECT po.po_id, s.supplier_name, po.order_date, po.expected_date,
                         COUNT(pi.po_item_id) AS line_count, SUM(pi.order_qty * pi.unit_cost) AS po_value
                  FROM purchase_orders po JOIN suppliers s ON s.supplier_id = po.supplier_id
                  JOIN po_items pi ON pi.po_id = po.po_id
                  WHERE po.po_type = 'Manual'
                  GROUP BY po.po_id, s.supplier_name, po.order_date, po.expected_date
                  ORDER BY po.po_id DESC""")
    return _dates(df, ["order_date", "expected_date"])


# ---------------- counter operations ----------------
def substitutes_for(drug_id):
    return query("""SELECT ds.substitute_drug_id AS drug_id, d.drug_name, ds.match_type, ds.rank_no, d.unit_mrp,
                           COALESCE(s.qty_on_hand, 0) AS qty_on_hand
                    FROM drug_substitutes ds JOIN drugs d ON d.drug_id = ds.substitute_drug_id
                    LEFT JOIN stock_on_hand s ON s.drug_id = ds.substitute_drug_id
                    WHERE ds.drug_id = :d ORDER BY ds.rank_no""", {"d": drug_id})


def check_availability(lines):
    """lines: DataFrame[drug_id, qty]. Returns availability with a best in-stock substitute."""
    stock = query("SELECT d.drug_id, s.qty_on_hand, d.is_formulary FROM drugs d "
                  "LEFT JOIN stock_on_hand s ON s.drug_id = d.drug_id")
    stock = stock.fillna({"qty_on_hand": 0}).set_index("drug_id")
    out = []
    for r in lines.itertuples():
        on_hand = int(stock.qty_on_hand.get(r.drug_id, 0) or 0)
        formulary = int(stock.is_formulary.get(r.drug_id, 1))
        if r.drug_id == "DRG0000":
            status, on_hand = "Available", r.qty
        elif not formulary:
            status = "Not stocked"
        elif on_hand >= r.qty:
            status = "Available"
        elif on_hand > 0:
            status = "Partial"
        else:
            status = "Out of stock"
        sub = None
        if status != "Available":
            need = r.qty - (on_hand if status == "Partial" else 0)
            subs = substitutes_for(r.drug_id)
            subs = subs[subs.qty_on_hand >= need]
            if len(subs):
                sub = subs.iloc[0].to_dict()
        out.append({"drug_id": r.drug_id, "qty": int(r.qty), "on_hand": on_hand, "status": status,
                    "substitute_id": sub["drug_id"] if sub else None,
                    "substitute_name": sub["drug_name"] if sub else None,
                    "match_type": sub["match_type"] if sub else None})
    return pd.DataFrame(out)


def dispense(patient_id, doctor_id, spec_id, dept_id, decisions):
    """decisions: DataFrame[drug_id, qty, on_hand, status, use_substitute, substitute_id]. Writes everything."""
    now = datetime.now()
    rx_id = "RXC" + now.strftime("%y%m%d%H%M%S")
    meta = query("SELECT drug_id, unit_mrp, unit_cost FROM drugs").set_index("drug_id")
    summary = {"rx_id": rx_id, "dispensed_value": 0.0, "bounced_lines": 0, "substituted_lines": 0}
    with get_engine().begin() as con:
        exists = con.execute(text("SELECT COUNT(*) FROM patients WHERE patient_id = :p"), {"p": patient_id}).scalar()
        if not exists:
            con.execute(text("INSERT INTO patients (patient_id, first_visit_date, visit_count) VALUES (:p, :d, 1)"),
                        {"p": patient_id, "d": AS_OF.date()})
        else:
            con.execute(text("UPDATE patients SET visit_count = visit_count + 1 WHERE patient_id = :p"), {"p": patient_id})
        con.execute(text("INSERT INTO prescriptions (rx_id, patient_id, doctor_id, spec_id, rx_date, source) "
                         "VALUES (:r, :p, :d, :s, :dt, 'Pharmacy counter')"),
                    {"r": rx_id, "p": patient_id, "d": doctor_id, "s": spec_id, "dt": AS_OF.date()})
        for i, r in enumerate(decisions.itertuples(), start=1):
            item_id = f"{rx_id}-{i:02d}"
            give_drug, sub_id, reason = r.drug_id, None, None
            if r.status == "Available":
                qty_disp, status = r.qty, "Fulfilled"
            elif r.use_substitute and r.substitute_id:
                give_drug, sub_id = r.substitute_id, r.substitute_id
                qty_disp, status = r.qty, "Fulfilled (substitute)"
                summary["substituted_lines"] += 1
            elif r.status == "Partial":
                qty_disp, status, reason = r.on_hand, "Partial", "Insufficient quantity"
                summary["bounced_lines"] += 1
            else:
                qty_disp, status = 0, "Bounced"
                reason = "Not stocked" if r.status == "Not stocked" else "Out of stock"
                summary["bounced_lines"] += 1
            txn_id = None
            if qty_disp > 0:
                txn_id = f"TXC{rx_id[3:]}-{i:02d}"
                mrp, cost = float(meta.at[give_drug, "unit_mrp"]), float(meta.at[give_drug, "unit_cost"])
                con.execute(text("INSERT INTO sales_transactions (txn_id, rx_id, patient_id, drug_id, spec_id, dept_id, "
                                 "txn_date, quantity, final_cost, final_sales) VALUES (:t, :r, :p, :d, :s, :dp, :dt, :q, :c, :v)"),
                            {"t": txn_id, "r": rx_id, "p": patient_id, "d": give_drug, "s": spec_id, "dp": dept_id,
                             "dt": AS_OF.date(), "q": int(qty_disp), "c": cost * qty_disp, "v": mrp * qty_disp})
                summary["dispensed_value"] += mrp * qty_disp
                if give_drug != "DRG0000":
                    con.execute(text("UPDATE stock_on_hand SET qty_on_hand = qty_on_hand - :q WHERE drug_id = :d"),
                                {"q": int(qty_disp), "d": give_drug})
                    _consume_batches(con, give_drug, int(qty_disp))
            con.execute(text("INSERT INTO prescription_items (rx_item_id, rx_id, drug_id, qty_requested, qty_dispensed, "
                             "status, bounce_reason, txn_id, substitute_drug_id) VALUES (:i, :r, :d, :q, :qd, :s, :b, :t, :sub)"),
                        {"i": item_id, "r": rx_id, "d": r.drug_id, "q": int(r.qty), "qd": int(qty_disp), "s": status,
                         "b": reason, "t": txn_id, "sub": sub_id})
    return summary


def _consume_batches(con, drug_id, qty):
    """First-expiry-first-out: take stock from the lot that expires soonest (skipping expired lots)."""
    lots = con.execute(text("SELECT batch_id, qty_remaining FROM inventory_batches WHERE drug_id = :d "
                            "AND qty_remaining > 0 AND expiry_date > :t ORDER BY expiry_date"),
                       {"d": drug_id, "t": AS_OF.date()}).fetchall()
    for batch_id, left in lots:
        if qty <= 0:
            break
        take = min(left, qty)
        con.execute(text("UPDATE inventory_batches SET qty_remaining = qty_remaining - :q WHERE batch_id = :b"),
                    {"q": take, "b": batch_id})
        qty -= take


# ---------------- ML outputs ----------------
def forecasts(drug_id):
    return _dates(query("SELECT * FROM forecasts WHERE drug_id = :d ORDER BY week_start", {"d": drug_id}), ["week_start"])


def model_metrics():
    return query("SELECT task, model, is_selected, metric, value FROM model_metrics")


def feature_importance():
    return query("SELECT feature, importance, method, model FROM feature_importance")


def simulation():
    res = query("SELECT scenario, metric, value FROM simulation_results")
    wide = res.pivot(index="scenario", columns="metric", values="value")
    order = ["Current policy", "ML reorder policy", "ML reorder + substitutes"]
    wide = wide.reindex(order).apply(pd.to_numeric, errors="coerce")
    brk = query("SELECT scenario, month, bounce_rate, lost_revenue FROM simulation_breakdown")
    return wide, brk


def robustness():
    abl = query("SELECT step, bounce_rate, bounce_reduction_pct, revenue_recovered_annual_inr, "
                "avg_inventory_value_inr FROM model_ablation ORDER BY id")
    sens = query("SELECT case_name, old_bounce_rate, rxbounce_bounce_rate, bounce_reduction_pct, meets_target "
                 "FROM sensitivity_results ORDER BY id")
    return abl, sens


def table_counts():
    tables = ["patients", "doctors", "drugs", "prescriptions", "prescription_items", "sales_transactions", "returns",
              "purchase_orders", "po_items", "daily_stock", "stock_on_hand", "inventory_batches", "drug_substitutes",
              "forecasts", "reorder_policy", "alerts", "users"]
    rows = [(t, int(query(f"SELECT COUNT(*) AS n FROM {t}").n.iat[0])) for t in tables]
    return pd.DataFrame(rows, columns=["table", "rows"])

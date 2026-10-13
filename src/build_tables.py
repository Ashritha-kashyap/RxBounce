"""Step 1c - Build the relational tables of the pharmacy system (Jan 2024 to Jan 2026).

Writes one CSV per table in data/processed/, matching sql/01_schema.sql. The whole period is first
replayed under the pharmacy's old ordering policy. simulate.py then replays the months after
go-live with RxBounce and writes the final stock, order and prescription outcomes.
"""
import hashlib
import math
import numpy as np
import pandas as pd

import config
from src.history import build_history
from src.substitutes import parse_drug
from src.inventory_engine import replay

OUT = config.PROCESSED

FIRST = ["Arjun", "Priya", "Rahul", "Sneha", "Vikram", "Ananya", "Karthik", "Meera", "Suresh", "Divya", "Rohan",
         "Kavya", "Aditya", "Nandini", "Nikhil", "Pooja", "Sanjay", "Deepa", "Harish", "Neha", "Manoj", "Asha"]
LAST = ["Sharma", "Reddy", "Iyer", "Nair", "Rao", "Patel", "Menon", "Gupta", "Kulkarni", "Hegde", "Shetty",
        "Pillai", "Bhat", "Joshi", "Verma", "Das", "Kumar", "Naidu", "Desai", "Mehta"]

NON_FORMULARY = [
    ("TELMISARTAN 40MG TAB", "TABLETS & CAPSULES", "CARDIOVASCULAR & HEMATOPOIETIC SYSTEM"),
    ("ROSUVASTATIN 10MG TAB", "TABLETS & CAPSULES", "CARDIOVASCULAR & HEMATOPOIETIC SYSTEM"),
    ("CILNIDIPINE 10MG TAB", "TABLETS & CAPSULES", "CARDIOVASCULAR & HEMATOPOIETIC SYSTEM"),
    ("SACUBITRIL 49MG + VALSARTAN 51MG TAB", "TABLETS & CAPSULES", "CARDIOVASCULAR & HEMATOPOIETIC SYSTEM"),
    ("DAPAGLIFLOZIN 10MG TAB", "TABLETS & CAPSULES", "HORMONES"),
    ("SITAGLIPTIN 100MG TAB", "TABLETS & CAPSULES", "HORMONES"),
    ("TENELIGLIPTIN 20MG TAB", "TABLETS & CAPSULES", "HORMONES"),
    ("VILDAGLIPTIN 50MG TAB", "TABLETS & CAPSULES", "HORMONES"),
    ("CEFIXIME 200MG TAB", "TABLETS & CAPSULES", "ANTI-INFECTIVES"),
    ("FAROPENEM 200MG TAB", "TABLETS & CAPSULES", "ANTI-INFECTIVES"),
    ("CEFPODOXIME 200MG TAB", "TABLETS & CAPSULES", "ANTI-INFECTIVES"),
    ("LINEZOLID 600MG TAB", "TABLETS & CAPSULES", "ANTI-INFECTIVES"),
    ("RIFAXIMIN 550MG TAB", "TABLETS & CAPSULES", "GASTRO INTESTINAL"),
    ("ESOMEPRAZOLE 40MG TAB", "TABLETS & CAPSULES", "GASTRO INTESTINAL"),
    ("ITOPRIDE 50MG TAB", "TABLETS & CAPSULES", "GASTRO INTESTINAL"),
    ("PREGABALIN 75MG CAP", "TABLETS & CAPSULES", "CENTRAL NERVOUS SYSTEM"),
    ("LEVETIRACETAM 750MG TAB", "TABLETS & CAPSULES", "CENTRAL NERVOUS SYSTEM"),
    ("ESCITALOPRAM 10MG TAB", "TABLETS & CAPSULES", "CENTRAL NERVOUS SYSTEM"),
    ("MONTELUKAST 10MG + LEVOCETIRIZINE 5MG TAB", "TABLETS & CAPSULES", "RESPIRATORY SYSTEM"),
    ("BUDESONIDE 200MCG + FORMOTEROL 6MCG INHALER", "INHALERS & RESPULES", "RESPIRATORY SYSTEM"),
    ("CALCIUM CARBONATE 500MG + VITAMIN D3 250IU TAB", "TABLETS & CAPSULES", "VITAMINS & MINERALS"),
    ("FERRIC CARBOXYMALTOSE 500MG INJ", "INJECTIONS", "CARDIOVASCULAR & HEMATOPOIETIC SYSTEM"),
    ("TERIPARATIDE 750MCG/3ML INJ", "INJECTIONS", "HORMONES"),
    ("ENOXAPARIN 60MG INJ", "INJECTIONS", "CARDIOVASCULAR & HEMATOPOIETIC SYSTEM"),
    ("LACTULOSE 10GM/15ML SYP", "SYRUP & SUSPENSION", "GASTRO INTESTINAL"),
]
COLD_RE = "INSULIN|ALBUMIN|IMMUNOGLOBULIN|ERYTHROPOIETIN|FILGRASTIM|OXYTOCIN|VACCINE|TERIPARATIDE"
SUPPLIERS = [
    ("SUP01", "Sri Balaji IV Fluids Distributors", "IV fluids & electrolytes", "Local", 2),
    ("SUP02", "Medline Injectables Pvt Ltd", "Injectables (general)", "Regional", 3),
    ("SUP03", "CritiCare Pharma Agencies", "Injectables (critical care)", "Regional", 6),
    ("SUP04", "Apex Oral Solids C&F", "Tablets & capsules", "Regional", 4),
    ("SUP05", "Sunrise Pharma Traders", "Tablets & capsules", "Regional", 5),
    ("SUP06", "Unity Liquids & Topicals", "Syrups, drops, topicals, others", "Regional", 5),
    ("SUP07", "ColdLink Biologics", "Cold-chain (2-8 C) items", "National", 7),
    ("SUP08", "GlobalMed Specialty Imports", "Imported / high-value specialty", "Import", 14),
    ("SUP09", "City Medicals (local emergency purchase)", "Same-day emergency purchase", "Local", 0),
]
HOLIDAYS = [
    ("2024-01-15", "Makar Sankranti / Pongal", "Festival"), ("2024-01-26", "Republic Day", "Gazetted"),
    ("2024-03-08", "Maha Shivaratri", "Festival"), ("2024-03-25", "Holi", "Festival"),
    ("2024-03-29", "Good Friday", "Gazetted"), ("2024-04-09", "Ugadi / Gudi Padwa", "Festival"),
    ("2024-04-11", "Id-ul-Fitr", "Gazetted"), ("2024-04-17", "Ram Navami", "Festival"),
    ("2024-04-21", "Mahavir Jayanti", "Gazetted"), ("2024-05-23", "Buddha Purnima", "Gazetted"),
    ("2024-06-17", "Id-ul-Zuha (Bakrid)", "Gazetted"), ("2024-07-17", "Muharram", "Gazetted"),
    ("2024-08-15", "Independence Day", "Gazetted"), ("2024-08-26", "Janmashtami", "Festival"),
    ("2024-09-07", "Ganesh Chaturthi", "Festival"), ("2024-09-16", "Milad-un-Nabi", "Gazetted"),
    ("2024-10-02", "Gandhi Jayanti", "Gazetted"), ("2024-10-12", "Dussehra (Vijaya Dashami)", "Gazetted"),
    ("2024-10-31", "Diwali (Deepavali)", "Gazetted"), ("2024-11-15", "Guru Nanak Jayanti", "Gazetted"),
    ("2024-12-25", "Christmas", "Gazetted"),
    ("2025-01-14", "Makar Sankranti / Pongal", "Festival"), ("2025-01-26", "Republic Day", "Gazetted"),
    ("2025-02-26", "Maha Shivaratri", "Festival"), ("2025-03-14", "Holi", "Festival"),
    ("2025-03-30", "Ugadi / Gudi Padwa", "Festival"), ("2025-03-31", "Id-ul-Fitr", "Gazetted"),
    ("2025-04-06", "Ram Navami", "Festival"), ("2025-04-10", "Mahavir Jayanti", "Gazetted"),
    ("2025-04-18", "Good Friday", "Gazetted"), ("2025-05-12", "Buddha Purnima", "Gazetted"),
    ("2025-06-07", "Id-ul-Zuha (Bakrid)", "Gazetted"), ("2025-07-06", "Muharram", "Gazetted"),
    ("2025-08-15", "Independence Day", "Gazetted"), ("2025-08-16", "Janmashtami", "Festival"),
    ("2025-08-27", "Ganesh Chaturthi", "Festival"), ("2025-09-05", "Milad-un-Nabi", "Gazetted"),
    ("2025-10-02", "Gandhi Jayanti / Dussehra", "Gazetted"), ("2025-10-20", "Diwali (Deepavali)", "Gazetted"),
    ("2025-11-05", "Guru Nanak Jayanti", "Gazetted"), ("2025-12-25", "Christmas", "Gazetted"),
    ("2026-01-14", "Makar Sankranti / Pongal", "Festival"), ("2026-01-26", "Republic Day", "Gazetted"),
]


def hash_password(pw):
    return hashlib.sha256(("rxbounce::" + pw).encode()).hexdigest()


def save(df, name):
    df.to_csv(OUT / f"{name}.csv", index=False)
    print(f"  {name:<22} {len(df):>8,} rows")


def build():
    rng = np.random.default_rng(config.SEED)
    df = build_history()
    sales = df[df.typeofsales == "Sale"].copy()
    rets = df[df.typeofsales == "Return"].copy()
    all_dates = pd.date_range(config.DATA_START, config.DATA_END)
    span = len(all_dates)

    # ---------------- master data ----------------
    depts = sorted(df.dept.unique())
    dept_map = {d: f"DEP{i+1:02d}" for i, d in enumerate(depts)}
    departments = pd.DataFrame({"dept_id": list(dept_map.values()), "dept_name": list(dept_map.keys())})

    specs = sorted(df.specialisation.unique(), key=lambda s: int("".join(c for c in s if c.isdigit()) or 0))
    spec_map = {s: f"SPC{i+1:02d}" for i, s in enumerate(specs)}
    spec_dept = df.groupby("specialisation").dept.agg(lambda x: x.mode().iat[0])
    specialisations = pd.DataFrame({"spec_id": [spec_map[s] for s in specs], "spec_name": specs,
                                    "dept_id": [dept_map[spec_dept[s]] for s in specs]})

    doc_rows, spec_docs, n = [], {}, 0
    lines_per_spec = sales.specialisation.value_counts()
    for s in specs:
        k = int(np.clip(1 + lines_per_spec.get(s, 0) // 800, 1, 4))
        spec_docs[s] = []
        for _ in range(k):
            n += 1
            did = f"DOC{n:03d}"
            spec_docs[s].append(did)
            doc_rows.append((did, f"Dr. {rng.choice(FIRST)} {rng.choice(LAST)}", spec_map[s]))
    doctors = pd.DataFrame(doc_rows, columns=["doctor_id", "doctor_name", "spec_id"])

    named = df[df.drugname != "UNSPECIFIED ITEM"]
    mode = lambda x: x.mode().iat[0]
    g = named.groupby("drugname").agg(subcat=("subcat", mode), subcat1=("subcat1", mode),
                                      formulation=("formulation", mode))
    s_agg = sales[sales.drugname != "UNSPECIFIED ITEM"].groupby("drugname").agg(
        qty=("quantity", "sum"), cost=("final_cost", "sum"), rev=("final_sales", "sum"))
    r_agg = rets[rets.drugname != "UNSPECIFIED ITEM"].groupby("drugname").agg(rq=("returnquantity", "sum"),
                                                                             rv=("rtnmrp", "sum"))
    g = g.join(s_agg).join(r_agg).fillna(0)
    g["unit_mrp"] = np.where(g.qty > 0, g.rev / g.qty.replace(0, 1), g.rv / g.rq.replace(0, 1)).round(2)
    g["unit_cost"] = np.where(g.qty > 0, g.cost / g.qty.replace(0, 1), g.unit_mrp * 0.8).round(2)
    g["net_sales"] = g.rev - g.rv
    g = g.sort_values("net_sales", ascending=False)
    share = g.net_sales.clip(lower=0).cumsum() / g.net_sales.clip(lower=0).sum()
    g["abc_class"] = np.where(share <= 0.80, "A", np.where(share <= 0.95, "B", "C"))
    g = g.reset_index().rename(columns={"drugname": "drug_name"})
    g.insert(0, "drug_id", [f"DRG{i+1:04d}" for i in range(len(g))])
    g["is_formulary"] = 1

    us = sales[sales.drugname == "UNSPECIFIED ITEM"]
    u_mrp = round(us.final_sales.sum() / max(1, us.quantity.sum()), 2)
    unspecified = pd.DataFrame([{"drug_id": "DRG0000", "drug_name": "UNSPECIFIED ITEM", "subcat": "GENERAL",
                                 "subcat1": "GENERAL", "formulation": "Unknown", "abc_class": "C",
                                 "unit_mrp": u_mrp, "unit_cost": round(u_mrp * 0.8, 2), "is_formulary": 1}])
    subcat_med = g.groupby("subcat").unit_mrp.median()
    nf = pd.DataFrame(NON_FORMULARY, columns=["drug_name", "subcat", "subcat1"])
    nf = nf[~nf.drug_name.isin(g.drug_name)]
    nf["drug_id"] = [f"DRG{9001+i}" for i in range(len(nf))]
    nf["formulation"] = "Form1"
    nf["abc_class"] = "C"
    nf["unit_mrp"] = nf.subcat.map(subcat_med).fillna(60).round(2)
    nf["unit_cost"] = (nf.unit_mrp * 0.78).round(2)
    nf["is_formulary"] = 0

    cols = ["drug_id", "drug_name", "formulation", "subcat", "subcat1", "abc_class", "unit_cost", "unit_mrp",
            "is_formulary"]
    drugs = pd.concat([unspecified[cols], g[cols], nf[cols]], ignore_index=True)
    parsed = drugs.drug_name.map(parse_drug)
    drugs["salt_composition"] = parsed.str[0]
    drugs["strength"] = parsed.str[1]
    drugs["pack_size"] = np.where(drugs.subcat == "TABLETS & CAPSULES", 10, 1)
    drugs["is_cold_chain"] = (drugs.drug_name.str.contains(COLD_RE) | (drugs.subcat == "VACCINE")).astype(int)
    drugs = drugs[["drug_id", "drug_name", "salt_composition", "strength", "formulation", "subcat", "subcat1",
                   "abc_class", "unit_cost", "unit_mrp", "pack_size", "is_formulary", "is_cold_chain"]]
    name2id = dict(zip(drugs.drug_name, drugs.drug_id))

    suppliers = pd.DataFrame(SUPPLIERS, columns=["supplier_id", "supplier_name", "category_served",
                                                 "supplier_type", "base_lead_time_days"])
    suppliers["on_time_rate"] = [round(float(x), 2) for x in rng.uniform(0.82, 0.97, len(suppliers))]
    base = dict(zip(suppliers.supplier_id, suppliers.base_lead_time_days))
    ds = []
    for d in drugs[(drugs.is_formulary == 1) & (drugs.drug_id != "DRG0000")].itertuples():
        if d.is_cold_chain:
            s = "SUP07"
        elif d.unit_cost > 2000:
            s = "SUP08"
        elif d.subcat.startswith("IV FLUIDS"):
            s = "SUP01"
        elif d.subcat == "INJECTIONS":
            s = "SUP02" if rng.random() < 0.7 else "SUP03"
        elif d.subcat == "TABLETS & CAPSULES":
            s = "SUP04" if rng.random() < 0.6 else "SUP05"
        else:
            s = "SUP06"
        m = max(1, round(base[s] + rng.normal(0, 1)))
        ds.append((d.drug_id, s, m, round(m * rng.uniform(0.2, 0.4), 1), int(d.pack_size)))
    drug_supplier = pd.DataFrame(ds, columns=["drug_id", "supplier_id", "lead_time_mean", "lead_time_sd",
                                              "min_order_qty"])

    holidays = pd.DataFrame(HOLIDAYS, columns=["holiday_date", "holiday_name", "holiday_type"])
    holidays["holiday_date"] = pd.to_datetime(holidays.holiday_date)
    cal = pd.DataFrame({"cal_date": all_dates})
    cal["day_name"] = cal.cal_date.dt.day_name()
    cal["week_no"] = cal.cal_date.dt.isocalendar().week.astype(int)
    cal["month_no"] = cal.cal_date.dt.month
    cal["month_name"] = cal.cal_date.dt.strftime("%b")
    cal["quarter"] = cal.cal_date.dt.quarter
    cal["year_no"] = cal.cal_date.dt.year
    cal["is_weekend"] = (cal.cal_date.dt.weekday >= 5).astype(int)
    hmap = dict(zip(holidays.holiday_date, holidays.holiday_name))
    cal["is_holiday"] = cal.cal_date.isin(hmap).astype(int)
    cal["holiday_name"] = cal.cal_date.map(hmap)

    # ---------------- transactions ----------------
    sales["spec_id"] = sales.specialisation.map(spec_map)
    sales["dept_id"] = sales.dept.map(dept_map)
    sales["drug_id"] = sales.drugname.map(name2id)
    keys = sales.groupby(["date", "patient_id", "spec_id"]).size().reset_index()[["date", "patient_id", "spec_id"]]
    keys["rx_id"] = [f"RX{i+1:06d}" for i in range(len(keys))]
    sales = sales.merge(keys, on=["date", "patient_id", "spec_id"])
    spec_doc_by_id = {spec_map[s]: v for s, v in spec_docs.items()}
    keys["doctor_id"] = [spec_doc_by_id[s][int(p) % len(spec_doc_by_id[s])] for p, s in zip(keys.patient_id, keys.spec_id)]
    sales = sales.sort_values(["date", "rx_id"]).reset_index(drop=True)
    sales["txn_id"] = [f"TXN{i+1:06d}" for i in range(len(sales))]
    sales_transactions = sales[["txn_id", "rx_id", "patient_id", "drug_id", "spec_id", "dept_id", "date",
                                "quantity", "final_cost", "final_sales"]].rename(columns={"date": "txn_date"})

    rets = rets.sort_values("date").reset_index(drop=True)
    returns = pd.DataFrame({"return_id": [f"RET{i+1:05d}" for i in range(len(rets))],
                            "patient_id": rets.patient_id, "drug_id": rets.drugname.map(name2id),
                            "spec_id": rets.specialisation.map(spec_map), "dept_id": rets.dept.map(dept_map),
                            "return_date": rets.date, "return_qty": rets.returnquantity, "rtn_mrp": rets.rtnmrp})

    # ---------------- requests at the counter that were not in the sales records ----------------
    stocked = drugs[(drugs.is_formulary == 1) & (drugs.drug_id != "DRG0000")].drug_id
    hist = sales[sales.drug_id.isin(stocked) & (sales.quantity > 0)]
    rx_by_date = keys.groupby("date").rx_id.apply(list).to_dict()
    extra = []
    lam = 0.70
    for drug, grp in hist.groupby("drug_id"):
        k = rng.poisson(lam * len(grp) + 0.3)
        if k == 0:
            continue
        dts = rng.choice(grp.date.values, k) + rng.integers(-7, 8, k).astype("timedelta64[D]")
        qtys = rng.choice(grp.quantity.values, k)
        for dt, q in zip(pd.to_datetime(dts), qtys):
            dt = min(max(dt, all_dates[0]), all_dates[-1])
            # unmet demand grew steadily over the period (the rising bounce rate)
            if rng.random() < 0.25 + 0.75 * (dt - all_dates[0]).days / span:
                extra.append((drug, dt, int(q)))
    for drug in drugs[drugs.is_formulary == 0].drug_id:
        for dt in rng.choice(all_dates, rng.poisson(8 * span / 365)):
            extra.append((drug, pd.Timestamp(dt), int(rng.choice([1, 1, 2, 10]))))
    extra = pd.DataFrame(extra, columns=["drug_id", "date", "qty"])
    extra["rx_id"] = [rng.choice(rx_by_date[d]) if d in rx_by_date else None for d in extra.date]
    new_rx = []
    pts = keys[["patient_id", "spec_id", "doctor_id"]].drop_duplicates("patient_id").reset_index(drop=True)
    for i in extra.index[extra.rx_id.isna()]:
        p = pts.iloc[rng.integers(len(pts))]
        rid = f"RX{len(keys) + len(new_rx) + 1:06d}"
        new_rx.append((extra.at[i, "date"], p.patient_id, p.spec_id, rid, p.doctor_id))
        extra.at[i, "rx_id"] = rid
    keys = pd.concat([keys, pd.DataFrame(new_rx, columns=keys.columns)], ignore_index=True)

    lines_hist = pd.DataFrame({"rx_id": sales.rx_id, "drug_id": sales.drug_id.fillna("DRG0000"),
                               "date": sales.date, "qty": sales.quantity.astype(int), "txn_id": sales.txn_id,
                               "is_hist": True})
    lines_extra = extra.assign(txn_id=None, is_hist=False)[["rx_id", "drug_id", "date", "qty", "txn_id", "is_hist"]]
    lines = pd.concat([lines_hist, lines_extra], ignore_index=True).sort_values(["date", "rx_id"]).reset_index(drop=True)
    lines["req_id"] = [f"RXI{i+1:06d}" for i in range(len(lines))]

    # ---------------- replay the whole period under the old ordering policy ----------------
    ab = drugs.set_index("drug_id")
    daily_dem = hist.groupby("drug_id").quantity.sum() / span
    cover = {"A": 30, "B": 40, "C": 55}
    opening = {}
    for d in stocked:
        mu = daily_dem.get(d, 0)
        opening[d] = 0 if rng.random() < 0.05 else max(1, math.ceil(mu * cover[ab.at[d, "abc_class"]] * rng.uniform(0.4, 1.4)))
    params = drug_supplier.set_index("drug_id").loc[list(stocked)]
    params["pack_size"] = params.min_order_qty
    req = lines[lines.drug_id.isin(stocked)][["req_id", "date", "drug_id", "qty", "is_hist"]]
    ret_q = returns[returns.drug_id.isin(stocked)].rename(columns={"return_date": "date", "return_qty": "qty"})
    daily, outcomes, pos = replay(req, ret_q, params, config.DATA_START, config.DATA_END, opening,
                                  policy="baseline", seed=config.SEED)

    disp = dict(zip(outcomes.req_id, outcomes.qty_dispensed))
    lines["qty_dispensed"] = [int(disp.get(r, q if h else 0)) for r, q, h in zip(lines.req_id, lines.qty, lines.is_hist)]
    nf_ids = set(drugs[drugs.is_formulary == 0].drug_id)
    lines["status"] = np.where(lines.qty_dispensed >= lines.qty, "Fulfilled",
                               np.where(lines.qty_dispensed > 0, "Partial", "Bounced"))
    lines["bounce_reason"] = np.select(
        [lines.status == "Fulfilled", lines.drug_id.isin(nf_ids), lines.status == "Partial"],
        [None, "Not stocked", "Insufficient quantity"], default="Out of stock")
    prescription_items = lines.rename(columns={"req_id": "rx_item_id", "qty": "qty_requested"})[
        ["rx_item_id", "rx_id", "drug_id", "qty_requested", "qty_dispensed", "status", "bounce_reason", "txn_id"]]
    prescription_items["substitute_drug_id"] = None

    prescriptions = keys.rename(columns={"date": "rx_date"})[["rx_id", "patient_id", "doctor_id", "spec_id", "rx_date"]]
    prescriptions["source"] = "Pharmacy records"
    prescriptions = prescriptions.sort_values(["rx_date", "rx_id"])

    patients = pd.concat([prescriptions[["patient_id", "rx_date"]],
                          returns[["patient_id", "return_date"]].rename(columns={"return_date": "rx_date"})])
    patients = patients.groupby("patient_id").agg(first_visit_date=("rx_date", "min"),
                                                  visit_count=("rx_date", "nunique")).reset_index()

    users = pd.DataFrame([
        (1, "manager", hash_password("manager123"), "Pharmacy Manager", "manager"),
        (2, "pharmacist", hash_password("pharma123"), "Counter Pharmacist", "pharmacist"),
    ], columns=["user_id", "username", "password_hash", "full_name", "role"])

    print("[build] tables written to data/processed:")
    for name, t in [("departments", departments), ("specialisations", specialisations), ("doctors", doctors),
                    ("patients", patients), ("drugs", drugs), ("suppliers", suppliers),
                    ("drug_supplier", drug_supplier), ("holidays", holidays), ("calendar", cal),
                    ("prescriptions", prescriptions), ("sales_transactions", sales_transactions),
                    ("returns", returns), ("prescription_items", prescription_items), ("users", users)]:
        save(t, name)
    daily.to_csv(OUT / "daily_stock_baseline.csv", index=False)
    lines.merge(prescriptions[["rx_id", "spec_id"]], on="rx_id").to_csv(OUT / "demand_lines.csv", index=False)
    pos.to_csv(OUT / "replay_orders.csv", index=False)
    pre = lines.date < pd.Timestamp(config.GO_LIVE)
    print(f"[build] prescription lines={len(lines):,}  bounce rate before go-live="
          f"{(lines[pre].status != 'Fulfilled').mean():.1%}")


if __name__ == "__main__":
    build()

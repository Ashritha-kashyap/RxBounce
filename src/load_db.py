"""Step 7 - Create the MySQL schema and load every table."""
import pandas as pd
import config
from src import db

ORDER = ["departments", "specialisations", "doctors", "patients", "drugs", "suppliers", "drug_supplier", "holidays",
         "calendar", "prescriptions", "sales_transactions", "returns", "prescription_items", "purchase_orders",
         "po_items", "daily_stock", "stock_on_hand", "inventory_batches", "drug_substitutes", "forecasts",
         "reorder_policy", "alerts", "model_metrics", "feature_importance", "simulation_results",
         "simulation_breakdown", "model_ablation", "sensitivity_results", "users"]
DATE_COLS = {"patients": ["first_visit_date"], "holidays": ["holiday_date"], "calendar": ["cal_date"],
             "prescriptions": ["rx_date"], "sales_transactions": ["txn_date"], "returns": ["return_date"],
             "purchase_orders": ["order_date", "expected_date", "received_date"], "daily_stock": ["stock_date"],
             "stock_on_hand": ["updated_at"], "inventory_batches": ["received_date", "mfg_date", "expiry_date"],
             "forecasts": ["week_start"], "reorder_policy": ["updated_at"], "alerts": ["created_at"]}


def run():
    eng = db.get_engine()
    mysql = db.is_mysql()
    if mysql:
        db.run_sql_file(config.ROOT / "sql" / "01_schema.sql")
    print(f"[db] loading into {eng.url.render_as_string(hide_password=True)}")
    for t in ORDER:
        df = pd.read_csv(config.PROCESSED / f"{t}.csv", parse_dates=DATE_COLS.get(t, []))
        df = df.astype(object).where(df.notna(), None)
        df.to_sql(t, eng, if_exists="append" if mysql else "replace", index=False, chunksize=2000, method="multi")
        print(f"  {t:<22} {len(df):>8,} rows")
    if mysql:
        db.run_sql_file(config.ROOT / "sql" / "02_views.sql")
    print("[db] done")


if __name__ == "__main__":
    run()

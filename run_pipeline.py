"""Run the full RxBounce pipeline end to end.

    python run_pipeline.py            # build data, train models, run impact study, load MySQL
    python run_pipeline.py --no-db    # everything except loading MySQL
"""
import sys
import time

from src import build_tables, substitutes, train_forecast, train_risk, simulate, decision_tables, load_db

STEPS = [
    ("Build pharmacy history and relational tables", build_tables.build),
    ("Substitute recommender", substitutes.run),
    ("Demand forecasting model", train_forecast.train),
    ("Stockout risk model", train_risk.train),
    ("Impact study and live records", simulate.run),
    ("Reorder policy and alerts", decision_tables.run),
]

if __name__ == "__main__":
    if "--no-db" not in sys.argv:
        STEPS.append(("Load MySQL database", load_db.run))
    for i, (name, fn) in enumerate(STEPS, 1):
        t = time.time()
        print(f"\n=== Step {i}/{len(STEPS)}: {name} ===")
        fn()
        print(f"--- done in {time.time() - t:.1f}s")
    print("\nPipeline complete. Start the app with:  streamlit run app/app.py")

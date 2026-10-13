# RxBounce: Reducing Pharmacy Bounce Rate with ML

A hospital pharmacy loses patients and revenue every time a prescribed item cannot be dispensed (a **bounce**).
RxBounce forecasts demand, flags shortages before they happen, plans the orders that prevent them and offers
in-stock substitutes at the counter. Inventory optimization is one part of this bounce-reduction system.

**Stack:** Python · MySQL 8 · SQLAlchemy/PyMySQL · pandas · scikit-learn · LightGBM · SHAP · Streamlit · Plotly · Power BI

---

## 1. Business understanding (CRISP-ML(Q))

| | |
|---|---|
| Business problem | Bounce rate is rising, leading to patient dissatisfaction and lost sales |
| Objective | Minimise bounce rate |
| Constraint | Minimise inventory cost |
| Business success criterion | Reduce bounce rate by at least 30% |
| Economic success criterion | Increase revenue by at least ₹20 lakh |

**Bounce rate** = prescription lines not fully dispensed ÷ total prescription lines.

**Timeline:** pharmacy history from Jan 2024 to Jan 2026. RxBounce went live on **1 Aug 2025**.
Models are trained on data before go-live and evaluated on the six months after it.

## 2. How the solution works

| Root cause of a bounce | What RxBounce does |
|---|---|
| Demand exceeds stock | Demand forecast (LightGBM) sets a reorder level for every drug |
| Shortage noticed too late | 7-day stockout-risk model flags drugs to order today |
| Item short, but an equivalent exists | Substitute recommender offers an in-stock alternative at the counter |
| Stock present but expired | Expiry monitor and first-expiry-first-out dispensing |

## 3. Results (Aug 2025 to Jan 2026, same prescriptions in every scenario)

| | Old policy | ML reorder | ML reorder + substitutes |
|---|---|---|---|
| Bounce rate | 9.8% | 3.0% | **2.1%** |
| Bounce reduction | – | 70% | **79%** |
| Revenue recovered per year | – | ₹4.15 L | **₹4.70 L** |
| Net gain per year after extra stock cost | – | ₹2.33 L | **₹2.88 L** |
| Emergency purchases | 1,532 | 373 | 373 |

* Business criterion (≥30% lower bounce rate): **met**.
* Economic criterion (₹20 L): one pharmacy recovers ₹4.70 L a year, so 5 pharmacies of similar size reach ₹20 L.

### How solid is the result?

**What each part contributes (ablation).** The same reorder rules were also run with a simple 4-week
moving-average forecast instead of LightGBM:

| Setup | Bounce rate | Lower than old policy | Average stock value |
|---|---|---|---|
| Old policy | 9.8% | – | ₹6.23 L |
| Reorder rules + moving-average forecast | 2.9% | 71% | ₹8.48 L |
| Reorder rules + LightGBM forecast | 3.0% | 70% | ₹8.34 L |
| LightGBM + substitutes | 2.1% | 79% | ₹8.34 L |

Most of the improvement comes from the forecast-driven reorder rules (safety stock, reorder level and weekly
review). On this data a moving-average forecast gives a similar bounce rate; LightGBM reaches it with
slightly less stock. The substitute recommender adds a further 9 points.

**Under harder conditions (sensitivity).** Old policy and RxBounce rerun side by side:

| Condition | Old policy | RxBounce | Lower by | 30% target |
|---|---|---|---|---|
| Base case | 9.9% | 2.0% | 80% | Met |
| Patients accept half as many substitutes | 9.9% | 2.4% | 75% | Met |
| 20% more demand than forecast | 14.1% | 3.4% | 76% | Met |
| Suppliers 50% slower than planned | 10.4% | 2.7% | 74% | Met |

Model accuracy after go-live:

| Demand forecast | MAE | RMSE | WAPE |
|---|---|---|---|
| **LightGBM (Tweedie)**, used | 0.975 | 4.788 | 0.818 |
| Random Forest | 1.041 | 4.713 | 0.874 |
| Naive (last week) | 1.094 | 5.515 | 0.918 |
| Moving average (4 weeks) | 1.118 | 5.156 | 0.938 |

| Stockout risk (7 days) | ROC-AUC | Recall | Precision |
|---|---|---|---|
| **LightGBM**, used | 0.957 | 0.862 | 0.360 |
| Random Forest | 0.953 | 0.843 | 0.362 |
| Logistic Regression | 0.948 | 0.885 | 0.285 |

Figures come from `python run_pipeline.py` and may differ slightly on another machine.

## 4. Pipeline

```
data/raw/Medical_Inventory_Optimaization_Dataset.xlsx
   │  src/clean.py          de-duplicate, fix line breaks, parse 3 date formats
   │  src/history.py        Jan 2024 to Jan 2026 history from the file's monthly bills
   ▼
src/build_tables.py         27 relational tables, replayed under the old ordering policy
src/substitutes.py          salt/strength parsing + TF-IDF → drug_substitutes
src/train_forecast.py       weekly demand forecast (LightGBM vs baselines)
src/train_risk.py           7-day stockout classifier + SHAP
src/simulate.py             impact study, then live records after go-live
src/decision_tables.py      reorder suggestions, alerts, model metrics
src/load_db.py              → MySQL (sql/01_schema.sql, sql/02_views.sql)
   ▼
Streamlit app (app/)  +  Power BI (connects to the MySQL views)
```

## 5. Run it (Windows, VS Code)

First time only:
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
In MySQL Workbench:
```sql
CREATE DATABASE IF NOT EXISTS pharmacy_bounce;
CREATE USER IF NOT EXISTS 'rxapp'@'localhost' IDENTIFIED BY 'rxpass123';
GRANT ALL PRIVILEGES ON pharmacy_bounce.* TO 'rxapp'@'localhost';
FLUSH PRIVILEGES;
```
Copy `.env.example` to `.env`, then build everything (5 to 10 minutes):
```powershell
python run_pipeline.py
```
Every day after that: double-click `start_app.bat`, or run `streamlit run app/app.py`.

| Login | Password | Sees |
|---|---|---|
| manager | manager123 | All pages |
| pharmacist | pharma123 | Home, Pharmacy counter, Expiry monitor |

## 6. App pages

| Page | Purpose |
|---|---|
| Home | Bounce rate before and after go-live, bounces prevented, revenue recovered |
| Demand forecast | Actual vs forecast weekly demand per drug, reorder level |
| Stockout risk & reorder | Drugs likely to run short in 7 days; raise purchase orders per supplier |
| Pharmacy counter | Check a prescription, offer substitutes, dispense and record bounces |
| Expiry monitor | Stock value by time to expiry and the lots to act on |
| Impact study | Old policy vs RxBounce: bounce rate, revenue, costs, ₹20 L chain target |
| Admin | Users, table counts, rerun the pipeline |

## 7. ER diagram and Power BI

* ER diagram: MySQL Workbench → **Database → Reverse Engineer…** → `pharmacy_bounce`.
* Power BI: **Get Data → MySQL database** → `localhost`, `pharmacy_bounce`; use `v_prescription_lines`,
  `v_bounce_monthly` and `v_inventory_status`.

## 8. Key parameters (config.py)

Go-live date, service level by ABC class (95/90/85%), review days, holding rate (20% + 8% cold chain),
ordering cost (₹500 per PO), emergency purchase premium (15%), substitute acceptance rates.
Change a value and rerun `python run_pipeline.py`.

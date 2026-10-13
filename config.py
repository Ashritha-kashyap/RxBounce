"""Central configuration for the RxBounce project."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:password@localhost:3306/pharmacy_bounce")

RAW_FILE = ROOT / "data" / "raw" / "Medical_Inventory_Optimaization_Dataset.xlsx"
PROCESSED = ROOT / "data" / "processed"
MODELS = ROOT / "models"
REPORTS = ROOT / "reports"
for p in (PROCESSED, MODELS, REPORTS):
    p.mkdir(parents=True, exist_ok=True)

SEED = 42

# ---------------- time line ----------------
DATA_START = "2024-01-01"
DATA_END = "2026-01-31"
GO_LIVE = "2025-08-01"      # RxBounce switched on. Models are trained before it and evaluated after it.
AS_OF = DATA_END            # "today" inside the application
TEST_START = GO_LIVE
YEAR_START, YEAR_END = DATA_START, DATA_END

# ---------------- transaction history ----------------
VOLUME_GROWTH = 0.06        # yearly growth in prescriptions
PRICE_INFLATION = 0.05      # yearly drug price rise
NEW_PATIENT_SHARE = 0.30    # share of bills from patients not seen in the source file

# ---------------- inventory policy ----------------
Z_BY_ABC = {"A": 1.65, "B": 1.28, "C": 1.04}          # service level 95% / 90% / 85%
REVIEW_DAYS_BY_ABC = {"A": 14, "B": 21, "C": 30}      # cycle stock horizon for the order-up-to level
REVIEW_WEEKDAYS_BY_ABC = {"A": (0, 3), "B": (0,), "C": (0,)}   # Mon & Thu for A items, Mon for B/C
HOLDING_RATE = 0.20
COLD_CHAIN_SURCHARGE = 0.08
ORDER_COST = 500            # INR per purchase order (one supplier, one day)
EMERGENCY_PREMIUM = 0.15    # local emergency purchase costs 15% above normal
NEAR_EXPIRY_DAYS = 90

# Probability a patient accepts a substitute, by match type
SUBSTITUTE_ACCEPTANCE = {
    "Same salt & strength": 0.90,
    "Same salt, different strength": 0.60,
    "Therapeutic alternative": 0.30,
}
RISK_THRESHOLD = 0.5

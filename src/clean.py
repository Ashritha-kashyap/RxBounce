"""Step 1a - Clean the client's pharmacy transaction file.

Fixes found during EDA:
  * line breaks / double spaces inside text columns (broke rows on import)
  * 26 exact duplicate rows
  * three mixed date formats (Excel dates, M/D/YYYY, text timestamps)
"""
import pandas as pd
import config

TEXT_COLS = ["Typeofsales", "Specialisation", "Dept", "Formulation", "DrugName", "SubCat", "SubCat1"]


def load_clean(verbose=True):
    raw = pd.read_excel(config.RAW_FILE)
    n_raw = len(raw)
    for c in TEXT_COLS:
        raw[c] = raw[c].astype("string").str.replace(r"\s+", " ", regex=True).str.strip()
    raw = raw.drop_duplicates()
    raw["Date"] = pd.to_datetime(raw["Dateofbill"].astype(str), format="mixed").dt.normalize()
    raw["DrugName"] = raw["DrugName"].fillna("UNSPECIFIED ITEM")
    raw["SubCat"] = raw["SubCat"].fillna("GENERAL")
    raw["SubCat1"] = raw["SubCat1"].fillna("GENERAL")
    raw["Formulation"] = raw["Formulation"].fillna("Unknown")
    df = raw.drop(columns=["Dateofbill"]).rename(columns=str.lower)
    df = df.sort_values("date").reset_index(drop=True)
    for c in df.select_dtypes("string").columns:
        df[c] = df[c].astype(object)
    if verbose:
        print(f"[clean] raw rows={n_raw}, after de-duplication={len(df)}")
    return df


if __name__ == "__main__":
    load_clean()

"""Step 2 - Substitute recommender.

When a prescribed item is unavailable, suggest an equivalent that IS in stock.
Tier 1  Same salt & strength          -> pharmacist can switch directly
Tier 2  Same salt, different strength -> dose adjustment, pharmacist confirms
Tier 3  Therapeutic alternative       -> same therapeutic class + similar salts, doctor approval
All tiers must share the dosage-form group (an injection is never swapped for a syrup).
"""
import re
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

STRENGTH_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:MG|MCG|GM|G|ML|IU|MIU|%|UNITS?|MEQ|L|LAC)(?![A-Z])(?:\s*/\s*\d*(?:\.\d+)?\s*(?:ML|G|GM|L|DOSE)(?![A-Z]))?"
)
FORM_WORDS = {
    "INJ", "INJECTION", "TAB", "TABS", "TABLET", "CAP", "CAPS", "CAPSULE", "SYP", "SYRUP", "IVF", "IV", "FLUID",
    "DROPS", "DROP", "CREAM", "GEL", "OINT", "OINTMENT", "SUSP", "SUSPENSION", "RESPULES", "RESPULE", "INHALER",
    "SACHET", "SPRAY", "PATCH", "LOTION", "SUPPOSITORY", "SOLUTION", "SOLN", "POWDER", "VIAL", "AMP", "W/V",
    "W/W", "V/V", "BAG", "BOTTLE", "PFS", "SR", "ER", "XR", "MR", "DT", "ORAL", "NASAL", "EYE", "EAR", "TOPICAL",
    "FOR", "AND", "WITH", "IN", "OF", "PLAIN", "FORTE", "KIT", "RTU", "PREFILLED", "SYRINGE", "PEN", "INFUSION",
}


def parse_drug(name):
    """Return (salt_composition, strength) parsed from a generic drug name."""
    name = str(name).upper()
    salts, strengths = [], []
    for part in name.split("+"):
        strengths += [s.replace(" ", "") for s in STRENGTH_RE.findall(part)]
        cleaned = STRENGTH_RE.sub(" ", part)
        tokens = [t for t in re.findall(r"[A-Z][A-Z0-9\-]*", cleaned) if t not in FORM_WORDS and len(t) > 1]
        if tokens:
            salts.append(" ".join(tokens))
    salt = " + ".join(sorted(set(salts))) or name
    return salt, " + ".join(strengths)


def build_substitutes(drugs, top_k=3):
    pool = drugs[(drugs.is_formulary == 1) & (drugs.drug_id != "DRG0000")].reset_index(drop=True)
    src = drugs[drugs.drug_id != "DRG0000"].reset_index(drop=True)
    vec = TfidfVectorizer(analyzer="word", token_pattern=r"[A-Z][A-Z0-9\-]+", lowercase=False)
    vec.fit(pd.concat([pool.salt_composition, src.salt_composition]))
    sim = cosine_similarity(vec.transform(src.salt_composition), vec.transform(pool.salt_composition))
    p_ids, p_salt, p_str = pool.drug_id.values, pool.salt_composition.values, pool.strength.fillna("").values
    p_sub, p_sub1 = pool.subcat.values, pool.subcat1.values

    rows = []
    for i, d in src.iterrows():
        cands = []
        for j in range(len(pool)):
            if p_ids[j] == d.drug_id or p_sub[j] != d.subcat:
                continue
            if p_salt[j] == d.salt_composition:
                same = p_str[j] == (d.strength if isinstance(d.strength, str) else "")
                mt, score = ("Same salt & strength", 1.0) if same else ("Same salt, different strength", 0.9)
            elif p_sub1[j] == d.subcat1 and p_sub1[j] != "GENERAL" and sim[i, j] >= 0.35:
                mt, score = "Therapeutic alternative", float(sim[i, j]) * 0.8
            else:
                continue
            cands.append((score, p_ids[j], mt, round(float(sim[i, j]), 3)))
        cands.sort(reverse=True)
        for rank, (_, pid, mt, s) in enumerate(cands[:top_k], start=1):
            rows.append({"drug_id": d.drug_id, "substitute_drug_id": pid, "match_type": mt,
                         "similarity": s, "rank_no": rank})
    return pd.DataFrame(rows)


def run():
    import config
    drugs = pd.read_csv(config.PROCESSED / "drugs.csv")
    subs = build_substitutes(drugs)
    subs.to_csv(config.PROCESSED / "drug_substitutes.csv", index=False)
    best = subs[subs.rank_no == 1].set_index("drug_id").match_type
    d = drugs[drugs.drug_id != "DRG0000"]
    cov = d.drug_id.map(best).fillna("No substitute").value_counts()
    cov.rename_axis("best_match").reset_index(name="drugs").to_csv(config.REPORTS / "substitute_coverage.csv", index=False)
    print(f"[substitutes] {len(subs):,} substitute links for {subs.drug_id.nunique()} drugs")
    return subs


if __name__ == "__main__":
    run()

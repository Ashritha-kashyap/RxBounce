import pandas as pd
import streamlit as st

import ui
from src import services

ui.page_header("Pharmacy counter",
               "Check each line before dispensing. If an item is short, offer an in-stock substitute.")

drugs = ui.drugs()
drugs = drugs[drugs.drug_id != "DRG0000"]
name_to_id = dict(zip(drugs.drug_name, drugs.drug_id))
docs = ui.doctors()

# ---------------- 1. patient and doctor ----------------
with st.container(border=True):
    c1, c2, c3 = st.columns([1, 1.3, 1.8])
    mode = c1.radio("Patient", ["Existing", "New"], horizontal=True)
    if mode == "New":
        patient_id = c2.number_input("New patient ID", min_value=1, value=99000000001, step=1, format="%d")
    else:
        patient_id = c2.selectbox("Patient ID", ui.patient_ids(), index=0)
    doc_label = docs.doctor_name + " (" + docs.spec_name + ")"
    doc_idx = c3.selectbox("Prescribing doctor", range(len(docs)), format_func=lambda i: doc_label.iat[i])
    doctor = docs.iloc[doc_idx]

# ---------------- 2. prescription lines ----------------
st.subheader("Prescription lines")
if "rx_lines" not in st.session_state:
    st.session_state.rx_lines = pd.DataFrame({"Drug": [None], "Quantity": [1]})
edited = st.data_editor(
    st.session_state.rx_lines, num_rows="dynamic", width="stretch", key="rx_editor",
    column_config={"Drug": st.column_config.SelectboxColumn("Drug", options=sorted(name_to_id), required=True,
                                                            width="large"),
                   "Quantity": st.column_config.NumberColumn("Quantity", min_value=1, step=1, required=True)})

if st.button("Check availability", type="primary"):
    lines = edited.dropna(subset=["Drug"])
    if lines.empty:
        st.warning("Add at least one drug to the prescription.")
    else:
        req = pd.DataFrame({"drug_id": lines.Drug.map(name_to_id), "qty": lines.Quantity.astype(int)})
        chk = services.check_availability(req)
        chk.insert(1, "drug_name", lines.Drug.values)
        chk["use_substitute"] = chk.substitute_id.notna()
        st.session_state.check = chk

# ---------------- 3. availability and decisions ----------------
if "check" in st.session_state:
    chk = st.session_state.check
    n_ok = (chk.status == "Available").sum()
    n_sub = chk.substitute_id.notna().sum()
    n_bad = len(chk) - n_ok
    c = st.columns(3)
    ui.kpi(c[0], "Ready to dispense", f"{n_ok} of {len(chk)}", "lines fully in stock", "good")
    ui.kpi(c[1], "Short lines", str(n_bad), "out of stock, partial or not stocked", "bad" if n_bad else "")
    ui.kpi(c[2], "Substitutes found", str(n_sub), "in-stock alternatives", "good" if n_sub else "")
    st.write("")
    decided = st.data_editor(
        chk[["drug_name", "qty", "on_hand", "status", "substitute_name", "match_type", "use_substitute"]],
        hide_index=True, width="stretch", key="decisions",
        disabled=["drug_name", "qty", "on_hand", "status", "substitute_name", "match_type"],
        column_config={"drug_name": "Prescribed drug", "qty": "Qty", "on_hand": "On hand", "status": "Status",
                       "substitute_name": "Suggested substitute", "match_type": "Match",
                       "use_substitute": st.column_config.CheckboxColumn("Give substitute")})
    if (chk.match_type == "Therapeutic alternative").any():
        st.caption("Therapeutic alternatives need the prescribing doctor's approval before dispensing.")

    if st.button("Dispense and save", type="primary"):
        dec = chk.copy()
        dec["use_substitute"] = decided.use_substitute.values & dec.substitute_id.notna()
        summary = services.dispense(int(patient_id), doctor.doctor_id, doctor.spec_id, doctor.dept_id, dec)
        ui.refresh()
        for k in ("check", "rx_lines", "rx_editor", "decisions"):
            st.session_state.pop(k, None)
        st.session_state.last_rx = summary
        st.rerun()

if "last_rx" in st.session_state:
    s = st.session_state.last_rx
    st.success(f"Saved prescription {s['rx_id']}: dispensed {ui.inr(s['dispensed_value'])}, "
               f"{s['substituted_lines']} line(s) filled with a substitute, {s['bounced_lines']} line(s) recorded as bounce.")

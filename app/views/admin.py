import subprocess
import sys

import streamlit as st

import config
import ui
from src import services

ui.page_header("Admin", "Users, database health and model retraining")

tab1, tab2, tab3 = st.tabs(["Users", "Database", "Retrain"])

with tab1:
    st.dataframe(services.list_users(), hide_index=True, width="stretch")
    with st.form("new_user", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        u = c1.text_input("Username")
        n = c2.text_input("Full name")
        r = c3.selectbox("Role", ["pharmacist", "manager"])
        p = c4.text_input("Password", type="password")
        if st.form_submit_button("Add user", type="primary"):
            if not (u and p):
                st.error("Username and password are required.")
            else:
                try:
                    services.add_user(u.strip(), n.strip(), r, p)
                    st.success(f"Added {u}.")
                except Exception as e:
                    st.error(f"Could not add user: {e}")

with tab2:
    st.dataframe(services.table_counts(), hide_index=True, width="stretch")

with tab3:
    st.caption("Rebuilds every table from the raw file, retrains both models, reruns the impact study and "
               "reloads MySQL. Takes about 5 minutes. Entries made in the app will be replaced.")
    if st.button("Run full pipeline", type="primary"):
        with st.status("Running pipeline...", expanded=True) as status:
            proc = subprocess.Popen([sys.executable, "run_pipeline.py"], cwd=config.ROOT,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            box = st.empty()
            log = []
            for line in proc.stdout:
                log.append(line.rstrip())
                box.code("\n".join(log[-25:]))
            proc.wait()
            if proc.returncode == 0:
                status.update(label="Pipeline finished", state="complete")
                ui.refresh()
            else:
                status.update(label="Pipeline failed, see log", state="error")

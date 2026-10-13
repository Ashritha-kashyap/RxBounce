"""RxBounce - Streamlit entry point.   Run:  streamlit run app/app.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = Path(__file__).resolve().parent
for p in (str(ROOT), str(APP)):
    if p not in sys.path:
        sys.path.insert(0, p)

import streamlit as st  # noqa: E402

st.set_page_config(page_title="RxBounce", page_icon=":material/local_pharmacy:", layout="wide",
                   initial_sidebar_state="expanded")

import ui  # noqa: E402
from src import services  # noqa: E402

ui.inject_css()


def login_screen():
    _, mid, _ = st.columns([1.3, 1, 1.3])
    with mid:
        st.markdown("<div style='height:8vh'></div>", unsafe_allow_html=True)
        ui.brand()
        st.markdown('<div class="tagline" style="margin-bottom:1rem">Fewer patients turned away at the pharmacy counter</div>',
                    unsafe_allow_html=True)
        with st.form("login", border=True):
            user = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in", type="primary", width="stretch")
        if ok:
            try:
                u = services.authenticate(user.strip(), pw)
            except Exception as e:  # database not reachable
                st.error(f"Could not reach the database. Check DATABASE_URL in .env and that MySQL is running.\n\n{e}")
                return
            if u:
                st.session_state.user = u
                st.rerun()
            else:
                st.error("Username or password is incorrect.")


if "user" not in st.session_state:
    login_screen()
    st.stop()

user = st.session_state.user
role = user["role"]

P = lambda path, title, icon, **kw: st.Page(str(APP / "views" / path), title=title, icon=icon, **kw)
home = P("overview.py", "Home", ":material/home:", default=True)
forecast = P("forecast.py", "Demand forecast", ":material/query_stats:")
risk = P("stock_risk.py", "Stockout risk & reorder", ":material/inventory_2:")
counter = P("counter.py", "Pharmacy counter", ":material/medication:")
expiry = P("expiry.py", "Expiry monitor", ":material/event_busy:")
impact = P("impact.py", "Impact study", ":material/trending_down:")
admin = P("admin.py", "Admin", ":material/settings:")

# Two roles: the pharmacist serves patients, the manager also plans stock and runs the system.
# "Prevent bounces" follows the three solution steps: forecast, reorder, substitute at the counter.
if role == "pharmacist":
    pages = {"": [home], "Prevent bounces": [counter, expiry]}
else:
    pages = {"": [home], "Prevent bounces": [forecast, risk, counter, expiry], "Results": [impact], "System": [admin]}

st.logo(str(APP / "assets" / "logo.svg"), size="large")
with st.sidebar:
    st.caption(f"{user['full_name']}, {'pharmacist' if role == 'pharmacist' else 'manager'}  \nData as of {services.AS_OF:%d %b %Y}")
    if st.button("Sign out", width="stretch"):
        del st.session_state["user"]
        st.rerun()

st.navigation(pages).run()

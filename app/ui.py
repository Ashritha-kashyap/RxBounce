"""Shared look-and-feel, formatting helpers and cached data loaders."""
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from src import services

# ---------------- palette ----------------
NAVY = "#15324D"      # brand, hero band
INK = "#1E2A36"       # body text
GREY = "#6B7785"      # secondary text
LINE = "#E3E8EE"      # borders and gridlines
BLUE = "#2F6690"      # primary data colour
SKY = "#9CC3DE"       # light companion
CORAL = "#E4572E"     # bounce / loss
GREEN = "#2A9D74"     # recovered / gain
AMBER = "#F2A541"     # warning
LIVE_BG = "#E9F5F0"   # "RxBounce live" shading

ORANGE, TEAL, LEAF, MUTED = CORAL, BLUE, GREEN, GREY     # older names
SCENARIO = {"Current policy": "Old policy", "ML reorder policy": "ML reorder",
            "ML reorder + substitutes": "ML reorder + substitutes"}
SCENARIO_COLORS = {"Old policy": CORAL, "ML reorder": BLUE, "ML reorder + substitutes": GREEN}
FONT = "Source Sans 3, Segoe UI, Arial, sans-serif"

pio.templates["rx"] = go.layout.Template(layout=dict(
    font=dict(family=FONT, color=INK, size=12),
    colorway=[BLUE, AMBER, CORAL, SKY, GREEN, NAVY],
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=4, r=4, t=8, b=4),
    xaxis=dict(gridcolor=LINE, linecolor=LINE, zeroline=False, tickfont=dict(color=GREY), showgrid=False),
    yaxis=dict(gridcolor=LINE, linecolor=LINE, zeroline=False, tickfont=dict(color=GREY)),
    legend=dict(orientation="h", y=-0.18, x=0, font=dict(size=11)),
    hoverlabel=dict(font_family=FONT, bgcolor="white", bordercolor=LINE)))
pio.templates.default = "rx"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, button, input, textarea, select {{
    font-family: 'Source Sans 3', 'Segoe UI', Arial, sans-serif; }}
.block-container {{ padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1180px; }}
h1 {{ font-size: 1.45rem !important; font-weight: 600 !important; color: {INK}; padding-bottom: 0 !important; }}
h3 {{ font-size: 1rem !important; font-weight: 600 !important; color: {INK}; }}
.page-sub {{ color: {GREY}; font-size: 0.9rem; margin: -0.3rem 0 1rem 0; }}

.hero {{ background: {NAVY}; border-radius: 10px; padding: 1.3rem 1.6rem 1.2rem; color: #fff;
         display: flex; flex-wrap: wrap; gap: 0.6rem 3rem; margin-bottom: 1rem; }}
.hero-head {{ flex-basis: 100%; font-size: 1rem; font-weight: 600; color: #fff; }}
.hero-head span {{ font-weight: 400; color: #A9BED3; }}
.hero-item .v {{ font-size: 1.9rem; font-weight: 700; line-height: 1.15; font-variant-numeric: tabular-nums; }}
.hero-item .v .was {{ color: #F29E86; font-weight: 600; }}
.hero-item .v .arrow {{ color: #7F98B2; font-weight: 400; margin: 0 0.35rem; }}
.hero-item .v .now {{ color: #7FD8B5; }}
.hero-item .l {{ font-size: 0.82rem; color: #A9BED3; margin-top: 0.15rem; }}

.card-title {{ font-size: 0.98rem; font-weight: 600; color: {INK}; margin: 0.1rem 0 0.15rem 0; }}
.card-sub {{ font-size: 0.82rem; color: {GREY}; margin-bottom: 0.4rem; }}
.badge {{ display: inline-block; background: #FDECE7; color: {CORAL}; border-radius: 999px; padding: 0 0.55rem;
          font-size: 0.8rem; font-weight: 600; margin-left: 0.4rem; vertical-align: 1px; }}

.kpi {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 8px; padding: 0.7rem 0.9rem; }}
.kpi-label {{ font-size: 0.8rem; color: {GREY}; }}
.kpi-value {{ font-size: 1.35rem; font-weight: 600; color: {INK}; margin-top: 0.1rem; font-variant-numeric: tabular-nums; }}
.kpi-note {{ font-size: 0.78rem; color: {GREY}; margin-top: 0.1rem; }}
.kpi-note.bad {{ color: {CORAL}; }}
.kpi-note.good {{ color: {GREEN}; }}
.kpi-note.warn {{ color: #B7791F; }}

.strip {{ display: flex; flex-wrap: wrap; gap: 0.5rem 2.2rem; padding: 0.5rem 0 0.1rem; border-top: 1px solid {LINE}; }}
.strip div {{ font-size: 0.85rem; color: {GREY}; }}
.strip b {{ color: {INK}; font-weight: 600; font-size: 1rem; margin-right: 0.25rem; }}

.brand {{ display: flex; align-items: center; gap: 0.55rem; margin-bottom: 0.2rem; }}
.brand .mark {{ background: {NAVY}; color: #fff; font-weight: 700; font-size: 0.85rem; border-radius: 6px;
                width: 1.9rem; height: 1.9rem; display: flex; align-items: center; justify-content: center; }}
.brand .name {{ font-weight: 700; font-size: 1.05rem; color: {NAVY}; }}
.tagline {{ font-size: 0.82rem; color: {GREY}; }}
section[data-testid="stSidebar"] {{ border-right: 1px solid {LINE}; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ background: #FFFFFF; }}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def brand():
    st.markdown('<div class="brand"><div class="mark">Rx</div><div class="name">RxBounce</div></div>',
                unsafe_allow_html=True)


def page_header(title, subtitle=None):
    st.title(title)
    if subtitle:
        st.markdown(f'<p class="page-sub">{subtitle}</p>', unsafe_allow_html=True)


def hero(head, items, note=None):
    """items: list of (label, value) where value is a string or a (was, now) tuple."""
    cells = []
    for label, value in items:
        if isinstance(value, tuple):
            value = f'<span class="was">{value[0]}</span><span class="arrow">→</span><span class="now">{value[1]}</span>'
        cells.append(f'<div class="hero-item"><div class="v">{value}</div><div class="l">{label}</div></div>')
    sub = f" <span>{note}</span>" if note else ""
    st.markdown(f'<div class="hero"><div class="hero-head">{head}{sub}</div>{"".join(cells)}</div>',
                unsafe_allow_html=True)


def card_title(title, sub=None, badge=None):
    b = f'<span class="badge">{badge}</span>' if badge is not None else ""
    st.markdown(f'<div class="card-title">{title}{b}</div>' + (f'<div class="card-sub">{sub}</div>' if sub else ""),
                unsafe_allow_html=True)


def strip(items):
    """A slim row of (value, label) facts under a chart."""
    st.markdown('<div class="strip">' + "".join(f"<div><b>{v}</b>{l}</div>" for v, l in items) + "</div>",
                unsafe_allow_html=True)


def kpi(col, label, value, note="", tone=""):
    col.markdown(f'<div class="kpi"><div class="kpi-label">{label}</div>'
                 f'<div class="kpi-value">{value}</div><div class="kpi-note {tone}">{note}&nbsp;</div></div>',
                 unsafe_allow_html=True)


def chart(fig, height=300, container=st):
    fig.update_layout(height=height)
    container.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def inr(v):
    """Indian-style currency: 1,23,456 -> 1.23 L, 1,23,45,678 -> 1.23 Cr."""
    if v is None:
        return "-"
    sign = "-" if v < 0 else ""
    v = abs(float(v))
    if v >= 1e7:
        return f"{sign}₹{v / 1e7:.2f} Cr"
    if v >= 1e5:
        return f"{sign}₹{v / 1e5:.2f} L"
    return f"{sign}₹{v:,.0f}"


def pct(v, digits=1):
    return f"{v * 100:.{digits}f}%"


# ---------------- cached loaders ----------------
@st.cache_data(ttl=300, show_spinner=False)
def lines():
    return services.prescription_lines()


@st.cache_data(ttl=300, show_spinner=False)
def drugs():
    return services.drugs()


@st.cache_data(ttl=300, show_spinner=False)
def doctors():
    return services.doctors()


@st.cache_data(ttl=300, show_spinner=False)
def patient_ids():
    return services.patient_ids()


@st.cache_data(ttl=120, show_spinner=False)
def stock():
    return services.stock_view()


@st.cache_data(ttl=120, show_spinner=False)
def batches():
    return services.batches()


@st.cache_data(ttl=600, show_spinner=False)
def simulation():
    wide, brk = services.simulation()
    wide = wide.rename(index=SCENARIO)
    brk = brk.assign(scenario=brk.scenario.map(SCENARIO))
    return wide, brk


@st.cache_data(ttl=600, show_spinner=False)
def model_metrics():
    return services.model_metrics()


def refresh():
    st.cache_data.clear()

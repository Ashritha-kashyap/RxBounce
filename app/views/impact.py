import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ui
from src import services

wide, brk = ui.simulation()
old, ml, full = wide.loc["Old policy"], wide.loc["ML reorder"], wide.loc["ML reorder + substitutes"]
days = int(full.window_days)
yearly = 365 / days

ui.page_header("Impact study", f"{services.GO_LIVE:%b %Y} to {services.AS_OF:%b %Y}: the same prescriptions, "
               "run with the old ordering and with RxBounce")

ui.hero("Result", [
    ("Bounce rate", (ui.pct(old.bounce_rate), ui.pct(full.bounce_rate))),
    ("Lower bounce rate (target 30%)", ui.pct(full.bounce_reduction_pct, 0)),
    ("Revenue recovered per year", ui.inr(full.revenue_recovered_annual_inr)),
    ("Net gain per year, after stock costs", ui.inr(full.net_benefit_annual_inr)),
])

left, right = st.columns(2, gap="medium")
with left.container(border=True):
    ui.card_title("How the bounce rate came down", "Each step of the solution added on top of the last")
    fig = go.Figure(go.Bar(x=wide.index, y=wide.bounce_rate, text=[ui.pct(v) for v in wide.bounce_rate],
                           textposition="outside", width=0.5,
                           marker_color=[ui.SCENARIO_COLORS[s] for s in wide.index],
                           hovertemplate="%{x}: %{y:.1%}<extra></extra>"))
    fig.add_hline(y=old.bounce_rate * 0.7, line_dash="dot", line_color=ui.GREY, line_width=1,
                  annotation_text="Target", annotation_position="top right", annotation_font=dict(size=11, color=ui.GREY))
    fig.update_layout(yaxis=dict(tickformat=".0%", range=[0, old.bounce_rate * 1.25]),
                      xaxis=dict(tickfont=dict(color=ui.INK)))
    ui.chart(fig, 300)

with right.container(border=True):
    ui.card_title("Revenue lost to bounces each month", "Old ordering vs RxBounce")
    m = brk[brk.scenario.isin(["Old policy", "ML reorder + substitutes"])].copy()
    m["label"] = pd.to_datetime(m.month).dt.strftime("%b %y")
    fig = go.Figure()
    for sc, name in [("Old policy", "Old policy"), ("ML reorder + substitutes", "RxBounce")]:
        g = m[m.scenario == sc]
        fig.add_bar(x=g.label, y=g.lost_revenue, name=name, marker_color=ui.SCENARIO_COLORS[sc],
                    hovertemplate=f"{name}, %{{x}}: ₹%{{y:,.0f}}<extra></extra>")
    fig.update_layout(barmode="group", bargap=0.3, yaxis=dict(tickprefix="₹", tickformat="~s"),
                      legend=dict(y=1.12, x=1, xanchor="right"))
    ui.chart(fig, 300)

with st.container(border=True):
    ui.card_title("Where the revenue comes from, and what it costs", f"Per year, scaled from {days} days")
    c = st.columns(4)
    ui.kpi(c[0], "From ML reorder", ui.inr(ml.revenue_recovered_annual_inr), "drugs back in stock on time", "good")
    ui.kpi(c[1], "From substitutes", ui.inr((full.revenue_recovered_inr - ml.revenue_recovered_inr) * yearly),
           "short lines filled with an equivalent", "good")
    ui.kpi(c[2], "Extra stock cost", ui.inr(full.inventory_cost_change_inr * yearly),
           f"stock value {ui.inr(old.avg_inventory_value_inr)} to {ui.inr(full.avg_inventory_value_inr)}", "warn")
    ui.kpi(c[3], "Emergency purchases", f"{int(old.emergency_purchases):,} to {int(full.emergency_purchases):,}",
           "same-day local buys at a premium", "good")

with st.container(border=True):
    per_store = full.revenue_recovered_annual_inr
    needed = int(-(-20e5 // per_store)) if per_store > 0 else 0
    ui.card_title("₹20 lakh target across the hospital chain",
                  f"One pharmacy recovers {ui.inr(per_store)} a year. {needed} pharmacies of similar size reach the target.")
    stores = st.slider("Pharmacies using RxBounce", 1, 10, needed or 1)
    st.progress(min(per_store * stores / 20e5, 1.0), text=f"{ui.inr(per_store * stores)} of ₹20 L per year")

abl, sens = services.robustness()
with st.container(border=True):
    ui.card_title("What each part of the solution contributes",
                  "Most of the drop comes from the forecast-driven reorder rules. A moving-average forecast gives a "
                  "similar bounce rate, LightGBM holds slightly less stock, and substitutes add the rest.")
    t = pd.DataFrame({"Setup": abl.step, "Bounce rate": abl.bounce_rate.map(ui.pct),
                      "Lower than old policy": abl.bounce_reduction_pct.map(lambda v: ui.pct(v, 0) if v > 0 else "-"),
                      "Average stock value": abl.avg_inventory_value_inr.map(ui.inr)})
    st.dataframe(t, hide_index=True, width="stretch")

with st.container(border=True):
    ui.card_title("Does it hold under harder conditions?",
                  "Each condition reruns both the old policy and RxBounce on the same prescriptions")
    t = pd.DataFrame({"Condition": sens.case_name, "Old policy": sens.old_bounce_rate.map(ui.pct),
                      "RxBounce": sens.rxbounce_bounce_rate.map(ui.pct),
                      "Lower by": sens.bounce_reduction_pct.map(lambda v: ui.pct(v, 0)),
                      "30% target": sens.meets_target.map({1: "Met", 0: "Missed"})})
    st.dataframe(t, hide_index=True, width="stretch")

with st.expander("How this was measured"):
    st.markdown("""
- **Old policy:** stock topped up once a month to last month's sales. Demand that bounced was never seen.
- **ML reorder:** the demand forecast sets a reorder level for every drug. Stock is checked weekly
  (twice a week for A items) and topped up when it falls below that level.
- **Substitutes:** when a drug is still short, the counter offers an equivalent that is in stock.
- Every scenario starts from the same shelf and faces exactly the same prescriptions.
""")

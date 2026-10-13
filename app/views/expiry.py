import plotly.graph_objects as go
import streamlit as st

import config
import ui

ui.page_header("Expiry monitor", "Expired stock on the shelf is a bounce waiting to happen")

b = ui.batches()
BUCKETS = [("Expired", -10**6, 0, ui.CORAL), ("Within 30 days", 1, 30, ui.AMBER),
           ("31 to 90 days", 31, config.NEAR_EXPIRY_DAYS, "#F7CB82"), ("91 to 180 days", 91, 180, ui.SKY)]
b["window"] = None
for name, lo, hi, _ in BUCKETS:
    b.loc[b.days_to_expiry.between(lo, hi), "window"] = name

with st.container(border=True):
    ui.card_title("Stock value by time left to expiry")
    g = b.dropna(subset=["window"]).groupby("window").agg(value=("value", "sum"), lots=("batch_id", "count"))
    g = g.reindex([x[0] for x in BUCKETS]).fillna(0)
    fig = go.Figure(go.Bar(
        x=g.value, y=g.index, orientation="h", marker_color=[x[3] for x in BUCKETS],
        text=[f"{ui.inr(v)}  ·  {int(n)} lots" for v, n in zip(g.value, g.lots)], textposition="outside",
        hovertemplate="%{y}: ₹%{x:,.0f}<extra></extra>"))
    fig.update_layout(xaxis=dict(visible=False, range=[0, g.value.max() * 1.35]),
                      yaxis=dict(autorange="reversed", tickfont=dict(color=ui.INK, size=12)), bargap=0.4)
    ui.chart(fig, 220)

with st.container(border=True):
    show = st.segmented_control("Show", ["Expired", "Next 30 days", "Next 90 days"], default="Next 90 days",
                                label_visibility="collapsed")
    limit = {"Expired": 0, "Next 30 days": 30, "Next 90 days": config.NEAR_EXPIRY_DAYS}.get(show, 90)
    t = b[b.days_to_expiry <= limit].sort_values("expiry_date")
    ui.card_title("Lots to act on", "Expired lots: remove from the shelf. Others: dispense first or return to supplier.",
                  badge=len(t))
    st.dataframe(t[["drug_name", "lot_no", "qty_remaining", "expiry_date", "days_to_expiry", "value"]],
                 hide_index=True, width="stretch", height=min(420, 38 + 35 * max(len(t), 1)),
                 column_config={
                     "drug_name": "Drug", "lot_no": "Lot", "qty_remaining": "Units",
                     "expiry_date": st.column_config.DateColumn("Expires", format="DD MMM YYYY"),
                     "days_to_expiry": "Days left",
                     "value": st.column_config.NumberColumn("Value (₹)", format="%.0f")})

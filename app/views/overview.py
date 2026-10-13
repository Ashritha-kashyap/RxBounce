import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import ui
from src import services

GO = services.GO_LIVE
df = ui.lines()
wide, _ = ui.simulation()
old, new = wide.loc["Old policy"], wide.loc["ML reorder + substitutes"]
before, after = df[df.rx_date < GO], df[df.rx_date >= GO]

ui.page_header("Bounce overview", f"RxBounce has been running at the pharmacy counter since {GO:%d %B %Y}")

ui.hero("Since RxBounce went live", [
    ("Bounce rate, before vs after", (ui.pct(before.is_bounce.mean()), ui.pct(after.is_bounce.mean()))),
    ("Bounces prevented", f"{int(new.bounces_prevented):,}"),
    ("Revenue recovered per year", ui.inr(new.revenue_recovered_annual_inr)),
])

# ---------------- the one chart that tells the story ----------------
with st.container(border=True):
    ui.card_title("Monthly bounce rate", "Share of prescription lines not fully dispensed")
    m = df.groupby("month").is_bounce.mean()
    pre, post = m[m.index < GO], m[m.index >= GO]
    target = before.is_bounce.mean() * 0.7
    fig = go.Figure()
    fig.add_vrect(x0=GO - pd.Timedelta(days=15), x1=m.index.max() + pd.Timedelta(days=15),
                  fillcolor=ui.LIVE_BG, line_width=0, layer="below")
    fig.add_annotation(x=GO - pd.Timedelta(days=10), y=1, yref="paper", text="RxBounce live", showarrow=False,
                       xanchor="left", yanchor="top", font=dict(size=11, color=ui.GREEN))
    fig.add_scatter(x=pre.index, y=pre.values, mode="lines+markers", name="Old ordering",
                    line=dict(color=ui.CORAL, width=2.5), marker=dict(size=5),
                    hovertemplate="%{x|%b %Y}: %{y:.1%}<extra></extra>")
    fig.add_scatter(x=[pre.index[-1], *post.index], y=[pre.values[-1], *post.values], mode="lines+markers",
                    name="With RxBounce", line=dict(color=ui.GREEN, width=2.5), marker=dict(size=5),
                    hovertemplate="%{x|%b %Y}: %{y:.1%}<extra></extra>")
    fig.add_hline(y=target, line_dash="dot", line_color=ui.GREY, line_width=1,
                  annotation_text=f"Target {ui.pct(target)}", annotation_position="bottom left",
                  annotation_font=dict(size=11, color=ui.GREY))
    fig.update_layout(yaxis=dict(tickformat=".0%", rangemode="tozero"), xaxis=dict(tickformat="%b %y", dtick="M3"),
                      legend=dict(y=1.08, x=1, xanchor="right", orientation="h"))
    ui.chart(fig, 320)

# ---------------- what is still bouncing ----------------
left, right = st.columns([1, 1.4], gap="medium")
still = after[after.is_bounce == 1]
with left.container(border=True):
    ui.card_title("Why lines still bounce", "Since go-live")
    r = still.bounce_reason.value_counts().reset_index()
    r.columns = ["reason", "lines"]
    fig = px.pie(r, names="reason", values="lines", hole=0.6,
                 color="reason", color_discrete_map={"Out of stock": ui.CORAL, "Not stocked": ui.AMBER,
                                                     "Insufficient quantity": ui.SKY})
    fig.update_traces(texttemplate="%{percent:.0%}", textfont_size=11, sort=False,
                      hovertemplate="%{label}: %{value:,} lines<extra></extra>")
    fig.update_layout(legend=dict(orientation="v", y=0.5, x=1.0, yanchor="middle"))
    ui.chart(fig, 230)
with right.container(border=True):
    ui.card_title("Drugs to watch", "Most bounced since go-live")
    top = still.groupby("drug_name").size().sort_values().tail(5)
    fig = go.Figure(go.Bar(x=top.values, y=[n if len(n) < 34 else n[:32] + "…" for n in top.index],
                           orientation="h", marker_color=ui.BLUE, text=top.values, textposition="outside",
                           hovertemplate="%{y}: %{x} bounced lines<extra></extra>"))
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(tickfont=dict(color=ui.INK)), bargap=0.45)
    ui.chart(fig, 230)

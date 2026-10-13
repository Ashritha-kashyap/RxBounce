import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ui
from src import services

ui.page_header("Demand forecast", "Weekly demand predicted for each drug. It sets how much stock RxBounce keeps.")

stock = ui.stock()
c1, c2 = st.columns([1, 4])
abc = c1.selectbox("ABC class", ["A", "B", "C", "All"])
pool = stock if abc == "All" else stock[stock.abc_class == abc]
name = c2.selectbox("Drug", pool.sort_values("avg_daily_forecast", ascending=False).drug_name)
row = pool[pool.drug_name == name].iloc[0]

fc = services.forecasts(row.drug_id)
hist, fut = fc[fc.is_future == 0], fc[fc.is_future == 1]
go_live = services.GO_LIVE

with st.container(border=True):
    ui.card_title(name, "Units per week: what patients asked for, and what the model predicted")
    fig = go.Figure()
    fig.add_vrect(x0=go_live, x1=hist.week_start.max() + pd.Timedelta(days=6), fillcolor=ui.LIVE_BG,
                  line_width=0, layer="below")
    fig.add_annotation(x=go_live, y=1, yref="paper", text="RxBounce live", showarrow=False, xanchor="left",
                       yanchor="top", font=dict(size=11, color=ui.GREEN), xshift=4)
    fig.add_scatter(x=hist.week_start, y=hist.actual_qty, name="Actual demand", mode="lines",
                    line=dict(color="#B8C2CC", width=1.5))
    fig.add_scatter(x=hist.week_start, y=hist.predicted_qty, name="Forecast", mode="lines",
                    line=dict(color=ui.BLUE, width=2.5))
    fig.add_scatter(x=fut.week_start, y=fut.predicted_qty, name="Next week", mode="markers",
                    marker=dict(color=ui.CORAL, size=10))
    fig.update_layout(yaxis=dict(rangemode="tozero"), xaxis=dict(tickformat="%b %y"),
                      legend=dict(y=1.1, x=1, xanchor="right"), hovermode="x unified")
    ui.chart(fig, 340)
    nxt = float(fut.predicted_qty.iat[0]) if len(fut) else 0
    ui.strip([(f"{nxt:.0f}", "units expected next week"), (f"{int(row.qty_on_hand):,}", "on hand"),
              (f"{int(row.reorder_point)}", "reorder level"),
              (f"{int(row.suggested_order_qty)}" if row.suggested_order_qty else "None", "to order now")])

with st.expander("Model accuracy"):
    mm = ui.model_metrics()
    fm = mm[mm.task == "Demand forecasting"].pivot_table(index=["model", "is_selected"], columns="metric",
                                                         values="value").reset_index().sort_values("WAPE")
    fm["model"] = fm.model + fm.is_selected.map({1: " (used)", 0: ""})
    st.dataframe(fm[["model", "MAE", "RMSE", "WAPE"]].round(3), hide_index=True, width="stretch",
                 column_config={"model": "Model"})
    st.caption("Measured on weeks after go-live, which the models never saw. Lower is better.")

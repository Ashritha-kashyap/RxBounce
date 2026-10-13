import streamlit as st

import ui
from src import services

ui.page_header("Stockout risk & reorder", "Order these today so they are on the shelf before patients ask for them")

s = ui.stock()
high = s[s.risk_band == "High"]
reorder = s[s.suggested_order_qty > 0]
k = st.columns(4)
ui.kpi(k[0], "High-risk drugs", f"{len(high)}", "likely to run short in 7 days", "bad")
ui.kpi(k[1], "Orders suggested", f"{len(reorder)}", "at or below reorder level", "warn")
ui.kpi(k[2], "Order value", ui.inr((reorder.suggested_order_qty * reorder.unit_cost).sum()), "at cost price")
ui.kpi(k[3], "Out of stock now", f"{(s.qty_on_hand <= 0).sum()}", "drugs with zero on hand", "bad")
st.write("")

todo = s[(s.suggested_order_qty > 0) | (s.risk_band == "High")].copy()
todo["order_qty"] = todo.suggested_order_qty
todo["risk_pct"] = (todo.stockout_risk * 100).round(0)
todo = todo.sort_values(["stockout_risk", "suggested_order_qty"], ascending=False).reset_index(drop=True)

with st.container(border=True):
    ui.card_title("Orders to place today", "Ranked by risk. Tick the lines to order and adjust quantities if needed.",
                  badge=len(todo))
    todo.insert(0, "order", todo.order_qty > 0)
    view = st.data_editor(
        todo[["order", "drug_name", "qty_on_hand", "risk_pct", "order_qty", "supplier_name"]],
        hide_index=True, width="stretch", key="reorder_editor", height=min(460, 38 + 35 * max(len(todo), 1)),
        disabled=["drug_name", "qty_on_hand", "risk_pct", "supplier_name"],
        column_config={"order": st.column_config.CheckboxColumn("Order", width="small"),
                       "drug_name": st.column_config.TextColumn("Drug", width="large"),
                       "qty_on_hand": st.column_config.NumberColumn("On hand", width="small"),
                       "risk_pct": st.column_config.ProgressColumn("Chance of running short", min_value=0,
                                                                   max_value=100, format="%d%%"),
                       "order_qty": st.column_config.NumberColumn("Order qty", min_value=0, step=1, width="small"),
                       "supplier_name": "Supplier"})
    pick = view.order.values & (view.order_qty.values > 0)
    chosen = todo[pick].copy()
    chosen["order_qty"] = view.order_qty.values[pick]
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    c1.markdown(f"**{len(chosen)}** lines, **{ui.inr((chosen.order_qty * chosen.unit_cost).sum())}**, "
                f"**{chosen.supplier_id.nunique()}** suppliers")
    if c2.button("Raise purchase orders", type="primary", disabled=chosen.empty, width="stretch"):
        ids = services.create_purchase_orders(chosen[["drug_id", "supplier_id", "order_qty", "unit_cost",
                                                      "lead_time_mean"]])
        ui.refresh()
        st.toast(f"Raised {len(ids)} purchase orders")
        st.rerun()

placed = services.manual_orders()
if len(placed):
    with st.expander(f"Orders raised from this screen ({len(placed)})"):
        st.dataframe(placed, hide_index=True, width="stretch", column_config={
            "po_id": "PO", "supplier_name": "Supplier", "line_count": "Lines",
            "order_date": st.column_config.DateColumn("Ordered", format="DD MMM YYYY"),
            "expected_date": st.column_config.DateColumn("Expected", format="DD MMM YYYY"),
            "po_value": st.column_config.NumberColumn("Value (₹)", format="%.0f")})

with st.expander("Model accuracy"):
    mm = ui.model_metrics()
    rm = mm[mm.task.str.startswith("Stockout")].pivot_table(index=["model", "is_selected"], columns="metric",
                                                            values="value").reset_index()
    rm["model"] = rm.model + rm.is_selected.map({1: " (used)", 0: ""})
    st.dataframe(rm[["model", "ROC_AUC", "Recall", "Precision"]].round(3), hide_index=True, width="stretch",
                 column_config={"model": "Model", "ROC_AUC": "ROC-AUC"})
    st.caption("Recall is the share of real shortages the model flagged in advance, measured after go-live.")

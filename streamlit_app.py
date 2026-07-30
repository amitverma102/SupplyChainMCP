from __future__ import annotations
import datetime
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard_components import (
    download_dataframe,
    load_app_style,
    plot_bar_chart,
    plot_gauge,
    plot_line_chart,
    render_aggrid_table,
    render_kpi_cards,
    render_sidebar_menu,
)
from mcp_client import SupplyChainMCPClient


APP_TITLE = "SupplyChain Control Tower"
MENU_ITEMS = [
    "Dashboard",
    "Forecast Analysis",
    "PO Acknowledgements",
    "CUT Analysis",
    "Root Cause Analysis",
    "Vendor Performance",
    "Product Analytics",
    "Demand Analysis",
    "Forecast Accuracy",
    "Inventory Risk",
    "Supply Risk",
    "Exception Dashboard",
    "AI Supply Chain Copilot",
    "Settings",
]


@st.cache_resource
def get_client() -> SupplyChainMCPClient:
    return SupplyChainMCPClient()


@st.cache_data(show_spinner=False, ttl="5m")
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, list[str]], dict[str, tuple[date | None, date | None]]]:
    client = get_client()
    forecasts = client.forecast_df
    acks = client.ack_df
    filter_options = client.get_filter_options()
    date_ranges = client.get_date_ranges()
    return forecasts, acks, filter_options, date_ranges


DATE_FILTER_KEYS = {"forecast_month", "ack_date"}


def apply_filters(df: pd.DataFrame, filters: dict[str, list[str]]) -> pd.DataFrame:
    """Apply categorical sidebar filters after date ranges are handled."""
    if df.empty:
        return df
    for key, selected in filters.items():
        # Date ranges are applied separately by ``parse_date_filters``.  Their
        # (start, end) tuple must not be compared through ``isin``.
        if key in DATE_FILTER_KEYS or key not in df.columns:
            continue
        selected = [value for value in selected if value is not None and str(value).strip()]
        if not selected:
            continue
        df = df[df[key].astype(str).isin(selected)]
    return df


def filter_data(forecasts: pd.DataFrame, acks: pd.DataFrame, selections: dict[str, list[str]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    filtered_forecasts = apply_filters(forecasts, selections)
    filtered_acks = apply_filters(acks, selections)
    return filtered_forecasts, filtered_acks


def build_filter_controls(filter_options: dict[str, list[str]], date_ranges: dict[str, tuple[date | None, date | None]]) -> dict[str, list[str]]:
    st.sidebar.markdown("## Global Filters")
    filters: dict[str, list[str]] = {}
    for field, options in filter_options.items():
        selections = st.sidebar.multiselect(
            field.replace("_", " ").title(),
            options,
            default=[],
            key=f"filter_{field}",
        )
        filters[field] = selections

    st.sidebar.divider()
    st.sidebar.markdown("### Time Range")
    if date_ranges.get("forecast_month")[0] is not None:
        forecast_range = st.sidebar.date_input(
            "Forecast month range",
            value=(date_ranges["forecast_month"][0], date_ranges["forecast_month"][1]),
            key="forecast_month_range",
        )
        filters["forecast_month"] = [forecast_range]
    if date_ranges.get("ack_date")[0] is not None:
        ack_range = st.sidebar.date_input(
            "Acknowledgement date range",
            value=(date_ranges["ack_date"][0], date_ranges["ack_date"][1]),
            key="ack_date_range",
        )
        filters["ack_date"] = [ack_range]

    if st.sidebar.button("Reset filters"):
        for field in filter_options.keys():
            st.session_state[f"filter_{field}"] = []
        st.experimental_rerun()

    return filters


def parse_date_filters(filters: dict[str, list[str]], forecasts: pd.DataFrame, acks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "forecast_month" in filters and filters["forecast_month"]:
        dates = filters["forecast_month"][0]
        if isinstance(dates, (tuple, list)) and len(dates) == 2:
            start_date, end_date = dates
            if not pd.isna(start_date) and not pd.isna(end_date):
                forecasts = forecasts[
                    (forecasts["forecast_month"] >= pd.to_datetime(start_date))
                    & (forecasts["forecast_month"] <= pd.to_datetime(end_date))
                ]
    if "ack_date" in filters and filters["ack_date"]:
        dates = filters["ack_date"][0]
        if isinstance(dates, (tuple, list)) and len(dates) == 2:
            start_date, end_date = dates
            if not pd.isna(start_date) and not pd.isna(end_date):
                if "delivery_date" in acks.columns:
                    acks = acks[
                        (pd.to_datetime(acks["delivery_date"], errors="coerce") >= pd.to_datetime(start_date))
                        & (pd.to_datetime(acks["delivery_date"], errors="coerce") <= pd.to_datetime(end_date))
                    ]
                elif "ack_date" in acks.columns:
                    acks = acks[
                        (pd.to_datetime(acks["ack_date"], errors="coerce") >= pd.to_datetime(start_date))
                        & (pd.to_datetime(acks["ack_date"], errors="coerce") <= pd.to_datetime(end_date))
                    ]
                elif "po_date" in acks.columns:
                    acks = acks[
                        (pd.to_datetime(acks["po_date"], errors="coerce") >= pd.to_datetime(start_date))
                        & (pd.to_datetime(acks["po_date"], errors="coerce") <= pd.to_datetime(end_date))
                    ]
    return forecasts, acks


def _display_label(value: str) -> str:
    labels = {
        "po_shortfall_qty": "Purchase order quantity",
        "uncovered_shortfall_qty": "Uncovered purchase order quantity",
        "inventory_insufficient_for_po_shortfall": "Inventory insufficient for purchase order",
        "forecast_for_purchase_order_month": "Forecast for purchase order month",
        "no_forecast_issue": "No forecast issue",
        "under_forecasting": "Under forecasting",
        "forecast_below_purchase_order": "Forecast below purchase order",
        "supplier_delivery_delay": "Supplier delivery delay",
        "supplier_under_supply": "Supplier under supply",
        "damaged_supplier_shipment": "Damaged supplier shipment",
        "incorrect_supplier_shipment": "Incorrect supplier shipment",
        "buyer_supplier_order_issue": "Supplier PO timing or quantity issue",
    }
    if value in labels:
        return labels[value]
    return value.replace("_", " ").strip().title()


def _display_value(value: Any) -> str:
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return f"{value:,.0f}"
    if isinstance(value, (float, np.floating)):
        return f"{value:,.2f}"
    return str(value)


def render_root_cause_report(report: dict[str, Any], show_confidence: bool = True) -> None:
    """Render an analysis report as readable metrics, findings, and tables."""
    if show_confidence:
        st.metric("Analysis confidence", f"{report.get('confidence', 0.0) * 100:.0f}%")

    summary = report.get("summary", {})
    if summary:
        st.subheader("Summary")
        columns = st.columns(min(4, len(summary)))
        for index, (label, value) in enumerate(summary.items()):
            if label.endswith("fill_rate") and pd.notna(value):
                display_value = f"{float(value):.1%}"
            else:
                display_value = _display_value(value)
            columns[index % len(columns)].metric(_display_label(label), display_value)

    conclusions = report.get("conclusions", [])
    if conclusions:
        st.subheader("Findings (Analysis Window - 3 Months)")
        for conclusion in conclusions:
            cause = _display_label(conclusion.get("cause", "unknown"))
            confidence = conclusion.get("confidence", "unknown").title()
            st.markdown(f"**{cause}** — {confidence} confidence")
            evidence = conclusion.get("evidence")
            if isinstance(evidence, dict):
                details = "; ".join(
                    f"{_display_label(key)}: {_display_value(value)}"
                    for key, value in evidence.items()
                    if not isinstance(value, (dict, list))
                )
                if details:
                    st.caption(details)

    recommendations = report.get("recommendations", [])
    if recommendations:
        st.subheader("Recommended actions")
        for recommendation in recommendations:
            st.markdown(f"- {recommendation}")

    evidence_items = report.get("evidence", [])
    if evidence_items:
        st.subheader("Supporting evidence")
        for item in evidence_items:
            for label, values in item.items():
                st.markdown(f"**{_display_label(label)}**")
                if isinstance(values, list) and values:
                    render_aggrid_table(pd.DataFrame(values), height=250)
                elif isinstance(values, dict):
                    render_aggrid_table(pd.DataFrame([values]), height=150)
                elif values is not None:
                    st.write(_display_value(values))

    samples = report.get("supporting_ack_samples", [])
    if samples:
        st.subheader("Recent acknowledgement lines")
        render_aggrid_table(pd.DataFrame(samples), height=300)


def compute_kpis(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> dict[str, dict[str, Any]]:
    metrics = client.compute_dashboard_kpis(forecasts=forecasts, acknowledgements=acks)
    return {
        "Forecast Value": {"value": f"{metrics['forecast_value']:,.0f}", "delta": "", "detail": "Total forecast value"},
        "Ordered Quantity": {"value": f"{metrics['ordered_quantity']:,.0f}", "delta": "", "detail": "Total ordered units"},
        "Confirmed Quantity": {"value": f"{metrics['confirmed_quantity']:,.0f}", "delta": "", "detail": "Total confirmed units"},
        "Fill Rate": {"value": f"{metrics['fill_rate'] * 100:.2f}%", "delta": "", "detail": "Confirmed / ordered"},
        "Forecast Accuracy": {"value": f"{metrics.get('forecast_accuracy', 0.0) * 100:.1f}%", "delta": "", "detail": "MAPE"},
        "WMAPE": {"value": f"{metrics.get('wmape', 0.0) * 100:.1f}%", "delta": "", "detail": "Weighted MAPE"},
        "Products Short": {"value": f"{int(metrics['products_short']):,}", "delta": "", "detail": "Unique SKUs with short supply"},
        "High Risk Vendors": {"value": f"{int(metrics.get('high_risk_vendors', 0)):,}", "delta": "", "detail": "Low fill-rate vendors"},
    }


def page_dashboard(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# Executive Dashboard")
    st.markdown("Modern enterprise metrics for supply chain control and investigation.")

    metrics = compute_kpis(forecasts, acks, client)
    cards = []
    for label, payload in metrics.items():
        cards.append({"label": label, **payload})
    selected = render_kpi_cards(cards, columns=4)
    if selected:
        st.session_state.page = selected
        st.rerun()

    st.markdown("---")
    row1, row2 = st.columns([1.5, 1.5])
    with row1:
        st.subheader("Forecast vs Actual")
        df_fva = client.forecast_vs_actual()
        if not df_fva.empty:
            plot_line_chart(df_fva, x="month", y="forecast_qty", color=None, title="Forecasted Quantity")
            plot_line_chart(df_fva, x="month", y="actual_qty", color=None, title="Confirmed Quantity")
        else:
            st.info("Forecast vs actual data is not available.")
    with row2:
        st.subheader("Fill Rate Gauge")
        if metrics["Fill Rate"]["value"]:
            fill_rate = float(metrics["Fill Rate"]["value"].strip("%")) / 100
            plot_gauge(fill_rate, "Fill Rate", "Confirmed vs Ordered")
        else:
            st.info("Fill rate is unavailable.")

    st.markdown("---")
    st.subheader("Top Risk Products")
    risk_products = client.get_top_risk_products(10, acknowledgements=acks)
    if not risk_products.empty:
        selected_rows = render_aggrid_table(risk_products, return_selection=True)
        
        if selected_rows:
            selected_product = selected_rows[0]
            product_name = selected_product.get("Product Description", selected_product.get("vendor_sku", "Unknown Product"))
            sku = selected_product.get("vendor_sku")
            
            with st.expander(f"Product Issue Analysis: {product_name}", expanded=True):
                st.markdown("## Findings")
                st.markdown(f"**Item / Location review · Snapshot {pd.Timestamp.now().strftime('%Y-%m-%d')}**")
                
                cache_key = f"root_cause_report_v5_{sku}"
                if cache_key not in st.session_state:
                    with st.spinner("Analyzing root causes..."):
                        st.session_state[cache_key] = client.root_cause_analysis(product=sku, acknowledgements=acks)
                
                report = st.session_state[cache_key]
                conclusions = report.get("conclusions", [])
                
                missing_forecast = any(c.get("cause") == "missing_forecast_data" for c in conclusions)
                missing_supplier = any(c.get("cause") == "missing_supplier_data" for c in conclusions)
                missing_inventory = any(c.get("cause") == "missing_inventory_data" for c in conclusions)

                forecast_causes = [c for c in conclusions if c.get("cause") in ("under_forecasting", "forecast_below_purchase_order")]
                supplier_causes = [c for c in conclusions if any(term in str(c.get("cause")).lower() for term in ("supplier", "vendor", "buyer_supplier")) and not str(c.get("cause")).startswith("missing_")]
                inventory_causes = [c for c in conclusions if any(term in str(c.get("cause")).lower() for term in ("inventory", "supply_depleted")) and not str(c.get("cause")).startswith("missing_")]
                
                forecast_flag = bool(forecast_causes)
                supplier_flag = bool(supplier_causes)
                inventory_flag = bool(inventory_causes)

                col1, col2, col3 = st.columns(3)
                
                with col1:
                    if missing_forecast:
                        lbl = "⚪ Forecast vs PO - Missing"
                    else:
                        lbl = "🔴 Forecast vs PO - Flagged" if forecast_flag else "🟢 Forecast vs PO - On track"
                    if st.button(lbl, key="btn_forecast", use_container_width=True):
                        st.session_state["product_analysis_tab"] = "forecast"
                        st.session_state["product_analysis_sku"] = sku
                with col2:
                    if missing_supplier:
                        lbl = "⚪ Supplier Pipeline - Missing"
                    else:
                        lbl = "🔴 Supplier Pipeline - Flagged" if supplier_flag else "🟢 Supplier Pipeline - On track"
                    if st.button(lbl, key="btn_supplier", use_container_width=True):
                        st.session_state["product_analysis_tab"] = "supplier"
                        st.session_state["product_analysis_sku"] = sku
                with col3:
                    if missing_inventory:
                        lbl = "⚪ Inventory Coverage - Missing"
                    else:
                        lbl = "🔴 Inventory Coverage - Flagged" if inventory_flag else "🟢 Inventory Coverage - On track"
                    if st.button(lbl, key="btn_inventory", use_container_width=True):
                        st.session_state["product_analysis_tab"] = "inventory"
                        st.session_state["product_analysis_sku"] = sku

                st.caption("Click a light to see the analysis behind it.")

                if st.session_state.get("product_analysis_sku") == sku:
                    tab = st.session_state.get("product_analysis_tab")
                    po_months = []
                    for c in conclusions:
                        if "purchase_order_months" in c.get("evidence", {}):
                            po_months = c["evidence"]["purchase_order_months"]
                            break

                    def filter_last_3_po_months(df, date_col="month"):
                        if not po_months or df.empty:
                            return df.tail(3)
                        df["_temp_dt"] = pd.to_datetime(df[date_col])
                        max_po = pd.to_datetime(max(po_months))
                        min_po = pd.to_datetime(min(po_months)) - pd.DateOffset(months=2)
                        filtered = df[(df["_temp_dt"] >= min_po) & (df["_temp_dt"] <= max_po)].copy()
                        if filtered.empty:
                            return df.tail(3)
                        return filtered.drop(columns=["_temp_dt"])

                    if tab == "forecast":
                        def plot_forecast_chart():
                            monthly_sample = next((e["monthly_sample"] for e in report.get("evidence", []) if "monthly_sample" in e), [])
                            if monthly_sample:
                                df_monthly = pd.DataFrame(monthly_sample)
                                df_monthly = filter_last_3_po_months(df_monthly)
                                if not df_monthly.empty:
                                    df_monthly["month"] = pd.to_datetime(df_monthly["month"]).dt.strftime("%b %Y")
                                    df_monthly = df_monthly.rename(columns={"forecast_qty": "Forecast"})
                                    fig = px.bar(df_monthly, x="month", y=["Forecast", "Actual PO Quantity"], barmode="group",
                                                 title="Forecast vs Actual PO", labels={"value": "Quantity", "variable": "Metric"})
                                    st.plotly_chart(fig, use_container_width=True)

                        if missing_forecast:
                            st.info("No supporting data found.")
                        elif forecast_causes:
                            cause = forecast_causes[0]
                            st.error(f"Yes, likely due to {_display_label(cause.get('cause'))} ({cause.get('confidence')} confidence).")
                            evidence = cause.get("evidence", {})
                            st.write(f"**Last 3 Months Forecast:** {evidence.get('last_three_month_forecast', 0):.0f}")
                            st.write(f"**Actual PO Quantity:** {evidence.get('purchase_order_qty', 0):.0f}")
                            plot_forecast_chart()
                        else:
                            st.success("No incorrect forecast issues identified as the root cause.")
                            no_forecast = [c for c in conclusions if c.get("cause") == "no_forecast_issue"]
                            if no_forecast:
                                evidence = no_forecast[0].get("evidence", {})
                                st.write(f"**Last 3 Months Forecast:** {evidence.get('last_three_month_forecast', 0):.0f}")
                                st.write(f"**Actual PO Quantity:** {evidence.get('purchase_order_qty', 0):.0f}")
                                plot_forecast_chart()
                    elif tab == "supplier":
                        def plot_supplier_chart():
                            supplier_evidence = next((e["supplier_purchase_orders"] for e in report.get("evidence", []) if "supplier_purchase_orders" in e), {})
                            monthly_sample = next((e["monthly_sample"] for e in report.get("evidence", []) if "monthly_sample" in e), [])
                            if supplier_evidence:
                                st.write(f"**Supplier Ordered Qty:** {supplier_evidence.get('supplier_ordered_qty', 0):.0f}")
                                st.write(f"**Supplier Fulfilled Qty:** {supplier_evidence.get('supplier_received_qty', 0):.0f}")
                                s_monthly = supplier_evidence.get("supplier_monthly", [])
                                if s_monthly and monthly_sample:
                                    df_s = pd.DataFrame(s_monthly)
                                    df_m = pd.DataFrame(monthly_sample)
                                    df_m = filter_last_3_po_months(df_m)
                                    if not df_s.empty and not df_m.empty:
                                        df_s["month"] = pd.to_datetime(df_s["month"]).dt.strftime("%Y-%m")
                                        df_m["month"] = pd.to_datetime(df_m["month"]).dt.strftime("%Y-%m")
                                        df = pd.merge(df_m, df_s, on="month", how="outer").fillna(0)
                                        df = df.sort_values(by="month")
                                        df["month_label"] = pd.to_datetime(df["month"]).dt.strftime("%b %Y")
                                        df = df.rename(columns={"supplier_fulfilled_qty": "Supplier Fulfilled"})
                                        fig = px.bar(df, x="month_label", y=["Supplier Fulfilled", "Actual PO Quantity"], barmode="group",
                                                     title="Supplier Fulfilled vs Vendor PO Ordered", labels={"value": "Quantity", "variable": "Metric"})
                                        st.plotly_chart(fig, use_container_width=True)

                        if missing_supplier:
                            st.info("No supporting data found.")
                        elif supplier_causes:
                            cause = supplier_causes[0]
                            st.error(f"Yes, likely due to {_display_label(cause.get('cause'))} ({cause.get('confidence')} confidence).")
                            plot_supplier_chart()
                        else:
                            st.success("No supplier pipeline issues identified as the root cause.")
                            plot_supplier_chart()
                    elif tab == "inventory":
                        def plot_inventory_chart():
                            inventory_evidence = next((e["inventory_supply"] for e in report.get("evidence", []) if "inventory_supply" in e), {})
                            monthly_sample = next((e["monthly_sample"] for e in report.get("evidence", []) if "monthly_sample" in e), [])
                            if inventory_evidence:
                                st.write(f"**Inventory Qty Available:** {inventory_evidence.get('qty_available', 0):.0f}")
                                st.write(f"**PO Shortfall Qty:** {inventory_evidence.get('po_shortfall_qty', 0):.0f}")
                            if monthly_sample and inventory_evidence:
                                df_inv = pd.DataFrame(monthly_sample)
                                df_inv = filter_last_3_po_months(df_inv)
                                if not df_inv.empty:
                                    df_inv["month"] = pd.to_datetime(df_inv["month"]).dt.strftime("%b %Y")
                                    if "inventory_qty" in df_inv.columns:
                                        df_inv = df_inv.rename(columns={"inventory_qty": "Inventory"})
                                    else:
                                        df_inv["Inventory"] = inventory_evidence.get("qty_available", 0)
                                    fig = px.bar(df_inv, x="month", y=["Inventory", "Actual PO Quantity"], barmode="group",
                                                 title="Inventory vs PO Ordered", labels={"value": "Quantity", "variable": "Metric"})
                                    st.plotly_chart(fig, use_container_width=True)

                        if missing_inventory:
                            st.info("No supporting data found.")
                        elif inventory_causes:
                            cause = inventory_causes[0]
                            st.error(f"Yes, likely due to {_display_label(cause.get('cause'))} ({cause.get('confidence')} confidence).")
                            plot_inventory_chart()
                        else:
                            st.success("No inventory issues identified as the root cause.")
                            plot_inventory_chart()

        download_dataframe(risk_products, label="Export Risk Products")
    else:
        st.info("No risk product summary available.")


def page_forecast_analysis(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# Forecast Analysis")
    st.markdown("Analyze forecast trends, seasonality, bias, and pipeline consumption.")
    forecast_summary = client.forecast_summary()
    if not forecast_summary.empty:
        plot_line_chart(forecast_summary, x="forecast_month", y="forecast_qty", title="Monthly Forecast Trend")
    else:
        st.info("Forecast trend data is not available.")

    top_products = (
        forecasts.groupby("vendor_sku", as_index=False).agg(
            forecast_qty=("forecast_qty", "sum"),
            **({"product_description": ("product_description", "first")} if "product_description" in forecasts.columns else {}),
        )
        .sort_values(by="forecast_qty", ascending=False)
        .head(12)
    ) if "vendor_sku" in forecasts.columns else pd.DataFrame()
    if not top_products.empty:
        st.subheader("Top Forecasted Products")
        render_aggrid_table(top_products)
        download_dataframe(top_products, label="Export Top Forecasted Products")
    else:
        st.info("No forecasted product data is available.")

    if "brand" in forecasts.columns:
        brand_summary = (
            forecasts.groupby("brand")["forecast_qty"].sum().reset_index().sort_values(by="forecast_qty", ascending=False)
        )
        st.subheader("Brand Forecast Comparison")
        plot_bar_chart(brand_summary.head(12), x="brand", y="forecast_qty", title="Forecast Volume by Brand")


def page_po_acknowledgements(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# PO Acknowledgements")
    st.markdown("Review vendor acknowledgements, fill rates, partial acceptance, and delivery performance.")
    if acks.empty:
        st.info("Acknowledgement dataset is empty.")
        return

    acks["backorder_qty"] = acks["ordered_qty"].fillna(0) - acks["confirmed_qty"].fillna(0)
    summary = {
        "Total POs": len(acks["po_number"].dropna().unique()) if "po_number" in acks.columns else 0,
        "Ordered Qty": float(acks["ordered_qty"].sum()),
        "Confirmed Qty": float(acks["confirmed_qty"].sum()),
        "Backordered Qty": float(acks["backorder_qty"].clip(lower=0).sum()),
    }
    cols = st.columns(4)
    for idx, (label, value) in enumerate(summary.items()):
        cols[idx].metric(label, f"{value:,.0f}")

    if "vendor" in acks.columns:
        vendor_fill = (
            acks.groupby("vendor")[["ordered_qty", "confirmed_qty"]]
            .sum()
            .reset_index()
        )
        vendor_fill["fill_rate"] = vendor_fill.apply(
            lambda row: float(row["confirmed_qty"] / row["ordered_qty"]) if row["ordered_qty"] > 0 else 0.0,
            axis=1,
        )
        st.subheader("Vendor Fill Rate")
        plot_bar_chart(vendor_fill.sort_values(by="fill_rate", ascending=False).head(15), x="vendor", y="fill_rate", title="Vendor Fill Rate")
        st.subheader("Recent Acknowledgements")
        render_aggrid_table(acks.sort_values(by="delivery_date" if "delivery_date" in acks.columns else "po_number", ascending=False).head(30))
        download_dataframe(acks.head(100), label="Export Acknowledgements")


def page_cut_analysis(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# CUT Analysis")
    st.markdown("Investigate potential forecast cuts, product delists, and supply reductions.")
    search = st.text_input("Search PO Number, Product, Vendor SKU, Customer or Vendor")
    if search:
        forecast_matches, ack_matches = client.search_inventory(search)
        # Tables and calculations use the acknowledgement rows selected by
        # the global date filter, rather than the client's full history.
        ack_matches = ack_matches.loc[ack_matches.index.intersection(acks.index)]
        root_report = client.root_cause_analysis(product=search, acknowledgements=acks)
        st.subheader("Root Cause Summary")
        render_root_cause_report(root_report)

        st.subheader("Matched Forecast Records")
        render_aggrid_table(forecast_matches.head(50))
        st.subheader("Matched Acknowledgement Records")
        render_aggrid_table(ack_matches.head(50))
        inventory_matches = client.search_inventory_snapshot(search)
        if not inventory_matches.empty:
            st.subheader("Latest Inventory Snapshot")
            render_aggrid_table(inventory_matches)
        supplier_po_matches = client.search_supplier_pos(search, acknowledgements=acks)
        if not supplier_po_matches.empty:
            st.subheader("Supplier purchase orders")
            render_aggrid_table(supplier_po_matches)
        cut_supply = client.get_cut_supply_analysis(search, acknowledgements=acks)
        if cut_supply.empty and not ack_matches.empty and "vendor_sku" in ack_matches.columns:
            sku_values = ack_matches["vendor_sku"].dropna().astype(str).unique()
            cut_supply = client.get_cut_supply_analysis(acknowledgements=acks)
            cut_supply = cut_supply[cut_supply["vendor_sku"].isin(sku_values)]
        if not cut_supply.empty:
            st.subheader("Purchase order coverage")
            render_aggrid_table(cut_supply.head(50))
    else:
        st.info("Enter a search term to begin CUT analysis.")


def page_root_cause_analysis(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# Root Cause Analysis")
    st.markdown("Use product, vendor SKU, or PO number to generate a structured diagnosis.")
    product = st.text_input("Search product / SKU / PO number")
    if product:
        report = client.root_cause_analysis(product, acknowledgements=acks)
        render_root_cause_report(report)
    else:
        st.info("Enter a product or PO identifier to generate root cause insights.")


def page_vendor_performance(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# Vendor Performance")
    st.markdown("Score vendors on fill rate, delivery history, and reliability.")
    vendor_report = client.get_vendor_performance()
    if vendor_report.empty:
        st.info("Vendor performance data is unavailable.")
        return
    render_aggrid_table(vendor_report.head(50))
    plot_bar_chart(vendor_report.head(12), x="vendor", y="fill_rate", title="Top Vendor Fill Rates")
    download_dataframe(vendor_report, label="Export Vendor Performance")


def page_product_analytics(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# Product Analytics")
    st.markdown("Deep dive into product history for forecast, PO, and acknowledgement performance.")
    search = st.text_input("Search product / SKU / UPC / description")
    if search:
        forecast_matches, ack_matches = client.search_inventory(search)
        st.subheader("Forecast History")
        render_aggrid_table(forecast_matches.head(50))
        st.subheader("Acknowledgement History")
        render_aggrid_table(ack_matches.head(50))
        inventory_matches = client.search_inventory_snapshot(search)
        if not inventory_matches.empty:
            st.subheader("Latest Inventory Snapshot")
            render_aggrid_table(inventory_matches)
        timeline = client.get_product_timeline(search)
        if not timeline.empty:
            plot_line_chart(timeline, x="month", y="forecast_qty", title="Forecast Trend")
            plot_line_chart(timeline, x="month", y="confirmed_qty", title="Confirmed Trend")
    else:
        st.info("Enter a product search value to see product analytics.")


def page_demand_analysis(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# Demand Analysis")
    st.markdown("Detect demand spikes, volatility, and forecast consumption.")
    if forecasts.empty:
        st.info("Forecast dataset is empty.")
        return
    if "forecast_month" in forecasts.columns:
        demand = (
            forecasts.groupby(pd.to_datetime(forecasts["forecast_month"]).dt.to_period("M").dt.to_timestamp())["forecast_qty"]
            .sum()
            .reset_index()
            .rename(columns={"forecast_month": "month", "forecast_qty": "forecast_qty"})
        )
        plot_line_chart(demand, x="month", y="forecast_qty", title="Demand Trend")
    else:
        st.info("No forecast month data available for demand analysis.")


def page_forecast_accuracy(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# Forecast Accuracy")
    st.markdown("Measure forecast error, bias, and tracking signals.")
    fva = client.forecast_vs_actual()
    if fva.empty:
        st.info("No forecast accuracy data is available.")
        return
    fva = fva.assign(
        abs_error=(fva["forecast_qty"] - fva["actual_qty"]).abs(),
        pct_error=lambda df: np.where(df["forecast_qty"] > 0, (df["abs_error"] / df["forecast_qty"]) * 100, np.nan),
    )
    st.subheader("Monthly Forecast Error")
    render_aggrid_table(fva.head(25))
    plot_line_chart(fva, x="month", y="pct_error", title="Forecast Percentage Error")


def page_inventory_risk(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# Inventory Risk")
    st.markdown("Identify products with poor fill rates, demand volatility, and supply risk.")
    risk_products = client.get_cut_supply_analysis()
    if not risk_products.empty:
        risk_products = risk_products[risk_products["short_qty"] > 0].head(25)
        plot_bar_chart(risk_products, x="vendor_sku", y="uncovered_short_qty", title="Uncovered Inventory Risk")
        render_aggrid_table(risk_products)
    else:
        st.info("Inventory risk metrics are unavailable.")


def page_supply_risk(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# Supply Risk")
    st.markdown("Review vendor and product risk across the supply network.")
    vendor_report = client.get_vendor_performance()
    if vendor_report.empty:
        st.info("Supply risk data is unavailable.")
        return
    plot_bar_chart(vendor_report.head(20), x="vendor", y="fill_rate", title="Vendor Supply Risk")
    render_aggrid_table(vendor_report.head(30))


def page_exception_dashboard(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# Exception Dashboard")
    st.markdown("Focus on critical shortages, repeated issues, and high-risk purchase orders.")
    if acks.empty:
        st.info("Acknowledgement dataset is empty.")
        return
    exceptions = acks.copy()
    exceptions["short_qty"] = exceptions["ordered_qty"].fillna(0) - exceptions["confirmed_qty"].fillna(0)
    inventory_supply = client.get_cut_supply_analysis()[["vendor_sku", "qty_available", "supplier_po_qty", "uncovered_short_qty", "cut_reason"]]
    top_exceptions = exceptions.merge(inventory_supply, on="vendor_sku", how="left").sort_values(by="short_qty", ascending=False).head(25)
    render_aggrid_table(top_exceptions)
    st.subheader("Largest Shortages")
    download_dataframe(top_exceptions, label="Export Exceptions")


def page_ai_copilot(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# AI Supply Chain Copilot")
    st.markdown("Ask a conversational question and receive evidence-based supply chain insights.")
    question = st.text_area("Ask a question", height=120)
    if st.button("Analyze question") and question:
        answer = generate_copilot_response(question, forecasts, acks, client)
        st.subheader("Response")
        st.write(answer)
    elif question:
        st.info("Press the analyze button to generate a response.")


def generate_copilot_response(question: str, forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> str:
    q = question.lower()
    if "po" in q and "short" in q:
        candidate = q.split()[-1]
        report = client.root_cause_analysis(candidate)
        return summarize_root_cause(report)
    if "sku" in q or "product" in q or "upc" in q:
        candidate = q.split()[-1]
        report = client.root_cause_analysis(candidate)
        return summarize_root_cause(report)
    if "vendor" in q:
        vendor = q.split()[-1]
        vendor_report = client.get_vendor_performance()
        rows = vendor_report[vendor_report["vendor"].str.contains(vendor, case=False, na=False)]
        if not rows.empty:
            return f"Vendor {vendor} has an average fill rate of {rows['fill_rate'].mean():.2%}. Review the top 10 POs for late confirmations."
    return "I am reviewing supply and forecast data. Please narrow the question to a product, PO number, or vendor." 


def summarize_root_cause(report: dict[str, Any]) -> str:
    confidence = report.get("confidence", 0.0)
    conclusions = report.get("conclusions", [])
    recommendations = report.get("recommendations", [])
    summary_lines = [f"Confidence: {confidence * 100:.0f}%."]
    if conclusions:
        for conclusion in conclusions:
            summary_lines.append(f"Possible cause: {conclusion.get('cause', 'unknown')} ({conclusion.get('confidence', 'low')}).")
    if recommendations:
        summary_lines.append("Recommendations:")
        summary_lines.extend([f"- {item}" for item in recommendations[:4]])
    return "\n".join(summary_lines)


def page_settings(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# Settings")
    st.markdown("Manage the dashboard, refresh data, and review configuration.")
    st.subheader("Configuration")
    config = pd.json_normalize(client.cfg.model_dump()).rename(
        columns=lambda column: _display_label(column.replace(".", " "))
    )
    st.dataframe(config, hide_index=True)
    if st.button("Refresh data cache"):
        client.refresh_data()
        # `load_data` is cached separately from the client.  Clear it so the
        # rerun uses the newly loaded, deduplicated forecast snapshots.
        load_data.clear()
        st.experimental_rerun()
    st.markdown("---")


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide", page_icon="📊")
    if "theme" not in st.session_state:
        st.session_state.theme = "light"
    st.sidebar.title(APP_TITLE)
    st.sidebar.markdown("### Theme")
    if "theme" not in st.session_state:
        st.session_state.theme = "light"

    st.sidebar.radio(

    "Dashboard Theme",

    ["dark", "light"],

    key="theme",

)
    load_app_style(st.session_state.theme)
    client = get_client()
    forecasts, acks, filter_options, date_ranges = load_data()

    if "page" not in st.session_state:
        st.session_state.page = MENU_ITEMS[0]

    page = render_sidebar_menu(st.session_state.page, MENU_ITEMS)
    st.session_state.page = page

    filters = build_filter_controls(filter_options, date_ranges)
    forecasts, acks = parse_date_filters(filters, forecasts, acks)
    forecasts, acks = filter_data(forecasts, acks, filters)

    if page == "Dashboard":
        page_dashboard(forecasts, acks, client)
    elif page == "Forecast Analysis":
        page_forecast_analysis(forecasts, acks, client)
    elif page == "PO Acknowledgements":
        page_po_acknowledgements(forecasts, acks, client)
    elif page == "CUT Analysis":
        page_cut_analysis(forecasts, acks, client)
    elif page == "Root Cause Analysis":
        page_root_cause_analysis(forecasts, acks, client)
    elif page == "Vendor Performance":
        page_vendor_performance(forecasts, acks, client)
    elif page == "Product Analytics":
        page_product_analytics(forecasts, acks, client)
    elif page == "Demand Analysis":
        page_demand_analysis(forecasts, acks, client)
    elif page == "Forecast Accuracy":
        page_forecast_accuracy(forecasts, acks, client)
    elif page == "Inventory Risk":
        page_inventory_risk(forecasts, acks, client)
    elif page == "Supply Risk":
        page_supply_risk(forecasts, acks, client)
    elif page == "Exception Dashboard":
        page_exception_dashboard(forecasts, acks, client)
    elif page == "AI Supply Chain Copilot":
        page_ai_copilot(forecasts, acks, client)
    elif page == "Settings":
        page_settings(forecasts, acks, client)
    else:
        st.warning("Please select a page from the navigation menu.")


if __name__ == "__main__":
    main()

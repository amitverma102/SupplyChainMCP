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


@st.cache_data(show_spinner=False)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, list[str]], dict[str, tuple[date | None, date | None]]]:
    client = get_client()
    forecasts = client.forecast_df
    acks = client.ack_df
    filter_options = client.get_filter_options()
    date_ranges = client.get_date_ranges()
    return forecasts, acks, filter_options, date_ranges


def apply_filters(df: pd.DataFrame, filters: dict[str, list[str]]) -> pd.DataFrame:
    if df.empty:
        return df
    for key, selected in filters.items():
        if not selected or key not in df.columns:
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
        start_date, end_date = filters["forecast_month"][0]
        if not pd.isna(start_date) and not pd.isna(end_date):
            forecasts = forecasts[
                (forecasts["forecast_month"] >= pd.to_datetime(start_date))
                & (forecasts["forecast_month"] <= pd.to_datetime(end_date))
            ]
    if "ack_date" in filters and filters["ack_date"]:
        start_date, end_date = filters["ack_date"][0]
        if not pd.isna(start_date) and not pd.isna(end_date):
            if "delivery_date" in acks.columns:
                acks = acks[
                    (pd.to_datetime(acks["delivery_date"], errors="coerce") >= pd.to_datetime(start_date))
                    & (pd.to_datetime(acks["delivery_date"], errors="coerce") <= pd.to_datetime(end_date))
                ]
            elif "po_date" in acks.columns:
                acks = acks[
                    (pd.to_datetime(acks["po_date"], errors="coerce") >= pd.to_datetime(start_date))
                    & (pd.to_datetime(acks["po_date"], errors="coerce") <= pd.to_datetime(end_date))
                ]
    return forecasts, acks


def compute_kpis(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> dict[str, dict[str, Any]]:
    metrics = client.compute_dashboard_kpis()
    return {
        "Forecast Value": {"value": f"{metrics['forecast_value']:,.0f}", "delta": "", "detail": "Total forecast value"},
        "Ordered Quantity": {"value": f"{metrics['ordered_quantity']:,.0f}", "delta": "", "detail": "Total ordered units"},
        "Confirmed Quantity": {"value": f"{metrics['confirmed_quantity']:,.0f}", "delta": "", "detail": "Total confirmed units"},
        "Fill Rate": {"value": f"{metrics['fill_rate'] * 100:.1f}%", "delta": "", "detail": "Confirmed / ordered"},
        "Forecast Accuracy": {"value": f"{metrics.get('forecast_accuracy', 0.0) * 100:.1f}%", "delta": "", "detail": "MAPE"},
        "WMAPE": {"value": f"{metrics.get('wmape', 0.0) * 100:.1f}%", "delta": "", "detail": "Weighted MAPE"},
        "Products Short": {"value": f"{int(metrics['products_short']):,}", "delta": "", "detail": "Products with short supply"},
        "High Risk Vendors": {"value": f"{int(metrics.get('high_risk_vendors', 0)):,}", "delta": "", "detail": "Low fill-rate vendors"},
    }


def page_dashboard(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# Executive Dashboard")
    st.markdown("Modern enterprise metrics for supply chain control and investigation.")

    metrics = compute_kpis(forecasts, acks, client)
    cards = []
    for label, payload in metrics.items():
        cards.append({"label": label, **payload, "action": "Explore", "target": "Forecast Analysis"})
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
    risk_products = client.get_top_risk_products(10)
    if not risk_products.empty:
        render_aggrid_table(risk_products)
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
        st.subheader("Matched Forecast Records")
        render_aggrid_table(forecast_matches.head(50))
        st.subheader("Matched Acknowledgement Records")
        render_aggrid_table(ack_matches.head(50))
        root_report = client.root_cause_analysis(product=search)
        st.subheader("Root Cause Summary")
        st.write(root_report)
    else:
        st.info("Enter a search term to begin CUT analysis.")


def page_root_cause_analysis(forecasts: pd.DataFrame, acks: pd.DataFrame, client: SupplyChainMCPClient) -> None:
    st.markdown("# Root Cause Analysis")
    st.markdown("Use product, vendor SKU, or PO number to generate a structured diagnosis.")
    product = st.text_input("Search product / SKU / PO number")
    if product:
        report = client.root_cause_analysis(product)
        st.metric("Confidence", f"{report.get('confidence', 0.0) * 100:.0f}%")
        if report.get("summary"):
            st.write(report["summary"])
        if report.get("evidence"):
            for item in report["evidence"]:
                st.write(item)
        if report.get("conclusions"):
            st.write(report["conclusions"])
        if report.get("recommendations"):
            st.subheader("Recommendations")
            for rec in report["recommendations"]:
                st.write(f"- {rec}")
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
    risk_products = client.get_top_risk_products(25)
    if not risk_products.empty:
        plot_bar_chart(risk_products, x="vendor_sku", y="risk_score", title="Inventory Risk Score")
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
    top_exceptions = exceptions.sort_values(by="short_qty", ascending=False).head(25)
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
            return f"Vendor {vendor} has an average fill rate of {rows['fill_rate'].mean():.1%}. Review the top 10 POs for late confirmations."
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
    # Pydantic v2 removed keyword arguments from ``.json()``; serialize with
    # ``model_dump_json()`` so the configuration remains nicely formatted.
    st.code(client.cfg.model_dump_json(indent=2), language="json")
    if st.button("Refresh data cache"):
        client.refresh_data()
        # `load_data` is cached separately from the client.  Clear it so the
        # rerun uses the newly loaded, deduplicated forecast snapshots.
        load_data.clear()
        st.experimental_rerun()
    st.markdown("---")
    st.write("Streamlit session state:")
    st.write(st.session_state)


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

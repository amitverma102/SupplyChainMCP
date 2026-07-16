from __future__ import annotations
import logging
from typing import Optional, Dict, Any
import pandas as pd
import polars as pl
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import numpy as np
from pathlib import Path

logger = logging.getLogger(__name__)


class ReportingService:
    """Generate interactive Plotly dashboards for supply chain analytics."""

    def __init__(self, forecasts: Optional[pl.DataFrame], acks: Optional[pd.DataFrame], reports_dir: str | Path = "reports"):
        self.forecasts = forecasts if forecasts is not None else pl.DataFrame()
        self.acks = acks if acks is not None else pd.DataFrame()
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def forecast_vs_actual_chart(self, output_file: Optional[str | Path] = None) -> go.Figure:
        """Generate a line chart comparing monthly forecast vs actual confirmed quantities."""
        try:
            if self.forecasts.is_empty() and self.acks.empty:
                return self._empty_figure("No data available")

            # aggregate by month
            f_df = self.forecasts.to_pandas() if not self.forecasts.is_empty() else pd.DataFrame()
            a_df = self.acks

            months = []
            forecast_qty = []
            actual_qty = []

            if not f_df.empty and "forecast_month_parsed" in f_df.columns:
                f_agg = f_df.groupby(pd.to_datetime(f_df["forecast_month_parsed"], errors="coerce").dt.to_period("M"))["forecast_qty"].sum()
                for period, qty in f_agg.items():
                    months.append(str(period))
                    forecast_qty.append(float(qty))

            if not a_df.empty and "delivery_date" in a_df.columns:
                a_agg = a_df.groupby(pd.to_datetime(a_df["delivery_date"], errors="coerce").dt.to_period("M"))["confirmed_qty"].sum()
                for period, qty in a_agg.items():
                    if str(period) not in months:
                        months.append(str(period))
                        forecast_qty.append(0.0)
                    else:
                        idx = months.index(str(period))
                        if len(actual_qty) <= idx:
                            actual_qty.extend([0.0] * (idx - len(actual_qty) + 1))
                    if len(actual_qty) <= months.index(str(period)):
                        actual_qty.extend([0.0] * (months.index(str(period)) - len(actual_qty) + 1))
                    actual_qty[months.index(str(period))] = float(qty)

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=months, y=forecast_qty, mode="lines+markers", name="Forecast", line=dict(color="blue", width=2)))
            fig.add_trace(go.Scatter(x=months, y=actual_qty, mode="lines+markers", name="Actual", line=dict(color="green", width=2)))

            fig.update_layout(
                title="Forecast vs Actual Confirmed Quantity",
                xaxis_title="Month",
                yaxis_title="Quantity",
                hovermode="x unified",
                template="plotly_white",
                height=500,
            )

            if output_file:
                fig.write_html(str(self.reports_dir / output_file))
            return fig
        except Exception as e:
            logger.exception("Failed to generate forecast_vs_actual_chart: %s", e)
            return self._empty_figure(f"Error: {str(e)}")

    def vendor_performance_chart(self, output_file: Optional[str | Path] = None) -> go.Figure:
        """Generate a bar chart of vendor fill rates."""
        try:
            if self.acks.empty:
                return self._empty_figure("No acknowledgement data available")

            a_df = self.acks.copy()
            if "vendor" not in a_df.columns or "confirmed_qty" not in a_df.columns or "ordered_qty" not in a_df.columns:
                return self._empty_figure("Missing required columns (vendor, confirmed_qty, ordered_qty)")

            vendor_stats = []
            for vendor in a_df["vendor"].unique():
                if pd.isna(vendor):
                    continue
                vendor_data = a_df[a_df["vendor"] == vendor]
                total_ordered = vendor_data["ordered_qty"].sum()
                total_confirmed = vendor_data["confirmed_qty"].sum()
                fill_rate = (total_confirmed / total_ordered * 100) if total_ordered > 0 else 0.0
                vendor_stats.append({"vendor": vendor, "fill_rate": fill_rate, "orders": len(vendor_data)})

            df_stats = pd.DataFrame(vendor_stats).sort_values("fill_rate", ascending=False)

            fig = go.Figure(
                data=[go.Bar(x=df_stats["vendor"], y=df_stats["fill_rate"], marker=dict(color=df_stats["fill_rate"], colorscale="RdYlGn"))]
            )
            fig.update_layout(
                title="Vendor Fill Rate Performance",
                xaxis_title="Vendor",
                yaxis_title="Fill Rate (%)",
                template="plotly_white",
                height=500,
                showlegend=False,
            )

            if output_file:
                fig.write_html(str(self.reports_dir / output_file))
            return fig
        except Exception as e:
            logger.exception("Failed to generate vendor_performance_chart: %s", e)
            return self._empty_figure(f"Error: {str(e)}")

    def demand_trend_chart(self, output_file: Optional[str | Path] = None) -> go.Figure:
        """Generate a line chart of demand trends over time."""
        try:
            if self.acks.empty:
                return self._empty_figure("No acknowledgement data available")

            a_df = self.acks.copy()
            if "delivery_date" not in a_df.columns or "ordered_qty" not in a_df.columns:
                return self._empty_figure("Missing required columns (delivery_date, ordered_qty)")

            a_df["delivery_month"] = pd.to_datetime(a_df["delivery_date"], errors="coerce").dt.to_period("M").astype(str)
            demand_by_month = a_df.groupby("delivery_month")["ordered_qty"].sum()

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=demand_by_month.index, y=demand_by_month.values, mode="lines+markers", fill="tozeroy", name="Total Demand"))

            fig.update_layout(
                title="Monthly Demand Trend",
                xaxis_title="Month",
                yaxis_title="Total Ordered Quantity",
                template="plotly_white",
                height=500,
                hovermode="x unified",
            )

            if output_file:
                fig.write_html(str(self.reports_dir / output_file))
            return fig
        except Exception as e:
            logger.exception("Failed to generate demand_trend_chart: %s", e)
            return self._empty_figure(f"Error: {str(e)}")

    def fill_rate_distribution_chart(self, output_file: Optional[str | Path] = None) -> go.Figure:
        """Generate a histogram of fill rate distribution across products."""
        try:
            if self.acks.empty:
                return self._empty_figure("No acknowledgement data available")

            a_df = self.acks.copy()
            if "vendor_sku" not in a_df.columns or "ordered_qty" not in a_df.columns or "confirmed_qty" not in a_df.columns:
                return self._empty_figure("Missing required columns")

            product_stats = []
            for sku in a_df["vendor_sku"].unique():
                if pd.isna(sku):
                    continue
                sku_data = a_df[a_df["vendor_sku"] == sku]
                total_ordered = sku_data["ordered_qty"].sum()
                total_confirmed = sku_data["confirmed_qty"].sum()
                fill_rate = (total_confirmed / total_ordered * 100) if total_ordered > 0 else 0.0
                product_stats.append(fill_rate)

            fig = go.Figure(data=[go.Histogram(x=product_stats, nbinsx=20, marker=dict(color="steelblue"))])
            fig.update_layout(
                title="Product Fill Rate Distribution",
                xaxis_title="Fill Rate (%)",
                yaxis_title="Number of Products",
                template="plotly_white",
                height=500,
            )

            if output_file:
                fig.write_html(str(self.reports_dir / output_file))
            return fig
        except Exception as e:
            logger.exception("Failed to generate fill_rate_distribution_chart: %s", e)
            return self._empty_figure(f"Error: {str(e)}")

    def customer_ordering_behavior_chart(self, output_file: Optional[str | Path] = None) -> go.Figure:
        """Generate a scatter plot of order vs forecast ratio by customer."""
        try:
            if self.acks.empty or self.forecasts.is_empty():
                return self._empty_figure("Missing forecast or acknowledgement data")

            a_df = self.acks.copy()
            if "customer" not in a_df.columns or "ordered_qty" not in a_df.columns:
                return self._empty_figure("Missing required columns in acks")

            customer_stats = []
            for customer in a_df["customer"].unique():
                if pd.isna(customer):
                    continue
                customer_data = a_df[a_df["customer"] == customer]
                avg_order = customer_data["ordered_qty"].mean()
                total_orders = len(customer_data)
                customer_stats.append({"customer": customer, "avg_order": avg_order, "order_count": total_orders})

            df_cust = pd.DataFrame(customer_stats)

            fig = go.Figure(
                data=[go.Scatter(x=df_cust["avg_order"], y=df_cust["order_count"], mode="markers+text", text=df_cust["customer"], marker=dict(size=10, color="coral"))]
            )
            fig.update_layout(
                title="Customer Ordering Behavior",
                xaxis_title="Average Order Size",
                yaxis_title="Number of Orders",
                template="plotly_white",
                height=500,
                hovermode="closest",
            )

            if output_file:
                fig.write_html(str(self.reports_dir / output_file))
            return fig
        except Exception as e:
            logger.exception("Failed to generate customer_ordering_behavior_chart: %s", e)
            return self._empty_figure(f"Error: {str(e)}")

    def forecast_accuracy_gauge(self, output_file: Optional[str | Path] = None) -> go.Figure:
        """Generate a gauge chart for overall forecast accuracy (MAPE)."""
        try:
            if self.forecasts.is_empty() or self.acks.empty:
                return self._empty_figure("Missing data")

            f_df = self.forecasts.to_pandas()
            a_df = self.acks

            # simple accuracy: (actual / forecast) where we have both
            accuracies = []
            if not f_df.empty and "forecast_month_parsed" in f_df.columns and not a_df.empty and "delivery_date" in a_df.columns:
                f_agg = f_df.groupby(pd.to_datetime(f_df["forecast_month_parsed"], errors="coerce").dt.to_period("M"))["forecast_qty"].sum()
                a_agg = a_df.groupby(pd.to_datetime(a_df["delivery_date"], errors="coerce").dt.to_period("M"))["confirmed_qty"].sum()

                for period in f_agg.index:
                    if period in a_agg.index:
                        f_qty = f_agg[period]
                        a_qty = a_agg[period]
                        if f_qty > 0:
                            accuracy = min(100, (a_qty / f_qty) * 100)
                            accuracies.append(accuracy)

            overall_accuracy = np.mean(accuracies) if accuracies else 50.0

            fig = go.Figure(
                data=[
                    go.Indicator(
                        mode="gauge+number+delta",
                        value=overall_accuracy,
                        title={"text": "Forecast Accuracy (%)"},
                        delta={"reference": 85},
                        gauge={
                            "axis": {"range": [0, 100]},
                            "bar": {"color": "darkblue"},
                            "steps": [
                                {"range": [0, 50], "color": "lightgray"},
                                {"range": [50, 85], "color": "gray"},
                                {"range": [85, 100], "color": "lightgreen"},
                            ],
                            "threshold": {
                                "line": {"color": "red", "width": 4},
                                "thickness": 0.75,
                                "value": 85,
                            },
                        },
                    )
                ]
            )
            fig.update_layout(height=500)

            if output_file:
                fig.write_html(str(self.reports_dir / output_file))
            return fig
        except Exception as e:
            logger.exception("Failed to generate forecast_accuracy_gauge: %s", e)
            return self._empty_figure(f"Error: {str(e)}")

    def supply_chain_dashboard(self, output_file: str | Path = "dashboard.html") -> go.Figure:
        """Generate a comprehensive supply chain dashboard with multiple subplots."""
        try:
            fig = make_subplots(
                rows=2,
                cols=2,
                subplot_titles=("Forecast vs Actual", "Vendor Fill Rates", "Demand Trend", "Fill Rate Distribution"),
                specs=[[{"secondary_y": False}, {"secondary_y": False}], [{"secondary_y": False}, {"secondary_y": False}]],
            )

            # Forecast vs Actual
            if not self.forecasts.is_empty():
                f_df = self.forecasts.to_pandas()
                if "forecast_month_parsed" in f_df.columns:
                    f_agg = f_df.groupby(pd.to_datetime(f_df["forecast_month_parsed"], errors="coerce").dt.to_period("M"))["forecast_qty"].sum()
                    fig.add_trace(
                        go.Scatter(x=[str(p) for p in f_agg.index], y=f_agg.values, mode="lines", name="Forecast"),
                        row=1,
                        col=1,
                    )

            if not self.acks.empty and "delivery_date" in self.acks.columns:
                a_agg = self.acks.groupby(pd.to_datetime(self.acks["delivery_date"], errors="coerce").dt.to_period("M"))["confirmed_qty"].sum()
                fig.add_trace(
                    go.Scatter(x=[str(p) for p in a_agg.index], y=a_agg.values, mode="lines", name="Actual"),
                    row=1,
                    col=1,
                )

            # Vendor fill rates
            if not self.acks.empty and "vendor" in self.acks.columns:
                vendor_stats = []
                for vendor in self.acks["vendor"].unique():
                    if pd.isna(vendor):
                        continue
                    vendor_data = self.acks[self.acks["vendor"] == vendor]
                    total_ordered = vendor_data["ordered_qty"].sum()
                    total_confirmed = vendor_data["confirmed_qty"].sum()
                    fill_rate = (total_confirmed / total_ordered * 100) if total_ordered > 0 else 0.0
                    vendor_stats.append({"vendor": vendor, "fill_rate": fill_rate})

                if vendor_stats:
                    df_vendors = pd.DataFrame(vendor_stats).sort_values("fill_rate", ascending=False).head(10)
                    fig.add_trace(
                        go.Bar(x=df_vendors["vendor"], y=df_vendors["fill_rate"], name="Fill Rate", showlegend=False),
                        row=1,
                        col=2,
                    )

            # Demand trend
            if not self.acks.empty and "delivery_date" in self.acks.columns and "ordered_qty" in self.acks.columns:
                a_df = self.acks.copy()
                a_df["month"] = pd.to_datetime(a_df["delivery_date"], errors="coerce").dt.to_period("M").astype(str)
                demand_by_month = a_df.groupby("month")["ordered_qty"].sum()
                fig.add_trace(
                    go.Scatter(x=demand_by_month.index, y=demand_by_month.values, mode="lines+markers", name="Demand", showlegend=False, fill="tozeroy"),
                    row=2,
                    col=1,
                )

            # Fill rate distribution
            if not self.acks.empty and "vendor_sku" in self.acks.columns:
                product_stats = []
                for sku in self.acks["vendor_sku"].unique():
                    if pd.isna(sku):
                        continue
                    sku_data = self.acks[self.acks["vendor_sku"] == sku]
                    total_ordered = sku_data["ordered_qty"].sum()
                    total_confirmed = sku_data["confirmed_qty"].sum()
                    fill_rate = (total_confirmed / total_ordered * 100) if total_ordered > 0 else 0.0
                    product_stats.append(fill_rate)

                if product_stats:
                    fig.add_trace(
                        go.Histogram(x=product_stats, nbinsx=20, name="Products", showlegend=False),
                        row=2,
                        col=2,
                    )

            fig.update_xaxes(title_text="Month", row=1, col=1)
            fig.update_yaxes(title_text="Quantity", row=1, col=1)
            fig.update_xaxes(title_text="Vendor", row=1, col=2)
            fig.update_yaxes(title_text="Fill Rate (%)", row=1, col=2)
            fig.update_xaxes(title_text="Month", row=2, col=1)
            fig.update_yaxes(title_text="Ordered Qty", row=2, col=1)
            fig.update_xaxes(title_text="Fill Rate (%)", row=2, col=2)
            fig.update_yaxes(title_text="# Products", row=2, col=2)

            fig.update_layout(height=800, title_text="Supply Chain Analytics Dashboard", showlegend=True, template="plotly_white")
            fig.write_html(str(self.reports_dir / output_file))
            logger.info("Generated supply chain dashboard: %s", self.reports_dir / output_file)
            return fig
        except Exception as e:
            logger.exception("Failed to generate supply_chain_dashboard: %s", e)
            return self._empty_figure(f"Error: {str(e)}")

    def _empty_figure(self, message: str) -> go.Figure:
        """Return an empty figure with a message."""
        fig = go.Figure()
        fig.add_annotation(text=message, xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(size=14))
        return fig

    def export_report_json(self, output_file: str | Path = "report.json") -> Dict[str, Any]:
        """Export analytics summary as JSON."""
        try:
            summary = {
                "forecast_records": 0 if self.forecasts.is_empty() else len(self.forecasts),
                "ack_records": len(self.acks),
                "vendors": 0,
                "customers": 0,
                "products": 0,
            }

            if not self.acks.empty:
                if "vendor" in self.acks.columns:
                    summary["vendors"] = int(self.acks["vendor"].nunique())
                if "customer" in self.acks.columns:
                    summary["customers"] = int(self.acks["customer"].nunique())
                if "vendor_sku" in self.acks.columns:
                    summary["products"] = int(self.acks["vendor_sku"].nunique())

            import json
            with open(self.reports_dir / output_file, "w") as f:
                json.dump(summary, f, indent=2)

            logger.info("Exported report JSON: %s", self.reports_dir / output_file)
            return summary
        except Exception as e:
            logger.exception("Failed to export report JSON: %s", e)
            return {}


__all__ = ["ReportingService"]

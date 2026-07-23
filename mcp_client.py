from __future__ import annotations
from pathlib import Path
from typing import Optional

import pandas as pd
import polars as pl

from config import load_config
from services.acknowledgement_service import AcknowledgementService
from services.analytics_service import AnalyticsService
from services.cache_service import CacheService
from services.forecast_service import ForecastService
from services.inventory_service import InventoryService
from services.root_cause_service import RootCauseService


BASE_DIR = Path(__file__).resolve().parent


def resolve_dir(p: str | Path, base: Path = BASE_DIR.parent) -> Path:
    directory = Path(p)
    if not directory.is_absolute():
        directory = base / directory
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def count_unique_short_skus(acks: pd.DataFrame) -> int:
    """Count SKUs whose total confirmed quantity is short across all POs."""
    required_columns = {"vendor_sku", "ordered_qty", "confirmed_qty"}
    if acks.empty or not required_columns.issubset(acks.columns):
        return 0

    sku = acks["vendor_sku"].astype("string").str.strip()
    valid_sku = sku.notna() & sku.ne("")
    if not valid_sku.any():
        return 0

    totals = (
        acks.loc[valid_sku, ["ordered_qty", "confirmed_qty"]]
        .assign(vendor_sku=sku.loc[valid_sku])
        .groupby("vendor_sku", dropna=True)[["ordered_qty", "confirmed_qty"]]
        .sum()
    )
    return int((totals["ordered_qty"] > totals["confirmed_qty"]).sum())


class SupplyChainMCPClient:
    """Client wrapper for SupplyChainMCP service classes and analytics integration."""

    def __init__(self, config_path: str | Path | None = None):
        config_path = Path(config_path) if config_path else BASE_DIR / "config.yaml"
        self.config_path = config_path
        self.cfg = load_config(config_path)
        self.base_dir = config_path.resolve().parent

        self.forecasts_dir = resolve_dir(self.cfg.app.forecasts_dir, self.base_dir)
        self.acknowledgements_dir = resolve_dir(self.cfg.app.acknowledgements_dir, self.base_dir)
        self.inventory_dir = resolve_dir(self.cfg.app.inventory_dir, self.base_dir)
        self.cache_dir = resolve_dir(self.cfg.app.cache_dir, self.base_dir)
        self.reports_dir = resolve_dir(self.cfg.app.reports_dir, self.base_dir)

        self.cache = CacheService(self.cache_dir / "metadata.db")
        self.forecast_service = ForecastService(self.forecasts_dir, cache_service=self.cache)
        self.ack_service = AcknowledgementService(self.acknowledgements_dir, cache_service=self.cache)
        self.inventory_service = InventoryService(self.inventory_dir)
        self.analytics = AnalyticsService()

        self._forecasts: Optional[pl.DataFrame] = None
        self._acks: Optional[pd.DataFrame] = None
        self._inventory: Optional[pd.DataFrame] = None

    def load_forecasts(self, force: bool = False) -> pl.DataFrame:
        if self._forecasts is None or force:
            self._forecasts = self.forecast_service.load_all(incremental=not force)
            self._register_data()
        return self._forecasts

    def load_acknowledgements(self, force: bool = False) -> pd.DataFrame:
        if self._acks is None or force:
            self._acks = self.ack_service.load_all()
            self._register_data()
        return self._acks

    def load_inventory(self, force: bool = False) -> pd.DataFrame:
        if self._inventory is None or force:
            self._inventory = self.inventory_service.load_latest()
        return self._inventory

    def _register_data(self) -> None:
        self.analytics = AnalyticsService()
        if self._forecasts is not None and len(self._forecasts) > 0:
            self.analytics.register_forecasts(self._forecasts, name="forecasts")
        if self._acks is not None and not self._acks.empty and len(self._acks.columns) > 0:
            self.analytics.register_acknowledgements(self._acks, name="acks")

    def refresh_data(self) -> tuple[pl.DataFrame, pd.DataFrame]:
        self._forecasts = None
        self._acks = None
        self._inventory = None
        return self.load_forecasts(force=True), self.load_acknowledgements(force=True)

    @property
    def forecast_df(self) -> pd.DataFrame:
        df = self.load_forecasts().to_pandas()
        if "forecast_month_parsed" in df:
            df["forecast_month"] = pd.to_datetime(df["forecast_month_parsed"], errors="coerce")
        return df

    @property
    def ack_df(self) -> pd.DataFrame:
        return self.load_acknowledgements().copy()

    @property
    def inventory_df(self) -> pd.DataFrame:
        return self.load_inventory().copy()

    def forecast_summary(self) -> pd.DataFrame:
        try:
            return self.analytics.forecast_summary()
        except Exception:
            return pd.DataFrame()

    def forecast_vs_actual(self) -> pd.DataFrame:
        try:
            return self.analytics.forecast_vs_actual()
        except Exception:
            return pd.DataFrame()

    def get_filter_options(self) -> dict[str, list[str]]:
        forecast = self.forecast_df
        acks = self.ack_df
        fields = {
            "customer": ["customer"],
            "vendor": ["vendor"],
            "brand": ["brand"],
            "department": ["department"],
            "product": ["vendor_sku", "buyer_part_number", "upc", "description"],
            "vendor_sku": ["vendor_sku"],
            "upc": ["upc"],
            "buyer_part_number": ["buyer_part_number"],
            "po_number": ["po_number"],
        }
        options: dict[str, list[str]] = {}
        for key, cols in fields.items():
            values: pd.Series = pd.Series([], dtype=str)
            for col in cols:
                if col in forecast.columns:
                    values = pd.concat([values, forecast[col].astype(str).fillna("")])
                if col in acks.columns:
                    values = pd.concat([values, acks[col].astype(str).fillna("")])
            values = values[values.str.strip() != ""].drop_duplicates().sort_values()
            if not values.empty:
                options[key] = values.tolist()
        return options

    def get_date_ranges(self) -> dict[str, tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]]:
        ranges: dict[str, tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]] = {
            "forecast_month": (None, None),
            "ack_date": (None, None),
        }
        forecast = self.forecast_df
        acks = self.ack_df
        if "forecast_month" in forecast.columns:
            forecast_dates = pd.to_datetime(forecast["forecast_month"], errors="coerce")
            ranges["forecast_month"] = (forecast_dates.min(), forecast_dates.max())
        if "delivery_date" in acks.columns:
            ack_dates = pd.to_datetime(acks["delivery_date"], errors="coerce")
            ranges["ack_date"] = (ack_dates.min(), ack_dates.max())
        if "po_date" in acks.columns:
            po_dates = pd.to_datetime(acks["po_date"], errors="coerce")
            ranges["ack_date"] = (ranges["ack_date"][0] or po_dates.min(), ranges["ack_date"][1] or po_dates.max())
        return ranges

    def search_inventory(self, query: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        if not query:
            return self.forecast_df, self.ack_df
        query = str(query).strip()
        forecast = self.forecast_df
        acks = self.ack_df
        search_mask = pd.Series(False, index=forecast.index)
        for col in ["vendor_sku", "buyer_part_number", "upc", "description", "brand", "department"]:
            if col in forecast.columns:
                search_mask = search_mask | forecast[col].astype(str).str.contains(query, case=False, na=False)
        product_matches = forecast[search_mask]

        ack_mask = pd.Series(False, index=acks.index)
        for col in ["vendor_sku", "buyer_part_number", "upc", "po_number", "vendor", "customer"]:
            if col in acks.columns:
                ack_mask = ack_mask | acks[col].astype(str).str.contains(query, case=False, na=False)
        ack_matches = acks[ack_mask]

        # A PO number is only present in acknowledgement records.  Once the
        # PO lines are found, use their product identifiers to retrieve every
        # corresponding forecast record (including all forecast months).
        if not ack_matches.empty:
            related_forecast_mask = pd.Series(False, index=forecast.index)
            for column in ["vendor_sku", "buyer_part_number", "upc"]:
                if column not in ack_matches.columns or column not in forecast.columns:
                    continue
                identifiers = (
                    ack_matches[column]
                    .astype("string")
                    .str.strip()
                    .dropna()
                )
                identifiers = identifiers[identifiers.ne("")].unique()
                if len(identifiers):
                    related_forecast_mask |= (
                        forecast[column].astype("string").str.strip().isin(identifiers)
                    )
            if related_forecast_mask.any():
                product_matches = pd.concat(
                    [product_matches, forecast[related_forecast_mask]]
                ).drop_duplicates()
        return product_matches, ack_matches

    def get_product_timeline(self, query: str) -> pd.DataFrame:
        forecast, acks = self.search_inventory(query)
        if forecast.empty and acks.empty:
            return pd.DataFrame()
        forecast_history = (
            forecast.groupby(pd.to_datetime(forecast["forecast_month"]).dt.to_period("M").dt.to_timestamp())
            ["forecast_qty"].sum()
            .rename("forecast_qty")
            .reset_index()
        )
        ack_history = (
            acks.assign(delivery_month=pd.to_datetime(acks["delivery_date"], errors="coerce").dt.to_period("M").dt.to_timestamp())
            .groupby("delivery_month")["confirmed_qty"].sum()
            .rename("confirmed_qty")
            .reset_index()
        )
        timeline = pd.merge(forecast_history, ack_history, left_on="forecast_month", right_on="delivery_month", how="outer")
        timeline = timeline.rename(columns={"forecast_month": "month"}).drop(columns=[col for col in ["delivery_month"] if col in timeline.columns], errors="ignore")
        timeline = timeline.sort_values("month").fillna(0)
        return timeline

    def get_top_risk_products(self, top_n: int = 10) -> pd.DataFrame:
        df = self.ack_df.copy()
        if df.empty or "vendor_sku" not in df.columns:
            return pd.DataFrame()
        df["backorder_qty"] = df["ordered_qty"].fillna(0) - df["confirmed_qty"].fillna(0)
        aggregations = {
            "ordered_qty": "sum",
            "confirmed_qty": "sum",
            "backorder_qty": "sum",
        }
        if "product_description" in df.columns:
            aggregations["product_description"] = "first"
        summary = df.groupby("vendor_sku", as_index=False).agg(aggregations)
        summary["fill_rate"] = summary.apply(
            lambda row: float(row["confirmed_qty"] / row["ordered_qty"]) if row["ordered_qty"] > 0 else 0.0,
            axis=1,
        )
        summary["risk_score"] = (1.0 - summary["fill_rate"]).clip(lower=0.0)
        summary = summary.sort_values(by=["risk_score", "backorder_qty"], ascending=[False, False]).head(top_n)
        return summary

    def search_inventory_snapshot(self, query: str) -> pd.DataFrame:
        inventory = self.inventory_df
        if inventory.empty or not query:
            return inventory
        query = str(query).strip()
        mask = inventory["vendor_sku"].astype(str).str.contains(query, case=False, na=False)
        if "inventory_description" in inventory.columns:
            mask |= inventory["inventory_description"].astype(str).str.contains(query, case=False, na=False)
        return inventory[mask]

    def get_cut_supply_analysis(self, query: str | None = None) -> pd.DataFrame:
        """Compare PO shortages with the newest available SKU inventory snapshot."""
        acks = self.ack_df
        inventory = self.inventory_df
        if acks.empty or "vendor_sku" not in acks.columns:
            return pd.DataFrame()

        sku = acks["vendor_sku"].astype("string").str.strip()
        valid = sku.notna() & sku.ne("")
        po_supply = (
            acks.loc[valid, ["ordered_qty", "confirmed_qty"]]
            .assign(vendor_sku=sku.loc[valid])
            .groupby("vendor_sku", as_index=False)[["ordered_qty", "confirmed_qty"]]
            .sum()
        )
        po_supply["short_qty"] = (po_supply["ordered_qty"] - po_supply["confirmed_qty"]).clip(lower=0)
        if "vendor_sku" not in inventory.columns:
            inventory = pd.DataFrame(columns=["vendor_sku", "qty_available", "supplier_po_qty"])
        result = po_supply.merge(inventory, on="vendor_sku", how="left")
        for column in ("qty_available", "supplier_po_qty"):
            if column not in result.columns:
                result[column] = 0.0
            result[column] = result[column].fillna(0.0)
        # QtyAvailable is already the net supply position, including the
        # supplier PO quantity. Keep the latter for reference only; adding it
        # again would double-count inbound supply.
        result["supply_available"] = result["qty_available"].clip(lower=0)
        result["uncovered_short_qty"] = (result["short_qty"] - result["supply_available"]).clip(lower=0)
        result["cut_reason"] = "PO shortfall covered by available supply"
        result.loc[(result["short_qty"] > 0) & (result["supply_available"] <= 0), "cut_reason"] = "No available supply"
        result.loc[(result["short_qty"] > 0) & (result["supply_available"] > 0) & (result["uncovered_short_qty"] > 0), "cut_reason"] = "Available supply does not cover the PO shortfall"
        if query:
            query = str(query).strip()
            text_mask = result["vendor_sku"].astype(str).str.contains(query, case=False, na=False)
            if "inventory_description" in result.columns:
                text_mask |= result["inventory_description"].astype(str).str.contains(query, case=False, na=False)
            result = result[text_mask]
        return result.sort_values(["uncovered_short_qty", "short_qty"], ascending=False)

    def compute_dashboard_kpis(self) -> dict[str, float]:
        forecast = self.forecast_df
        acks = self.ack_df
        metrics: dict[str, float] = {
            "forecast_value": float(forecast["forecast_qty"].sum()) if "forecast_qty" in forecast.columns else 0.0,
            "ordered_quantity": float(acks["ordered_qty"].sum()) if "ordered_qty" in acks.columns else 0.0,
            "confirmed_quantity": float(acks["confirmed_qty"].sum()) if "confirmed_qty" in acks.columns else 0.0,
            "fill_rate": 0.0,
            "products_short": 0.0,
            "products_over_supplied": 0.0,
            "high_risk_products": 0.0,
            "high_risk_vendors": 0.0,
        }
        if metrics["ordered_quantity"] > 0:
            metrics["fill_rate"] = metrics["confirmed_quantity"] / metrics["ordered_quantity"]
        if not acks.empty and "vendor_sku" in acks.columns:
            metrics["products_short"] = count_unique_short_skus(acks)
            metrics["products_over_supplied"] = int((acks["confirmed_qty"] > acks["ordered_qty"]).sum())
        if not acks.empty and "vendor" in acks.columns:
            vendor_fill = acks.groupby("vendor").apply(lambda df: df["confirmed_qty"].sum() / df["ordered_qty"].sum() if df["ordered_qty"].sum() > 0 else 0.0)
            metrics["vendor_reliability"] = float(vendor_fill.mean()) if not vendor_fill.empty else 0.0
            metrics["high_risk_vendors"] = int((vendor_fill < 0.8).sum())
        if not forecast.empty and "forecast_qty" in forecast.columns:
            metrics["forecast_accuracy"] = float(self._calculate_mape())
            metrics["wmape"] = float(self._calculate_wmape())
        return metrics

    def _calculate_mape(self) -> float:
        df = self.forecast_vs_actual()
        if not isinstance(df, pd.DataFrame) or df.empty or "forecast_qty" not in df.columns or "actual_qty" not in df.columns:
            return 0.0
        df = df[df["forecast_qty"] > 0].copy()
        if df.empty:
            return 0.0
        return float((df["forecast_qty"] - df["actual_qty"]).abs().div(df["forecast_qty"]).mean())

    def _calculate_wmape(self) -> float:
        df = self.forecast_vs_actual()
        if not isinstance(df, pd.DataFrame) or df.empty or "forecast_qty" not in df.columns or "actual_qty" not in df.columns:
            return 0.0
        total_forecast = float(df["forecast_qty"].sum())
        if total_forecast == 0:
            return 0.0
        return float((df["forecast_qty"] - df["actual_qty"]).abs().sum() / total_forecast)

    def root_cause_analysis(
        self,
        product: str,
        vendor: Optional[str] = None,
        customer: Optional[str] = None,
        po_number: Optional[str] = None,
        lookback_months: int = 12,
        recent_weeks: int = 8,
    ) -> dict[str, object]:
        forecasts = self.forecast_df if not self.forecast_df.empty else None
        acks = self.ack_df if not self.ack_df.empty else None
        root_service = RootCauseService(forecasts, acks, self.inventory_df)
        # The root-cause service expands a PO entered in the product search to
        # the acknowledgement line SKUs before evaluating forecast history.
        return root_service.root_cause_analysis(product, vendor, customer, po_number, lookback_months, recent_weeks)

    def get_vendor_performance(self) -> pd.DataFrame:
        acks = self.ack_df
        if acks.empty or "vendor" not in acks.columns:
            return pd.DataFrame()
        vendor_report = (
            acks.groupby("vendor")[["ordered_qty", "confirmed_qty"]].sum().reset_index()
        )
        vendor_report["fill_rate"] = vendor_report.apply(
            lambda row: float(row["confirmed_qty"] / row["ordered_qty"]) if row["ordered_qty"] > 0 else 0.0,
            axis=1,
        )
        vendor_report["late_confirmations"] = 0
        vendor_report["partial_acceptance"] = vendor_report.apply(
            lambda row: float(row["confirmed_qty"] / row["ordered_qty"]) if row["ordered_qty"] > 0 else 0.0,
            axis=1,
        )
        vendor_report["reliability_score"] = vendor_report["fill_rate"]
        return vendor_report.sort_values(by="reliability_score", ascending=False)

    def investigation_workspace(self, query: str) -> dict[str, object]:
        forecast_match, ack_match = self.search_inventory(query)
        timeline = self.get_product_timeline(query)
        root_report = self.root_cause_analysis(query)
        return {
            "forecast_matches": forecast_match,
            "ack_matches": ack_match,
            "timeline": timeline,
            "root_report": root_report,
        }

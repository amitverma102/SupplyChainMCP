from __future__ import annotations
from typing import Optional, Dict, Any, List, Tuple
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from scipy import stats
from sklearn.ensemble import RandomForestClassifier

logger = logging.getLogger(__name__)


class RootCauseService:
    """Advanced root cause analysis for supply shortages.

    The service uses rule-based heuristics and optional model-based scoring
    to produce a structured analysis containing evidence, conclusions,
    confidence levels and recommended actions.
    """

    def __init__(self, forecasts: Optional[pd.DataFrame], acks: Optional[pd.DataFrame], inventory: Optional[pd.DataFrame] = None):
        # forecasts: expected columns include vendor_sku, upc, buyer_part_number,
        # forecast_month_parsed (datetime) or forecast_month, forecast_qty
        # acks: expected columns include vendor_sku, upc, buyer_part_number,
        # ordered_qty, confirmed_qty, delivery_date, po_number
        self.forecasts = forecasts if forecasts is not None else pd.DataFrame()
        self.acks = acks if acks is not None else pd.DataFrame()
        self.inventory = inventory if inventory is not None else pd.DataFrame()

    def _filter_product(self, product: str, po_number: Optional[str] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Return product records, expanding a PO number to its line-item SKUs.

        A PO number exists only in acknowledgement data.  CUT analysis accepts
        either a product identifier or a PO number, so a PO match must first
        be resolved to its acknowledgement lines and then to the matching
        forecast product identifiers.
        """
        f = self.forecasts
        a = self.acks
        if f.empty and a.empty:
            return pd.DataFrame(), pd.DataFrame()

        def match(df: pd.DataFrame) -> pd.DataFrame:
            if df.empty:
                return df
            mask = pd.Series(False, index=df.index)
            for col in ["vendor_sku", "upc", "buyer_part_number", "product_id"]:
                if col in df.columns:
                    mask = mask | (df[col].astype(str).fillna("") == str(product))
            return df[mask]

        prod_f = match(f)
        prod_a = match(a)

        po_value = str(po_number if po_number is not None else product).strip()
        if not po_value or "po_number" not in a.columns:
            return prod_f, prod_a

        po_matches = a[a["po_number"].astype("string").str.strip().eq(po_value)]
        if po_matches.empty:
            return prod_f, prod_a

        # A PO may have several lines.  Retain all of them, then fetch every
        # related forecast row using the identifiers shared by both feeds.
        prod_a = pd.concat([prod_a, po_matches]).drop_duplicates()
        related_forecast_mask = pd.Series(False, index=f.index)
        for column in ["vendor_sku", "buyer_part_number", "upc"]:
            if column not in po_matches.columns or column not in f.columns:
                continue
            identifiers = po_matches[column].astype("string").str.strip().dropna()
            identifiers = identifiers[identifiers.ne("")].unique()
            if len(identifiers):
                related_forecast_mask |= f[column].astype("string").str.strip().isin(identifiers)
        if related_forecast_mask.any():
            prod_f = pd.concat([prod_f, f[related_forecast_mask]]).drop_duplicates()

        return prod_f, prod_a

    @staticmethod
    def _confidence_summary(conclusions: List[Dict[str, Any]]) -> float:
        """Convert finding confidence labels into the report's numeric score."""
        scores = {"high": 1.0, "medium": 0.6, "low": 0.2}
        values = [scores.get(str(item.get("confidence", "")).lower(), 0.0) for item in conclusions]
        return float(np.mean(values)) if values else 0.0

    def _monthly_aggregates(self, prod_f: pd.DataFrame, prod_a: pd.DataFrame) -> pd.DataFrame:
        # create a monthly summary with forecast and actual confirmed_qty
        if prod_f.empty and prod_a.empty:
            return pd.DataFrame()

        f = prod_f.copy()
        a = prod_a.copy()

        # normalize month column names
        month_col = "forecast_month_parsed" if "forecast_month_parsed" in f.columns else (
            "forecast_month" if "forecast_month" in f.columns else None
        )

        if month_col and not f.empty:
            f["month"] = pd.to_datetime(f[month_col], errors="coerce").dt.to_period("M").dt.to_timestamp()
        else:
            f["month"] = pd.NaT

        if "delivery_date" in a.columns:
            a["month"] = pd.to_datetime(a["delivery_date"], errors="coerce").dt.to_period("M").dt.to_timestamp()
        else:
            a["month"] = pd.NaT

        fagg = f.groupby("month", dropna=True)["forecast_qty"].sum().rename("forecast_qty")
        aagg = a.groupby("month", dropna=True)["confirmed_qty"].sum().rename("confirmed_qty")

        df = pd.concat([fagg, aagg], axis=1).fillna(0)
        df["fill_rate"] = np.where(df["forecast_qty"] > 0, df["confirmed_qty"] / df["forecast_qty"], np.nan)
        df["forecast_vs_actual_ratio"] = np.where(df["forecast_qty"] > 0, df["confirmed_qty"] / df["forecast_qty"], np.nan)
        return df.sort_index()

    def _inventory_evidence(self, product: str, prod_f: pd.DataFrame, prod_a: pd.DataFrame) -> Dict[str, Any]:
        if self.inventory.empty or "vendor_sku" not in self.inventory.columns:
            return {}

        sku_values = {str(product).strip()}
        for df in (prod_f, prod_a):
            if "vendor_sku" in df.columns:
                sku_values.update(df["vendor_sku"].dropna().astype(str).str.strip())
        inventory_sku = self.inventory["vendor_sku"].astype(str).str.strip()
        matched = self.inventory[inventory_sku.isin(sku_values)].copy()
        if matched.empty:
            return {"inventory_match": False}

        available = float(pd.to_numeric(matched.get("qty_available", 0), errors="coerce").fillna(0).sum())
        supplier_po = float(pd.to_numeric(matched.get("supplier_po_qty", 0), errors="coerce").fillna(0).sum())
        po_shortfall = 0.0
        if not prod_a.empty and {"ordered_qty", "confirmed_qty"}.issubset(prod_a.columns):
            po_shortfall = float((prod_a["ordered_qty"].fillna(0) - prod_a["confirmed_qty"].fillna(0)).clip(lower=0).sum())
        return {
            "inventory_match": True,
            "qty_available": available,
            "supplier_po_qty": supplier_po,
            "po_shortfall_qty": po_shortfall,
            # QtyAvailable already includes the supplier PO quantity from the
            # inventory snapshot, so supplier_po is evidence only.
            "supply_available": max(available, 0.0),
            "uncovered_shortfall_qty": max(po_shortfall - max(available, 0.0), 0.0),
            "snapshot_date": str(matched["inventory_snapshot_date"].max()) if "inventory_snapshot_date" in matched else None,
        }

    def _detect_demand_spike(self, df_monthly: pd.DataFrame, window: int = 3, z_thresh: float = 3.0, recent_months: int = 6) -> Dict[str, Any]:
        if df_monthly.empty or df_monthly["confirmed_qty"].sum() == 0:
            return {"spike": False}

        series = df_monthly["confirmed_qty"].replace(0, np.nan).dropna()
        if len(series) < window + 1:
            return {"spike": False}

        # compute rolling z-scores across the series and detect any spikes in the recent months
        zscores = []
        for i in range(window, len(series)):
            window_slice = series.iloc[i - window:i]
            mean = window_slice.mean()
            std = window_slice.std(ddof=0)
            if pd.isna(std) or std == 0:
                z = 0.0
            else:
                z = (series.iloc[i] - mean) / std
            zscores.append((series.index[i], float(z), float(series.iloc[i]), float(mean)))

        # consider only recent_months
        cutoff_idx = max(0, len(zscores) - recent_months)
        recent = zscores[cutoff_idx:]
        spikes = [z for z in recent if z[1] >= z_thresh]
        if not spikes:
            return {"spike": False}

        # return top spike
        top = max(spikes, key=lambda x: x[1])
        return {"spike": True, "z_score": top[1], "date": str(top[0]), "recent": top[2], "window_mean": top[3]}

    def _detect_product_cut(self, df_monthly: pd.DataFrame, drop_pct: float = 0.8) -> Dict[str, Any]:
        # detect sudden drops in forecast or orders
        if df_monthly.empty:
            return {"cut": False}
        f = df_monthly["forecast_qty"].replace(0, np.nan).dropna()
        a = df_monthly["confirmed_qty"].replace(0, np.nan).dropna()
        result = {"cut": False}
        if len(f) >= 2:
            if f.iloc[-1] <= f.iloc[-2] * (1 - drop_pct):
                result["cut"] = True
                result["type"] = "forecast_drop"
                result["drop_pct"] = float(1 - (f.iloc[-1] / f.iloc[-2]))
                return result
        if len(a) >= 2:
            if a.iloc[-1] <= a.iloc[-2] * (1 - drop_pct):
                result["cut"] = True
                result["type"] = "orders_drop"
                result["drop_pct"] = float(1 - (a.iloc[-1] / a.iloc[-2]))
                return result
        return result

    def _vendor_performance_trend(self, df_monthly: pd.DataFrame, months: int = 6) -> Dict[str, Any]:
        # evaluate if fill rate is deteriorating using slope and recent vs historical averages
        res = {"deteriorating": False}
        if df_monthly.empty:
            return res
        recent = df_monthly["fill_rate"].dropna()
        if len(recent) < 3:
            return res

        # slope of recent months
        y = recent.values[-months:]
        if len(y) < 3:
            return res
        x = np.arange(len(y))
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
        res["slope"] = float(slope)
        res["r_value"] = float(r_value)
        res["p_value"] = float(p_value)

        # compare recent average to earlier average
        n_recent = min(len(recent), months)
        recent_avg = float(recent.values[-n_recent:].mean())
        earlier = recent.values[:-n_recent]
        earlier_avg = float(earlier.mean()) if len(earlier) > 0 else recent_avg
        res["recent_avg"] = recent_avg
        res["earlier_avg"] = earlier_avg
        # deterioration if slope is negative and recent avg significantly lower than earlier
        res["deteriorating"] = (slope < -0.01) or (earlier_avg > 0 and (earlier_avg - recent_avg) / max(earlier_avg, 1e-9) > 0.05)
        return res

    def _classify(self, df_monthly: pd.DataFrame, spike_info: Dict[str, Any], cut_info: Dict[str, Any], vendor_trend: Dict[str, Any], inventory_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        conclusions: List[Dict[str, Any]] = []

        # Demand exceeded forecast
        if not df_monthly.empty:
            avg_forecast = df_monthly["forecast_qty"].mean()
            avg_actual = df_monthly["confirmed_qty"].mean()
            if avg_actual > avg_forecast * 1.2:
                conclusions.append({"cause": "demand_exceeded_forecast", "confidence": "high", "evidence": {"avg_forecast": float(avg_forecast), "avg_actual": float(avg_actual)}})
            elif avg_actual > avg_forecast * 1.05:
                conclusions.append({"cause": "demand_exceeded_forecast", "confidence": "medium", "evidence": {"avg_forecast": float(avg_forecast), "avg_actual": float(avg_actual)}})

        # Demand spike
        if spike_info.get("spike"):
            conclusions.append({"cause": "demand_spike", "confidence": "high", "evidence": spike_info})

        # Product cut
        if cut_info.get("cut"):
            conclusions.append({"cause": "product_cut", "confidence": "high", "evidence": cut_info})

        # Vendor issues
        if vendor_trend.get("deteriorating"):
            conclusions.append({"cause": "vendor_under_supply", "confidence": "high" if vendor_trend.get("slope", 0) < -0.05 else "medium", "evidence": vendor_trend})

        if inventory_info.get("inventory_match"):
            if inventory_info["po_shortfall_qty"] > 0 and inventory_info["supply_available"] <= 0:
                conclusions.append({"cause": "available_supply_depleted", "confidence": "high", "evidence": inventory_info})
            elif inventory_info["uncovered_shortfall_qty"] > 0:
                conclusions.append({"cause": "inventory_insufficient_for_po_shortfall", "confidence": "high", "evidence": inventory_info})

        # forecast missing
        if df_monthly["forecast_qty"].sum() == 0 and df_monthly["confirmed_qty"].sum() > 0:
            conclusions.append({"cause": "forecast_missing", "confidence": "high"})

        if not conclusions:
            conclusions.append({"cause": "unknown", "confidence": "low"})

        return conclusions

    def root_cause_analysis(self, product: str, vendor: Optional[str] = None, customer: Optional[str] = None, po_number: Optional[str] = None, lookback_months: int = 12, recent_weeks: int = 8) -> Dict[str, Any]:
        """Run a structured root cause analysis for `product`.

        Returns a dictionary containing:
        - product: queried product identifier
        - summary: top-level metrics
        - evidence: list of computed metrics and small samples
        - conclusions: list of possible causes with confidence and evidence
        - recommendations: suggested actions
        """
        report: Dict[str, Any] = {"product": product, "summary": {}, "evidence": [], "conclusions": [], "recommendations": []}

        try:
            prod_f, prod_a = self._filter_product(product, po_number)
            if prod_f.empty and prod_a.empty:
                report["conclusions"].append({"cause": "no_data", "confidence": "high"})
                report["confidence"] = self._confidence_summary(report["conclusions"])
                return report

            df_monthly = self._monthly_aggregates(prod_f, prod_a)

            # limit lookback
            if not df_monthly.empty and lookback_months is not None:
                cutoff = (datetime.now() - pd.DateOffset(months=lookback_months)).to_period("M").to_timestamp()
                df_monthly = df_monthly[df_monthly.index >= cutoff]

            # compute key metrics
            total_forecast = float(df_monthly["forecast_qty"].sum()) if not df_monthly.empty else 0.0
            total_confirmed = float(df_monthly["confirmed_qty"].sum()) if not df_monthly.empty else 0.0
            overall_fill_rate = float(total_confirmed / total_forecast) if total_forecast > 0 else float("nan")
            report["summary"] = {"total_forecast": total_forecast, "total_confirmed": total_confirmed, "overall_fill_rate": overall_fill_rate}

            report["evidence"].append({"monthly_sample": df_monthly.tail(6).reset_index().to_dict(orient="records")})
            inventory_info = self._inventory_evidence(product, prod_f, prod_a)
            if inventory_info:
                report["summary"].update({key: value for key, value in inventory_info.items() if key != "inventory_match"})
                report["evidence"].append({"inventory_supply": inventory_info})

            spike_info = self._detect_demand_spike(df_monthly)
            cut_info = self._detect_product_cut(df_monthly)
            vendor_trend = self._vendor_performance_trend(df_monthly)

            conclusions = self._classify(df_monthly, spike_info, cut_info, vendor_trend, inventory_info)
            report["conclusions"] = conclusions

            # produce recommendations based on conclusions
            recs: List[str] = []
            for c in conclusions:
                cause = c.get("cause")
                if cause == "demand_exceeded_forecast":
                    recs.append("Increase safety stock and engage demand planning to review forecast inputs.")
                if cause == "demand_spike":
                    recs.append("Investigate promotion/events and communicate temporary allocation to vendors.")
                if cause == "product_cut":
                    recs.append("Confirm with merchandising if product was intentionally cut; if not, restore forecast or adjust ordering.")
                if cause == "vendor_under_supply":
                    recs.append("Open vendor performance case and consider alternative suppliers or expedite shipments.")
                if cause == "forecast_missing":
                    recs.append("Reinstate forecast or adjust systems that generate forecasts; contact forecasting team.")
                if cause == "available_supply_depleted":
                    recs.append("Expedite replenishment or transfer stock: the available supply position does not cover the PO shortfall.")
                if cause == "inventory_insufficient_for_po_shortfall":
                    recs.append("Allocate available stock and expedite replenishment; the remaining demand is not covered by the available supply position.")
            report["recommendations"] = recs

            # include confidence summary
            report["confidence"] = self._confidence_summary(conclusions)

            # attach small supporting sample of ack lines (latest 10)
            if not prod_a.empty:
                report["supporting_ack_samples"] = prod_a.sort_values(by="delivery_date", ascending=False).head(10).to_dict(orient="records")

        except Exception as exc:
            logger.exception("root cause analysis error: %s", exc)
            report["conclusions"].append({"cause": "analysis_error", "confidence": "low", "error": str(exc)})
            report["confidence"] = self._confidence_summary(report["conclusions"])

        return report


__all__ = ["RootCauseService"]

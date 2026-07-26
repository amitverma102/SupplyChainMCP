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

    def __init__(self, forecasts: Optional[pd.DataFrame], acks: Optional[pd.DataFrame], inventory: Optional[pd.DataFrame] = None, supplier_pos: Optional[pd.DataFrame] = None):
        # forecasts: expected columns include vendor_sku, upc, buyer_part_number,
        # forecast_month_parsed (datetime) or forecast_month, forecast_qty
        # acks: expected columns include vendor_sku, upc, buyer_part_number,
        # ordered_qty, confirmed_qty, delivery_date, po_number
        self.forecasts = forecasts if forecasts is not None else pd.DataFrame()
        self.acks = acks if acks is not None else pd.DataFrame()
        self.inventory = inventory if inventory is not None else pd.DataFrame()
        self.supplier_pos = supplier_pos if supplier_pos is not None else pd.DataFrame()

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

    def _supplier_po_evidence(self, product: str, prod_f: pd.DataFrame, prod_a: pd.DataFrame) -> Dict[str, Any]:
        """Summarize supplier PO exceptions for the SKU(s) under analysis."""
        if self.supplier_pos.empty or "vendor_sku" not in self.supplier_pos.columns:
            return {}
        skus = {str(product).strip()}
        for frame in (prod_f, prod_a):
            if "vendor_sku" in frame.columns:
                skus.update(frame["vendor_sku"].dropna().astype(str).str.strip())
        matches = self.supplier_pos[self.supplier_pos["vendor_sku"].astype(str).str.strip().isin(skus)].copy()
        if matches.empty:
            return {"supplier_po_match": False}

        # Supplier receipts count only if they were received on or before the
        # relevant acknowledgement date for that SKU.  This prevents later
        # supplier receipts from masking the cause of an earlier shortfall.
        matches["supplier_received_qty_as_of_ack"] = 0.0
        if {"vendor_sku", "delivery_date"}.issubset(prod_a.columns):
            ack_dates = prod_a.copy()
            ack_dates["acknowledgement_date"] = pd.to_datetime(ack_dates["delivery_date"], errors="coerce")
            cutoffs = ack_dates.groupby(ack_dates["vendor_sku"].astype("string").str.strip())["acknowledgement_date"].max()
            matches["acknowledgement_date"] = matches["vendor_sku"].astype("string").str.strip().map(cutoffs)
            received_date = pd.to_datetime(matches.get("actual_receipt_date"), errors="coerce")
            eligible = received_date.notna() & matches["acknowledgement_date"].notna() & received_date.le(matches["acknowledgement_date"])
            matches.loc[eligible, "supplier_received_qty_as_of_ack"] = pd.to_numeric(
                matches.loc[eligible, "supplier_received_qty"], errors="coerce"
            ).fillna(0.0)

        numeric_columns = ["supplier_forecast_qty", "supplier_ordered_qty", "supplier_confirmed_qty", "supplier_received_qty", "damaged_qty", "incorrect_qty"]
        totals = {
            column: float(pd.to_numeric(matches[column] if column in matches.columns else pd.Series(0, index=matches.index), errors="coerce").fillna(0).sum())
            for column in numeric_columns
        }
        totals["supplier_received_qty"] = float(matches["supplier_received_qty_as_of_ack"].sum())
        issue_types = matches.get("supplier_issue_type", pd.Series(dtype="string")).fillna("NONE").astype(str).str.upper()
        causes: set[str] = set()
        if issue_types.isin(["SUPPLIER_DELAYED_SHIPPING", "ORDER_DELAYED_IN_TRANSIT", "MULTIPLE_SUPPLY_CHAIN_ISSUES"]).any() or (
            pd.to_datetime(matches.get("actual_receipt_date"), errors="coerce") > pd.to_datetime(matches.get("expected_receipt_date"), errors="coerce")
        ).fillna(False).any():
            causes.add("supplier_delivery_delay")
        if issue_types.isin(["SUPPLIER_PARTIAL_CONFIRMATION", "MULTIPLE_SUPPLY_CHAIN_ISSUES"]).any() or totals["supplier_confirmed_qty"] < totals["supplier_ordered_qty"]:
            causes.add("supplier_under_supply")
        if issue_types.isin(["PARTIALLY_DAMAGED_SHIPMENT", "MULTIPLE_SUPPLY_CHAIN_ISSUES"]).any() or totals["damaged_qty"] > 0:
            causes.add("damaged_supplier_shipment")
        if issue_types.eq("INCORRECT_SKU_RECEIVED").any() or totals["incorrect_qty"] > 0:
            causes.add("incorrect_supplier_shipment")
        if issue_types.isin(["INSUFFICIENT_ORDER_QUANTITY", "VENDOR_ORDER_PLACED_LATE", "MULTIPLE_SUPPLY_CHAIN_ISSUES"]).any() or totals["supplier_ordered_qty"] < totals["supplier_forecast_qty"]:
            causes.add("buyer_supplier_order_issue")
        return {
            "supplier_po_match": True,
            "supplier_po_count": int(len(matches)),
            "supplier_causes": sorted(causes),
            "supplier_issue_types": sorted(issue_types.unique().tolist()),
            "supplier_receipt_cutoff_dates": sorted(matches["acknowledgement_date"].dropna().dt.strftime("%Y-%m-%d").unique().tolist()) if "acknowledgement_date" in matches else [],
            **totals,
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

    def _forecast_po_check(self, df_monthly: pd.DataFrame, prod_a: pd.DataFrame) -> Dict[str, Any]:
        """Apply the CUT forecast checks against the purchase-order quantity.

        Confirmed acknowledgement quantity is the available shipment measure.
        The PO coverage comparison uses only forecast in the PO delivery
        month(s).  When that forecast is below the PO, the shipment comparison
        uses the three calendar months ending in the latest PO delivery month;
        future forecast months are never included.
        """
        if df_monthly.empty or "ordered_qty" not in prod_a.columns or "delivery_date" not in prod_a.columns:
            return {"available": False}

        purchase_order_qty = float(pd.to_numeric(prod_a["ordered_qty"], errors="coerce").fillna(0).sum())
        po_months = (
            pd.to_datetime(prod_a["delivery_date"], errors="coerce")
            .dropna()
            .dt.to_period("M")
            .dt.to_timestamp()
            .unique()
        )
        if purchase_order_qty <= 0 or not len(po_months):
            return {"available": False, "purchase_order_qty": purchase_order_qty}

        po_month_index = pd.DatetimeIndex(po_months).sort_values()
        forecast_for_po_month = float(df_monthly.reindex(po_month_index, fill_value=0)["forecast_qty"].sum())
        evidence = {
            "purchase_order_qty": purchase_order_qty,
            "forecast_for_purchase_order_month": forecast_for_po_month,
            "purchase_order_months": [str(month.date()) for month in po_month_index],
        }
        if forecast_for_po_month >= purchase_order_qty:
            return {"available": True, "result": "no_forecast_issue", "rule": "forecast_meets_or_exceeds_purchase_order", **evidence}

        window_end = po_month_index.max()
        window_start = window_end - pd.DateOffset(months=2)
        recent = df_monthly.loc[window_start:window_end]
        last_three_shipments = float(recent["confirmed_qty"].sum())
        last_three_forecast = float(recent["forecast_qty"].sum())
        evidence.update(
            {
                "last_three_month_shipments": last_three_shipments,
                "last_three_month_forecast": last_three_forecast,
                "months_compared": int(len(recent)),
            }
        )
        # Forecast below the PO is always a coverage gap.  The shipment check
        # distinguishes a demonstrated historic under-forecast from a gap
        # whose shipment history has not yet exceeded forecast.
        result = "under_forecasting" if last_three_shipments > last_three_forecast else "forecast_below_purchase_order"
        rule = "shipments_exceed_forecast" if result == "under_forecasting" else "purchase_order_exceeds_month_forecast"
        return {"available": True, "result": result, "rule": rule, **evidence}

    def _classify(self, df_monthly: pd.DataFrame, spike_info: Dict[str, Any], cut_info: Dict[str, Any], vendor_trend: Dict[str, Any], inventory_info: Dict[str, Any], forecast_check: Dict[str, Any], supplier_po_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        conclusions: List[Dict[str, Any]] = []

        # CUT forecast checks: PO coverage first, then recent shipments versus forecast.
        if forecast_check.get("available"):
            conclusions.append(
                {
                    "cause": forecast_check["result"],
                    "confidence": "high",
                    "evidence": forecast_check,
                }
            )

        # Supplier PO data identifies whether the shortage originated with
        # supplier execution or the buyer's supplier-order decision.
        for cause in supplier_po_info.get("supplier_causes", []):
            conclusions.append({"cause": cause, "confidence": "high", "evidence": supplier_po_info})

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
            forecast_check = self._forecast_po_check(df_monthly, prod_a)
            if forecast_check.get("available"):
                report["summary"]["purchase_order_qty"] = forecast_check["purchase_order_qty"]
                report["summary"]["forecast_for_purchase_order_month"] = forecast_check["forecast_for_purchase_order_month"]
                report["evidence"].append({"forecast_purchase_order_check": forecast_check})
            inventory_info = self._inventory_evidence(product, prod_f, prod_a)
            if inventory_info:
                report["summary"].update({key: value for key, value in inventory_info.items() if key != "inventory_match"})
                report["evidence"].append({"inventory_supply": inventory_info})

            supplier_po_info = self._supplier_po_evidence(product, prod_f, prod_a)
            if supplier_po_info:
                report["summary"].update(
                    {
                        key: value
                        for key, value in supplier_po_info.items()
                        if key in {"supplier_po_count", "supplier_ordered_qty", "supplier_confirmed_qty", "supplier_received_qty", "damaged_qty", "incorrect_qty"}
                    }
                )
                report["evidence"].append({"supplier_purchase_orders": supplier_po_info})

            spike_info = self._detect_demand_spike(df_monthly)
            cut_info = self._detect_product_cut(df_monthly)
            vendor_trend = self._vendor_performance_trend(df_monthly)

            conclusions = self._classify(df_monthly, spike_info, cut_info, vendor_trend, inventory_info, forecast_check, supplier_po_info)
            report["conclusions"] = conclusions

            # produce recommendations based on conclusions
            recs: List[str] = []
            for c in conclusions:
                cause = c.get("cause")
                if cause == "demand_exceeded_forecast":
                    recs.append("Increase safety stock and engage demand planning to review forecast inputs.")
                if cause == "under_forecasting":
                    recs.append("Increase the forecast: recent shipments exceeded the last three months of forecast.")
                if cause == "forecast_below_purchase_order":
                    recs.append("Review the forecast: the purchase order exceeds forecast for its delivery month.")
                if cause == "supplier_delivery_delay":
                    recs.append("Escalate supplier delivery delay and recover the delayed receipt date.")
                if cause == "supplier_under_supply":
                    recs.append("Escalate the supplier confirmation shortfall and secure replacement supply.")
                if cause == "damaged_supplier_shipment":
                    recs.append("Raise a supplier damage claim and expedite replacement quantity.")
                if cause == "incorrect_supplier_shipment":
                    recs.append("Correct the supplier shipment discrepancy and arrange return/replacement of the wrong item.")
                if cause == "buyer_supplier_order_issue":
                    recs.append("Review supplier PO timing and quantity; the supplier order was late or below the supplier forecast.")
                if cause == "demand_spike":
                    recs.append("Investigate promotion/events and communicate temporary allocation to vendors.")
                if cause == "product_cut":
                    recs.append("Confirm with merchandising if product was intentionally cut; if not, restore forecast or adjust ordering.")
                if cause == "vendor_under_supply":
                    recs.append("Open vendor performance case and consider alternative suppliers or expedite shipments.")
                if cause == "forecast_missing":
                    recs.append("Reinstate forecast or adjust systems that generate forecasts; contact forecasting team.")
                if cause == "available_supply_depleted":
                    recs.append("Expedite replenishment or transfer stock: the available supply position does not cover the purchase order.")
                if cause == "inventory_insufficient_for_po_shortfall":
                    recs.append("Allocate available stock and expedite replenishment; the remaining purchase-order demand is not covered by the available supply position.")
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

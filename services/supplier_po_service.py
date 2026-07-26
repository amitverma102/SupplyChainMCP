from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class SupplierPOService:
    """Load supplier-facing purchase orders from JSON files into one schema."""

    COLUMNS = [
        "supplier_po_number", "vendor_sku", "supplier_forecast_qty", "supplier_ordered_qty",
        "supplier_confirmed_qty", "supplier_received_qty", "damaged_qty", "incorrect_sku_received",
        "incorrect_qty", "supplier_po_date", "expected_receipt_date", "actual_receipt_date",
        "supplier_issue_type", "supplier_status", "source_file",
    ]

    def __init__(self, supplier_pos_dir: str | Path):
        self.supplier_pos_dir = Path(supplier_pos_dir)

    def discover_files(self) -> list[Path]:
        return sorted(self.supplier_pos_dir.rglob("*.json"))

    def load_all(self) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for path in self.discover_files():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.exception("Failed to read supplier PO file: %s", path)
                continue
            orders = raw.get("purchaseOrders", []) if isinstance(raw, dict) else raw
            if not isinstance(orders, list):
                logger.warning("Supplier PO file has no purchaseOrders list: %s", path)
                continue
            for order in orders:
                if not isinstance(order, dict):
                    continue
                rows.append(
                    {
                        "supplier_po_number": order.get("poNumber"),
                        "vendor_sku": order.get("sku"),
                        "supplier_forecast_qty": order.get("forecastQty", 0),
                        "supplier_ordered_qty": order.get("orderedQty", 0),
                        "supplier_confirmed_qty": order.get("supplierConfirmedQty", 0),
                        "supplier_received_qty": order.get("receivedQty", 0),
                        "damaged_qty": order.get("damagedQty", 0),
                        "incorrect_sku_received": order.get("incorrectSkuReceived"),
                        "incorrect_qty": order.get("incorrectQty", 0),
                        "supplier_po_date": order.get("poDate"),
                        "expected_receipt_date": order.get("expectedReceiptDate"),
                        "actual_receipt_date": order.get("actualReceiptDate"),
                        "supplier_issue_type": order.get("issueType", "NONE"),
                        "supplier_status": order.get("status"),
                        "source_file": path.name,
                    }
                )
        if not rows:
            return pd.DataFrame(columns=self.COLUMNS)
        data = pd.DataFrame(rows, columns=self.COLUMNS)
        for column in ["supplier_forecast_qty", "supplier_ordered_qty", "supplier_confirmed_qty", "supplier_received_qty", "damaged_qty", "incorrect_qty"]:
            data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)
        for column in ["supplier_po_date", "expected_receipt_date", "actual_receipt_date"]:
            data[column] = pd.to_datetime(data[column], errors="coerce")
        data["vendor_sku"] = data["vendor_sku"].astype("string").str.strip()
        return data[data["vendor_sku"].notna() & data["vendor_sku"].ne("")].reset_index(drop=True)


__all__ = ["SupplierPOService"]

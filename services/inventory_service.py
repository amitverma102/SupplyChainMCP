from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd


class InventoryService:
    """Load the newest SKU-level inventory snapshot from the Inventory folder."""

    SKU_COLUMN = "Item__No__"
    SUPPLIER_PO_COLUMN = "Item__Qty__on_Purch__Order_"
    AVAILABLE_COLUMN = "QtyAvailable"
    DESCRIPTION_COLUMN = "Item_Item_Description"

    def __init__(self, inventory_dir: str | Path):
        self.inventory_dir = Path(inventory_dir)

    @staticmethod
    def _snapshot_date(path: Path) -> pd.Timestamp:
        match = re.search(r"(\d{1,2}[A-Za-z]{3,9}\d{4})", path.stem)
        if match:
            parsed = pd.to_datetime(match.group(1), format="%d%B%Y", errors="coerce")
            if pd.notna(parsed):
                return parsed.normalize()
            parsed = pd.to_datetime(match.group(1), format="%d%b%Y", errors="coerce")
            if pd.notna(parsed):
                return parsed.normalize()
        return pd.Timestamp(datetime.fromtimestamp(path.stat().st_mtime)).normalize()

    @staticmethod
    def _quantity(values: pd.Series) -> pd.Series:
        cleaned = values.astype("string").str.replace(r"[^0-9.\-]", "", regex=True)
        return pd.to_numeric(cleaned, errors="coerce").fillna(0.0)

    def discover_files(self) -> list[Path]:
        files = [*self.inventory_dir.glob("*.csv"), *self.inventory_dir.glob("*.xlsx"), *self.inventory_dir.glob("*.xls")]
        return sorted(files, key=self._snapshot_date)

    def load_latest(self) -> pd.DataFrame:
        files = self.discover_files()
        if not files:
            return pd.DataFrame(columns=["vendor_sku", "qty_available", "supplier_po_qty", "inventory_snapshot_date"])

        path = files[-1]
        if path.suffix.lower() == ".csv":
            raw = None
            for encoding in ("utf-8-sig", "cp1252", "latin-1"):
                try:
                    raw = pd.read_csv(path, encoding=encoding, dtype={self.SKU_COLUMN: "string"})
                    break
                except UnicodeDecodeError:
                    continue
            if raw is None:
                return pd.DataFrame()
        else:
            raw = pd.read_excel(path, dtype={self.SKU_COLUMN: "string"})

        required = {self.SKU_COLUMN, self.SUPPLIER_PO_COLUMN, self.AVAILABLE_COLUMN}
        if not required.issubset(raw.columns):
            return pd.DataFrame()

        inventory = pd.DataFrame(
            {
                "vendor_sku": raw[self.SKU_COLUMN].astype("string").str.strip(),
                "qty_available": self._quantity(raw[self.AVAILABLE_COLUMN]),
                "supplier_po_qty": self._quantity(raw[self.SUPPLIER_PO_COLUMN]),
                "inventory_snapshot_date": self._snapshot_date(path),
                "inventory_source_file": path.name,
            }
        )
        if self.DESCRIPTION_COLUMN in raw.columns:
            inventory["inventory_description"] = raw[self.DESCRIPTION_COLUMN].astype("string").str.strip()
        inventory = inventory[inventory["vendor_sku"].notna() & inventory["vendor_sku"].ne("")]
        aggregations = {"qty_available": "sum", "supplier_po_qty": "sum", "inventory_snapshot_date": "max", "inventory_source_file": "first"}
        if "inventory_description" in inventory.columns:
            aggregations["inventory_description"] = "first"
        return inventory.groupby("vendor_sku", as_index=False).agg(aggregations)


__all__ = ["InventoryService"]

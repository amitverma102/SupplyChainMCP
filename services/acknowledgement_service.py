from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Iterable, Optional
import pandas as pd
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class AckLineModel(BaseModel):
    """Pydantic model for a single acknowledgement line item."""
    po_number: str
    vendor_sku: Optional[str] = None
    buyer_part_number: Optional[str] = None
    upc: Optional[str] = None
    description: Optional[str] = None
    product_description: Optional[str] = None
    # Raw EDI quantities are expressed in cases.  The normalized quantities
    # below are units, matching the forecast workbook's unit of measure.
    ordered_cases: float = 0.0
    confirmed_cases: float = 0.0
    pack_value: float = 1.0
    ordered_qty: float = 0.0
    confirmed_qty: float = 0.0
    price: Optional[float] = None
    status_code: Optional[str] = None
    delivery_date: Optional[str] = None

    @field_validator("ordered_cases", "confirmed_cases", "pack_value", "ordered_qty", "confirmed_qty", mode="before")
    @classmethod
    def coerce_qty(cls, v):
        if v is None:
            return 0.0
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0


class AcknowledgementService:
    """Parse EDI855 acknowledgement JSON files with incremental loading and validation."""

    def __init__(self, ack_dir: str | Path, cache_service: Optional[object] = None):
        self.ack_dir = Path(ack_dir)
        self.cache = cache_service

    def discover_files(self) -> list[Path]:
        files = list(self.ack_dir.rglob("*.json"))
        logger.info("Discovered %d acknowledgement files", len(files))
        return files

    def parse_file(self, path: Path) -> pd.DataFrame:
        # incremental skip
        try:
            mtime = path.stat().st_mtime
        except OSError:
            logger.exception("Cannot stat file: %s", path)
            return pd.DataFrame()

        cached = None
        if self.cache:
            cached = self.cache.get(str(path))
            if cached and cached.get("mtime") == mtime:
                logger.debug("Skipping unchanged acknowledgement file %s", path)
                return pd.DataFrame()

        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            logger.exception("Failed to read JSON file: %s", path)
            return pd.DataFrame()

        # Best-effort mapping; EDI->JSON formats vary
        header = raw.get("Header", {}) if isinstance(raw, dict) else {}
        order_header = header.get("OrderHeader")
        vendor = order_header.get("Vendor") or raw.get("vendor")
        customer = order_header.get("Customer") or raw.get("customer")
        po_number = order_header.get("PurchaseOrderNumber") or raw.get("poNumber") or raw.get("po")

        lines = raw.get("LineItem") or raw.get("line_items") or []
        rows = []
        for idx, line in enumerate(lines):
            l = line.get("OrderLine") or {}
            ackLine = line.get("LineItemAcknowledgement") or [{}]
            descLine = line.get("ProductOrItemDescription") or [{}]
            physical_details = line.get("PhysicalDetails") or [{}]

            ordered_cases = _as_float(l.get("OrderQty") or l.get("orderedQty") or l.get("ordered"))
            confirmed_cases = _as_float(ackLine[0].get("ItemScheduleQty") or ackLine[0].get("confirmedQty"))
            pack_value = _as_float(physical_details[0].get("PackValue"), default=1.0)
            if pack_value <= 0:
                logger.warning("Invalid PackValue %r in %s; using 1 unit per case", pack_value, path)
                pack_value = 1.0
            # normalize field names
            line_data = {
                "po_number": po_number,
                "vendor_sku": l.get("VendorPartNumber") or l.get("vendorSku") or l.get("seller_item_id"),
                "buyer_part_number": l.get("BuyerPartNumber") or l.get("buyerPartNumber"),
                "description": descLine[0].get("ProductDescription"),
                "product_description": descLine[0].get("ProductDescription"),
                "ordered_cases": ordered_cases,
                "confirmed_cases": confirmed_cases,
                "pack_value": pack_value,
                "ordered_qty": ordered_cases * pack_value,
                "confirmed_qty": confirmed_cases * pack_value,
                "delivery_date": ackLine[0].get("ItemScheduleDate"),               
                "price": l.get("PurchasePrice"),                
            }
            # validate line with Pydantic
            try:
                validated = AckLineModel(**line_data)
                row = validated.model_dump()
                row["source_file"] = str(path)
                row["vendor"] = vendor
                row["customer"] = customer
                rows.append(row)
            except Exception:
                logger.warning("Skipped invalid ack line in %s: %s", path, line_data)

        df = pd.DataFrame(rows)
        if self.cache:
            self.cache.set(str(path), mtime, {"rows": len(rows)})
        return df

    def load_all(self) -> pd.DataFrame:
        parts = []
        for p in self.discover_files():
            try:
                df = self.parse_file(p)
                if df.empty:
                    continue
                parts.append(df)
            except Exception:
                logger.exception("Failed to parse acknowledgement: %s", p)
        if not parts:
            return pd.DataFrame()
        return pd.concat(parts, ignore_index=True)


__all__ = ["AcknowledgementService"]

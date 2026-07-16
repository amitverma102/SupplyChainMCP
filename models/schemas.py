from __future__ import annotations
from pydantic import BaseModel, Field, conint, confloat
from datetime import date, datetime
from typing import Optional, List


class Product(BaseModel):
    product_id: Optional[str]
    vendor_sku: Optional[str]
    buyer_part_number: Optional[str]
    upc: Optional[str]
    gtin: Optional[str]
    description: Optional[str]
    brand: Optional[str]
    department: Optional[str]


class Vendor(BaseModel):
    vendor_id: Optional[str]
    name: Optional[str]


class Customer(BaseModel):
    customer_id: Optional[str]
    name: Optional[str]


class ForecastRecord(BaseModel):
    record_id: Optional[str]
    product: Product
    customer: Customer
    vendor: Vendor
    forecast_month: date
    forecast_qty: confloat(ge=0)
    report_date: Optional[date]


class AcknowledgementLine(BaseModel):
    line_id: Optional[str]
    po_number: str
    vendor_sku: Optional[str]
    buyer_part_number: Optional[str]
    upc: Optional[str]
    description: Optional[str]
    ordered_qty: confloat(ge=0)
    confirmed_qty: confloat(ge=0)
    price: Optional[float]
    status_code: Optional[str]
    delivery_date: Optional[date]


class Acknowledgement(BaseModel):
    ack_id: Optional[str]
    vendor: Vendor
    customer: Customer
    po_number: str
    po_date: Optional[date]
    ack_date: Optional[date]
    currency: Optional[str]
    trading_partner: Optional[str]
    lines: List[AcknowledgementLine]


class PurchaseOrder(BaseModel):
    po_number: str
    vendor: Vendor
    customer: Customer
    po_date: Optional[date]
    lines: List[AcknowledgementLine]


class Metric(BaseModel):
    name: str
    value: float
    details: Optional[dict]


__all__ = [
    "Product",
    "Vendor",
    "Customer",
    "ForecastRecord",
    "Acknowledgement",
    "AcknowledgementLine",
    "PurchaseOrder",
    "Metric",
]

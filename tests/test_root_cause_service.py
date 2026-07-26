import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from services.root_cause_service import RootCauseService


def _make_test_data():
    # create 8 months of data with a demand spike and declining fill rate
    months = pd.date_range(end=pd.Timestamp.today(), periods=8, freq="MS")
    f_rows = []
    a_rows = []
    for i, m in enumerate(months):
        forecast = 100 + (i * 5)
        confirmed = forecast if i < 5 else int(forecast * 0.6)  # drop in later months
        if i == 6:
            confirmed = forecast * 2  # demand spike
        f_rows.append({"vendor_sku": "TEST-1", "forecast_month_parsed": m, "forecast_qty": forecast})
        a_rows.append({"vendor_sku": "TEST-1", "delivery_date": m + pd.Timedelta(days=10), "confirmed_qty": confirmed, "ordered_qty": forecast})

    f_df = pd.DataFrame(f_rows)
    a_df = pd.DataFrame(a_rows)
    return f_df, a_df


def test_root_cause_detects_spike_and_vendor_decline():
    f_df, a_df = _make_test_data()
    svc = RootCauseService(f_df, a_df)
    report = svc.root_cause_analysis("TEST-1", lookback_months=8)
    assert "conclusions" in report
    causes = [c["cause"] for c in report["conclusions"]]
    assert "demand_spike" in causes or "vendor_under_supply" in causes


def test_root_cause_resolves_a_po_to_its_acknowledgement_skus():
    forecasts = pd.DataFrame(
        {
            "vendor_sku": ["SKU-1", "SKU-1", "SKU-2"],
            "forecast_month_parsed": pd.to_datetime(["2026-06-01", "2026-07-01", "2026-06-01"]),
            "forecast_qty": [10, 12, 20],
        }
    )
    acknowledgements = pd.DataFrame(
        {
            "po_number": ["PO-100", "PO-100"],
            "vendor_sku": ["SKU-1", "SKU-2"],
            "delivery_date": ["2026-06-10", "2026-06-15"],
            "ordered_qty": [10, 20],
            "confirmed_qty": [8, 20],
        }
    )

    report = RootCauseService(forecasts, acknowledgements).root_cause_analysis(
        "PO-100", lookback_months=None
    )

    assert report["summary"]["total_forecast"] == 42.0
    assert report["summary"]["total_confirmed"] == 28.0
    assert all(finding["cause"] != "no_data" for finding in report["conclusions"])
    assert report["confidence"] > 0


def test_root_cause_no_data_report_has_numeric_confidence():
    report = RootCauseService(pd.DataFrame(), pd.DataFrame()).root_cause_analysis("missing")

    assert report["conclusions"] == [{"cause": "no_data", "confidence": "high"}]
    assert report["confidence"] == 1.0


def test_forecast_check_reports_no_issue_when_forecast_meets_purchase_order():
    forecasts = pd.DataFrame(
        {
            "vendor_sku": ["SKU-1"] * 3,
            "forecast_month_parsed": pd.to_datetime(["2026-04-01", "2026-05-01", "2026-06-01"]),
            "forecast_qty": [40, 40, 40],
        }
    )
    acknowledgements = pd.DataFrame(
        {
            "po_number": ["PO-100"],
            "vendor_sku": ["SKU-1"],
            "delivery_date": ["2026-06-10"],
            "ordered_qty": [30],
            "confirmed_qty": [30],
        }
    )

    report = RootCauseService(forecasts, acknowledgements).root_cause_analysis("PO-100", lookback_months=None)

    assert "no_forecast_issue" in [finding["cause"] for finding in report["conclusions"]]


def test_forecast_check_reports_under_forecasting_when_recent_shipments_exceed_forecast():
    forecasts = pd.DataFrame(
        {
            "vendor_sku": ["SKU-1"] * 4,
            "forecast_month_parsed": pd.to_datetime(["2026-04-01", "2026-05-01", "2026-06-01", "2026-07-01"]),
            "forecast_qty": [20, 20, 20, 1000],
        }
    )
    acknowledgements = pd.DataFrame(
        {
            "po_number": ["PO-100"] * 3,
            "vendor_sku": ["SKU-1"] * 3,
            "delivery_date": ["2026-04-10", "2026-05-10", "2026-06-10"],
            "ordered_qty": [100, 0, 0],
            "confirmed_qty": [25, 25, 25],
        }
    )

    report = RootCauseService(forecasts, acknowledgements).root_cause_analysis("PO-100", lookback_months=None)

    forecast_finding = next(finding for finding in report["conclusions"] if finding["cause"] == "under_forecasting")
    assert forecast_finding["evidence"]["forecast_for_purchase_order_month"] == 60.0


def test_forecast_check_reports_po_coverage_gap_when_recent_shipments_do_not_exceed_forecast():
    forecasts = pd.DataFrame(
        {
            "vendor_sku": ["SKU-1"] * 3,
            "forecast_month_parsed": pd.to_datetime(["2026-04-01", "2026-05-01", "2026-06-01"]),
            "forecast_qty": [20, 20, 20],
        }
    )
    acknowledgements = pd.DataFrame(
        {
            "po_number": ["PO-100"] * 3,
            "vendor_sku": ["SKU-1"] * 3,
            "delivery_date": ["2026-04-10", "2026-05-10", "2026-06-10"],
            "ordered_qty": [100, 0, 0],
            "confirmed_qty": [15, 15, 15],
        }
    )

    report = RootCauseService(forecasts, acknowledgements).root_cause_analysis("PO-100", lookback_months=None)

    assert "forecast_below_purchase_order" in [finding["cause"] for finding in report["conclusions"]]


def test_root_cause_identifies_supplier_and_buyer_supply_exceptions():
    supplier_pos = pd.DataFrame(
        {
            "vendor_sku": ["SKU-1", "SKU-1", "SKU-1", "SKU-1"],
            "supplier_forecast_qty": [100, 100, 100, 100],
            "supplier_ordered_qty": [100, 100, 100, 70],
            "supplier_confirmed_qty": [100, 80, 100, 70],
            "supplier_received_qty": [100, 80, 90, 70],
            "damaged_qty": [0, 0, 10, 0],
            "incorrect_qty": [0, 0, 0, 5],
            "expected_receipt_date": ["2026-05-01"] * 4,
            "actual_receipt_date": ["2026-05-10", "2026-05-01", "2026-05-01", "2026-05-01"],
            "supplier_issue_type": ["SUPPLIER_DELAYED_SHIPPING", "SUPPLIER_PARTIAL_CONFIRMATION", "PARTIALLY_DAMAGED_SHIPMENT", "INSUFFICIENT_ORDER_QUANTITY"],
        }
    )
    report = RootCauseService(
        pd.DataFrame({"vendor_sku": ["SKU-1"], "forecast_month_parsed": ["2026-05-01"], "forecast_qty": [100]}),
        pd.DataFrame({"vendor_sku": ["SKU-1"], "delivery_date": ["2026-05-01"], "ordered_qty": [100], "confirmed_qty": [100]}),
        supplier_pos=supplier_pos,
    ).root_cause_analysis("SKU-1", lookback_months=None)

    causes = {finding["cause"] for finding in report["conclusions"]}
    assert {"supplier_delivery_delay", "supplier_under_supply", "damaged_supplier_shipment", "incorrect_supplier_shipment", "buyer_supplier_order_issue"}.issubset(causes)


def test_supplier_received_quantity_excludes_receipts_after_acknowledgement_date():
    supplier_pos = pd.DataFrame(
        {
            "vendor_sku": ["SKU-1", "SKU-1"],
            "supplier_forecast_qty": [100, 100],
            "supplier_ordered_qty": [100, 100],
            "supplier_confirmed_qty": [100, 100],
            "supplier_received_qty": [60, 40],
            "damaged_qty": [0, 0],
            "incorrect_qty": [0, 0],
            "expected_receipt_date": ["2026-05-01", "2026-05-01"],
            "actual_receipt_date": ["2026-05-01", "2026-05-10"],
            "supplier_issue_type": ["NONE", "NONE"],
        }
    )
    report = RootCauseService(
        pd.DataFrame({"vendor_sku": ["SKU-1"], "forecast_month_parsed": ["2026-05-01"], "forecast_qty": [100]}),
        pd.DataFrame({"vendor_sku": ["SKU-1"], "delivery_date": ["2026-05-05"], "ordered_qty": [100], "confirmed_qty": [100]}),
        supplier_pos=supplier_pos,
    ).root_cause_analysis("SKU-1", lookback_months=None)

    supplier_evidence = next(item["supplier_purchase_orders"] for item in report["evidence"] if "supplier_purchase_orders" in item)
    assert supplier_evidence["supplier_received_qty"] == 60.0

import pandas as pd

from mcp_client import SupplyChainMCPClient


def test_search_inventory_expands_a_po_to_all_its_forecast_products(monkeypatch) -> None:
    forecasts = pd.DataFrame(
        {
            "vendor_sku": ["SKU-1", "SKU-1", "SKU-2", "SKU-3"],
            "forecast_month": pd.to_datetime(["2026-05-01", "2026-06-01", "2026-05-01", "2026-05-01"]),
            "forecast_qty": [10, 12, 20, 30],
        }
    )
    acknowledgements = pd.DataFrame(
        {
            "po_number": ["PO-100", "PO-100", "PO-200"],
            "vendor_sku": ["SKU-1", "SKU-2", "SKU-3"],
        }
    )
    monkeypatch.setattr(SupplyChainMCPClient, "forecast_df", property(lambda _: forecasts))
    monkeypatch.setattr(SupplyChainMCPClient, "ack_df", property(lambda _: acknowledgements))
    client = SupplyChainMCPClient.__new__(SupplyChainMCPClient)

    forecast_matches, ack_matches = client.search_inventory("PO-100")

    assert ack_matches["po_number"].tolist() == ["PO-100", "PO-100"]
    assert forecast_matches["vendor_sku"].tolist() == ["SKU-1", "SKU-1", "SKU-2"]


def test_root_cause_uses_the_supplied_filtered_acknowledgements(monkeypatch) -> None:
    forecasts = pd.DataFrame(
        {
            "vendor_sku": ["SKU-1", "SKU-1"],
            "forecast_month": pd.to_datetime(["2026-05-01", "2026-06-01"]),
            "forecast_qty": [100, 100],
        }
    )
    all_acknowledgements = pd.DataFrame(
        {
            "po_number": ["PO-MAY", "PO-JUNE"],
            "vendor_sku": ["SKU-1", "SKU-1"],
            "delivery_date": ["2026-05-10", "2026-06-10"],
            "ordered_qty": [100, 200],
            "confirmed_qty": [0, 0],
        }
    )
    filtered_acknowledgements = all_acknowledgements.iloc[[0]].copy()
    monkeypatch.setattr(SupplyChainMCPClient, "forecast_df", property(lambda _: forecasts))
    monkeypatch.setattr(SupplyChainMCPClient, "ack_df", property(lambda _: all_acknowledgements))
    monkeypatch.setattr(SupplyChainMCPClient, "inventory_df", property(lambda _: pd.DataFrame()))
    client = SupplyChainMCPClient.__new__(SupplyChainMCPClient)

    report = client.root_cause_analysis("SKU-1", acknowledgements=filtered_acknowledgements)

    assert report["summary"]["purchase_order_qty"] == 100.0
    assert report["summary"]["forecast_for_purchase_order_month"] == 100.0

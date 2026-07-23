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

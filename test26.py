import pandas as pd
from mcp_client import SupplyChainMCPClient
import asyncio
from streamlit_app import parse_date_filters

async def test():
    c = SupplyChainMCPClient()
    a = c.ack_df
    f = c.forecast_df
    # May 2026 filter
    filters = {"ack_date": [("2026-05-01", "2026-05-31")]}
    _, acks = parse_date_filters(filters, f, a)
    report = c.root_cause_analysis("1000127", acknowledgements=acks)
    for cause in report.get("conclusions", []):
        if cause["cause"] in ("forecast_below_purchase_order", "under_forecasting", "no_forecast_issue"):
            print("Current UI Output:")
            print(f"**Last 3 Months Forecast:** {cause['evidence'].get('last_three_month_forecast', 0):.0f}")
            print(f"**Actual PO Quantity:** {cause['evidence'].get('purchase_order_qty', 0):.0f}")
            break

asyncio.run(test())

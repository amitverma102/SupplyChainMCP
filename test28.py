import pandas as pd
from mcp_client import SupplyChainMCPClient
import asyncio
from streamlit_app import parse_date_filters

async def test():
    c = SupplyChainMCPClient()
    a = c.ack_df
    f = c.forecast_df
    filters = {"ack_date": [("2026-05-01", "2026-05-31")]}
    _, acks = parse_date_filters(filters, f, a)
    report = c.root_cause_analysis("1000127", acknowledgements=acks)
    for cause in report.get("conclusions", []):
        if cause["cause"] in ("forecast_below_purchase_order", "under_forecasting", "no_forecast_issue"):
            print(cause)
            break

asyncio.run(test())

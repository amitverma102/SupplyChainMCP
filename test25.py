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
    print("Ack dates after filter:")
    print(acks["delivery_date"].unique())

asyncio.run(test())

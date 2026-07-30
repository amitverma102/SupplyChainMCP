import pandas as pd
from mcp_client import SupplyChainMCPClient
import asyncio

async def test():
    c = SupplyChainMCPClient()
    a = c.ack_df
    # Mocking the UI date filter: May 2026
    selected_acks = a[(a["delivery_date"] >= "2026-05-01") & (a["delivery_date"] <= "2026-05-31")]
    report = c.root_cause_analysis("1000127", acknowledgements=selected_acks)
    
    monthly_sample = next((e["monthly_sample"] for e in report.get("evidence", []) if "monthly_sample" in e), [])
    df = pd.DataFrame(monthly_sample)
    print(df[["month", "inventory_qty", "Actual PO Quantity"]].head(15))

asyncio.run(test())

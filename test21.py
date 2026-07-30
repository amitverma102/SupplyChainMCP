import pandas as pd
from mcp_client import SupplyChainMCPClient
import asyncio
import json

async def test():
    c = SupplyChainMCPClient()
    a = c.ack_df
    # Mocking the UI date filter: May 2026
    selected_acks = a[(a["delivery_date"] >= "2026-05-01") & (a["delivery_date"] <= "2026-05-31")]
    report = c.root_cause_analysis("1000127", acknowledgements=selected_acks)
    
    supplier_evidence = next((e["supplier_purchase_orders"] for e in report.get("evidence", []) if "supplier_purchase_orders" in e), {})
    s_monthly = supplier_evidence.get("supplier_monthly", [])
    print("supplier_monthly:", s_monthly)

asyncio.run(test())

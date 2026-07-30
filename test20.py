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
    
    conclusions = report.get("conclusions", [])
    supplier_causes = [c for c in conclusions if any(term in str(c.get("cause")).lower() for term in ("supplier", "vendor", "buyer_supplier")) and not str(c.get("cause")).startswith("missing_")]
    
    print(f"Supplier Causes: {supplier_causes}")

asyncio.run(test())

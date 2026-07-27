import asyncio
from mcp_client import SupplyChainMCPClient
import json

async def main():
    client = SupplyChainMCPClient()
    await client.initialize()
    res = client.root_cause_analysis("JP-439-01")
    for ev in res.get("evidence", []):
        if "monthly_sample" in ev:
            print(json.dumps(ev["monthly_sample"], indent=2, default=str))

asyncio.run(main())

from mcp_client import SupplyChainMCPClient
import pandas as pd

client = SupplyChainMCPClient()
df = client.forecast_vs_actual()
print(df.head())

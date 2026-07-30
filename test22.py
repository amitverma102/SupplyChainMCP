from mcp_client import SupplyChainMCPClient
import pandas as pd

client = SupplyChainMCPClient()
acks = client.load_acknowledgements()

if not acks.empty:
    df = acks.copy()
    df["month"] = pd.to_datetime(df["delivery_date"]).dt.strftime("%Y-%m")
    grouped = df.groupby("month")[["ordered_qty", "confirmed_qty"]].sum().reset_index()
    grouped["fill_rate_pct"] = (grouped["confirmed_qty"] / grouped["ordered_qty"] * 100).fillna(0)
    print(grouped.head())

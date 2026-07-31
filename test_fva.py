import sys
import os
sys.path.append(os.getcwd())
from mcp_client import SupplyChainMCPClient
client = SupplyChainMCPClient("http://localhost:8000")
df = client.forecast_vs_actual()
if not df.empty:
    df = df[df["forecast_qty"] > 0]
    df["error"] = (df["forecast_qty"] - df["actual_qty"]).abs() / df["forecast_qty"] * 100
    df["accuracy"] = (1 - (df["forecast_qty"] - df["actual_qty"]).abs() / df["forecast_qty"]) * 100
    print(df[["month", "forecast_qty", "actual_qty", "error", "accuracy"]])

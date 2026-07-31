import duckdb
import pandas as pd
conn = duckdb.connect("mcp_cache.duckdb", read_only=True)
q = """
WITH monthly_forecast AS (
    SELECT
        forecast_month_parsed AS month,
        SUM(forecast_qty) AS forecast_qty
    FROM forecasts
    WHERE forecast_month_parsed IS NOT NULL
    GROUP BY 1
),
monthly_actual AS (
    SELECT
        CAST(DATE_TRUNC('month', TRY_CAST(delivery_date AS TIMESTAMP)) AS DATE) AS month,
        SUM(confirmed_qty) AS actual_qty
    FROM acks
    WHERE TRY_CAST(delivery_date AS TIMESTAMP) IS NOT NULL
    GROUP BY 1
)
SELECT
    f.month,
    f.forecast_qty,
    COALESCE(a.actual_qty, 0) AS actual_qty
FROM monthly_forecast f
LEFT JOIN monthly_actual a ON f.month = a.month
ORDER BY f.month
"""
df = conn.execute(q).df()
if not df.empty:
    df = df[df["forecast_qty"] > 0]
    df["error"] = (df["forecast_qty"] - df["actual_qty"]).abs() / df["forecast_qty"] * 100
    df["accuracy"] = (1 - (df["forecast_qty"] - df["actual_qty"]).abs() / df["forecast_qty"]) * 100
    print(df[["month", "forecast_qty", "actual_qty", "error", "accuracy"]])

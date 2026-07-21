from __future__ import annotations
import logging
from typing import Dict, Any
import duckdb
import polars as pl
import pandas as pd

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Analytics engine using DuckDB for fast, SQL-style analytics over Parquet/Polars.

    The design keeps datasets immutable and uses DuckDB for heavy aggregation.
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection | None = None):
        self.conn = connection or duckdb.connect(database=":memory:")

    def register_forecasts(self, df: pl.DataFrame, name: str = "forecasts") -> None:
        # DuckDB can query pandas/pyarrow objects; convert to pandas
        pdf = df.to_pandas()
        self.conn.register(name, pdf)

    def register_acknowledgements(self, df: pd.DataFrame, name: str = "acks") -> None:
        self.conn.register(name, df)

    def forecast_summary(self) -> pd.DataFrame:
        # ``forecast_month`` retains the source workbook header (for example,
        # "February" or "2026 P01").  The loader puts its normalized date in
        # ``forecast_month_parsed``; casting the source label makes DuckDB fail
        # and callers currently turn that exception into an empty DataFrame.
        q = """
        SELECT
          forecast_month_parsed as forecast_month,
          SUM(forecast_qty) as forecast_qty
        FROM forecasts
        WHERE forecast_month_parsed IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """
        return self.conn.execute(q).df()

    def forecast_vs_actual(self) -> pd.DataFrame:
        try:
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
                a.actual_qty
            FROM monthly_forecast f
            LEFT JOIN monthly_actual a USING (month)
            ORDER BY f.month
            """
            return self.conn.execute(q).df()
        except Exception as e:
            logger.exception("Unable to calculate forecast vs. actuals: %s", e)
            return pd.DataFrame(columns=["month", "forecast_qty", "actual_qty"])


__all__ = ["AnalyticsService"]

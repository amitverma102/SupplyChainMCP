from datetime import date

import pandas as pd
import polars as pl

from services.analytics_service import AnalyticsService


def test_forecast_summary_uses_normalized_forecast_month() -> None:
    service = AnalyticsService()
    service.register_forecasts(
        pl.DataFrame(
            {
                # These are the original workbook column labels, not dates.
                "forecast_month": ["February", "February", "March"],
                "forecast_month_parsed": [date(2026, 2, 1), date(2026, 2, 1), date(2026, 3, 1)],
                "forecast_qty": [10, 15, 20],
            }
        )
    )

    summary = service.forecast_summary()

    assert summary["forecast_month"].dt.date.tolist() == [date(2026, 2, 1), date(2026, 3, 1)]
    assert summary["forecast_qty"].tolist() == [25, 20]


def test_forecast_vs_actual_leaves_future_months_without_actuals_blank() -> None:
    service = AnalyticsService()
    service.register_forecasts(
        pl.DataFrame(
            {
                "forecast_month_parsed": [date(2026, 2, 1), date(2026, 3, 1)],
                "forecast_qty": [100, 150],
            }
        )
    )
    service.register_acknowledgements(
        pd.DataFrame(
            {
                "delivery_date": ["2026-02-15"],
                "confirmed_qty": [80],
            }
        )
    )

    result = service.forecast_vs_actual()

    assert result["month"].dt.date.tolist() == [date(2026, 2, 1), date(2026, 3, 1)]
    assert result["actual_qty"].iloc[0] == 80
    assert pd.isna(result["actual_qty"].iloc[1])

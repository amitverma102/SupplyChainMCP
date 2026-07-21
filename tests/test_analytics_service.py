from datetime import date

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

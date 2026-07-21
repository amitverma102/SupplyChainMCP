import pandas as pd

from dashboard_components import prepare_calendar_data


def test_prepare_calendar_data_sorts_month_columns_chronologically_for_tables() -> None:
    table = pd.DataFrame(
        {
            "forecast_month": ["April 2026", "February 2026", "March 2026"],
            "forecast_qty": [40, 20, 30],
        }
    )

    result = prepare_calendar_data(table)

    assert result["forecast_month"].dt.month.tolist() == [2, 3, 4]
    assert result["forecast_qty"].tolist() == [20, 30, 40]

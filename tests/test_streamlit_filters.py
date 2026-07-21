from datetime import date

import pandas as pd

from streamlit_app import apply_filters


def test_apply_filters_leaves_unselected_and_date_filters_unchanged() -> None:
    forecasts = pd.DataFrame(
        {
            "vendor": ["Acme", "Bravo"],
            "forecast_month": pd.to_datetime(["2026-02-01", "2026-03-01"]),
        }
    )

    result = apply_filters(
        forecasts,
        {
            "vendor": [],
            "forecast_month": [(date(2026, 2, 1), date(2026, 3, 1))],
        },
    )

    pd.testing.assert_frame_equal(result, forecasts)


def test_apply_filters_applies_selected_categorical_value() -> None:
    frame = pd.DataFrame({"vendor": ["Acme", "Bravo"]})

    result = apply_filters(frame, {"vendor": ["Acme"]})

    assert result["vendor"].tolist() == ["Acme"]

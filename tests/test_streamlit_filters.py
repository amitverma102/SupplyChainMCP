from datetime import date

import pandas as pd

from streamlit_app import apply_filters, compute_kpis, parse_date_filters


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


def test_acknowledgement_date_filter_uses_ack_date() -> None:
    acknowledgements = pd.DataFrame(
        {
            "ack_date": ["2026-01-07", "2026-06-01"],
            "delivery_date": ["2026-06-15", "2026-06-15"],
            "ordered_qty": [10, 20],
        }
    )

    _, result = parse_date_filters(
        {"ack_date": [(date(2026, 1, 1), date(2026, 1, 31))]},
        pd.DataFrame(),
        acknowledgements,
    )

    assert result["ordered_qty"].tolist() == [10]


def test_dashboard_kpis_receive_filtered_data() -> None:
    class Client:
        def compute_dashboard_kpis(self, forecasts, acknowledgements):
            assert len(acknowledgements) == 1
            return {
                "forecast_value": 10.0,
                "ordered_quantity": 20.0,
                "confirmed_quantity": 15.0,
                "fill_rate": 0.75,
                "products_short": 1.0,
            }

    metrics = compute_kpis(pd.DataFrame(), pd.DataFrame({"ordered_qty": [20]}), Client())

    assert metrics["Ordered Quantity"]["value"] == "20"

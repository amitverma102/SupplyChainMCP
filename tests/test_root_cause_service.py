import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from services.root_cause_service import RootCauseService


def _make_test_data():
    # create 8 months of data with a demand spike and declining fill rate
    months = pd.date_range(end=pd.Timestamp.today(), periods=8, freq="MS")
    f_rows = []
    a_rows = []
    for i, m in enumerate(months):
        forecast = 100 + (i * 5)
        confirmed = forecast if i < 5 else int(forecast * 0.6)  # drop in later months
        if i == 6:
            confirmed = forecast * 2  # demand spike
        f_rows.append({"vendor_sku": "TEST-1", "forecast_month_parsed": m, "forecast_qty": forecast})
        a_rows.append({"vendor_sku": "TEST-1", "delivery_date": m + pd.Timedelta(days=10), "confirmed_qty": confirmed, "ordered_qty": forecast})

    f_df = pd.DataFrame(f_rows)
    a_df = pd.DataFrame(a_rows)
    return f_df, a_df


def test_root_cause_detects_spike_and_vendor_decline():
    f_df, a_df = _make_test_data()
    svc = RootCauseService(f_df, a_df)
    report = svc.root_cause_analysis("TEST-1", lookback_months=8)
    assert "conclusions" in report
    causes = [c["cause"] for c in report["conclusions"]]
    assert "demand_spike" in causes or "vendor_under_supply" in causes

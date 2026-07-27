import asyncio
from services.root_cause_service import RootCauseService
from services.forecast_service import ForecastService
from services.acknowledgement_service import AcknowledgementService
from services.supplier_po_service import SupplierPOService
from pathlib import Path
import json
import pandas as pd

fs = ForecastService("Forecasts")
f_df = fs.parse_file(Path("Forecasts/Order_Proj__52853_JUVIA'S PLACE-2026-01-28.xlsx"))

acks = AcknowledgementService("Acknowledgements").discover_files()
a_df = pd.concat([AcknowledgementService("Acknowledgements").parse_file(f) for f in acks[:10]], ignore_index=True) if acks else pd.DataFrame()

sps = SupplierPOService("Purchase_Orders")
sps_dfs = sps.discover_files()
sp_df = pd.concat([sps.parse_file(f) for f in sps_dfs[:5]], ignore_index=True) if sps_dfs else pd.DataFrame()

rcs = RootCauseService(f_df, a_df, sp_df, pd.DataFrame())
report = rcs.root_cause_analysis("JP-439-01")
for ev in report.get("evidence", []):
    if "monthly_sample" in ev:
        print(json.dumps(ev["monthly_sample"], indent=2, default=str))

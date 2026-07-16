from __future__ import annotations
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP  # the actual SDK class mcp install expects

from config import load_config
from services.forecast_service import ForecastService
from services.acknowledgement_service import AcknowledgementService
from services.analytics_service import AnalyticsService
from services.matching_service import MatchingService
from services.cache_service import CacheService
from services.root_cause_service import RootCauseService
from services.reporting_service import ReportingService

cfg = load_config(str(Path(__file__).resolve().parent / "config.yaml"))

logging.basicConfig(
    level=getattr(logging, cfg.logging.level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("SupplyChainMCP")

BASE_DIR = Path(__file__).resolve().parent


def resolve_dir(p: str | Path) -> Path:
    """Resolve a config path against the project's own directory (not the
    process cwd), and ensure it exists."""
    p = Path(p)
    if not p.is_absolute():
        p = BASE_DIR / p
    p.mkdir(parents=True, exist_ok=True)
    return p


cache_dir = resolve_dir(cfg.app.cache_dir)
reports_dir = resolve_dir(cfg.app.reports_dir)
logs_dir = resolve_dir(cfg.app.logs_dir)
forecasts_dir = resolve_dir(cfg.app.forecasts_dir)
acknowledgements_dir = resolve_dir(cfg.app.acknowledgements_dir)

cache = CacheService(cache_dir / "metadata.db")
forecast_svc = ForecastService(forecasts_dir, cache_service=cache)
ack_svc = AcknowledgementService(acknowledgements_dir, cache_service=cache)

forecasts = forecast_svc.load_all()
acks = ack_svc.load_all()

analytics = AnalyticsService()
if not forecasts.is_empty():
    analytics.register_forecasts(forecasts)
if not acks.empty:
    analytics.register_acknowledgements(acks)

matching = MatchingService()
root_cause = RootCauseService(forecasts.to_pandas() if not forecasts.is_empty() else None, acks)

# ---- Module-level FastMCP object: THIS is what `mcp install` scans for ----
mcp = FastMCP(cfg.app.name)

@mcp.tool()
def dataset_status() -> dict:
    """Return counts of loaded forecasts and acknowledgements."""
    return {"forecasts": 0 if forecasts.is_empty() else len(forecasts), "acks": len(acks)}

@mcp.tool()
def refresh_forecasts():
    """Reload forecast data from disk."""
    return forecast_svc.load_all()

@mcp.tool()
def refresh_acknowledgements():
    """Reload acknowledgement data from disk."""
    return ack_svc.load_all()

@mcp.tool()
def refresh_all():
    """Reload both forecasts and acknowledgements."""
    return (forecast_svc.load_all(), ack_svc.load_all())

@mcp.tool()
def forecast_summary(*args, **kwargs):
    """Summarize forecast data."""
    return analytics.forecast_summary(*args, **kwargs)

@mcp.tool()
def forecast_vs_actual(*args, **kwargs):
    """Compare forecast vs actual."""
    return analytics.forecast_vs_actual(*args, **kwargs)

@mcp.tool()
def root_cause_analysis(product, vendor=None, customer=None, po_number=None, lookback_months=12, recent_weeks=8):
    """Run root cause analysis for a product/vendor/customer combination."""
    return root_cause.root_cause_analysis(product, vendor, customer, po_number, lookback_months, recent_weeks)


if __name__ == "__main__":
    mcp.run()
# SupplyChainMCP

**Enterprise-grade MCP (Model Context Protocol) server for intelligent supply chain analytics.**

An AI-powered platform enabling Supply Chain Managers, Procurement Managers, Demand Planners, and Vendor Managers to investigate forecast accuracy, vendor performance, demand trends, root causes of shortages, and supply chain risks using advanced analytics, machine learning, and natural language understanding.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Installation (macOS)](#installation-macos)
3. [Project Structure](#project-structure)
4. [Configuration](#configuration)
5. [Data Input](#data-input)
6. [Running the Server](#running-the-server)
7. [MCP Tools Reference](#mcp-tools-reference)
8. [Example Usage](#example-usage)
9. [Analytics Capabilities](#analytics-capabilities)
10. [Troubleshooting](#troubleshooting)
11. [Development & Testing](#development--testing)

---

## Quick Start

```bash
# 1. Create and activate virtualenv
python3.12 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Place your data files
# - Forecast Excel files in: Forecasts/
# - Acknowledgement JSON files in: Acknowledgements/

# 4. Run the server
python server.py

# Expected output:
# 2026-07-14 16:08:00 INFO SupplyChainMCP Loading forecasts...
# 2026-07-14 16:08:05 INFO SupplyChainMCP Loaded 99704 forecast records across 14 files
# 2026-07-14 16:08:06 INFO SupplyChainMCP MCP server initialized. Tools exposed: [...]
```

## Streamlit Control Tower Dashboard
A modern, enterprise-grade dashboard has been added in `streamlit_app.py` and integrates directly with the existing SupplyChainMCP analytics engine.

### Run the dashboard
```bash
pip install -r requirements-streamlit.txt
streamlit run streamlit_app.py
```

### Features
- Executive KPI cards and drill-down analytics
- Forecast analysis, PO acknowledgement review, CUT analysis, vendor performance, risk management, and exception monitoring
- AI investigation workspace for root cause summaries and conversational insights
- Plotly charts, AgGrid tables, export to CSV, and interactive global filters
- Modular page architecture, session-state management, and styling for dark/light dashboard modes

---

## Installation (macOS)

### Prerequisites
- **Python 3.12+** (required)
- **macOS 10.13+** (tested on macOS 12+)
- **Xcode Command Line Tools** (for compilation of native packages)

### Step-by-Step Setup

1. **Verify Python version:**
   ```bash
   python3 --version
   # Should output: Python 3.12.x or later
   ```

2. **Clone/download the project and navigate to it:**
   ```bash
   cd /path/to/SupplyChainMCP
   ```

3. **Create a virtual environment:**
   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   ```

4. **Install dependencies:**
   ```bash
   pip install --upgrade pip setuptools wheel
   pip install -r requirements.txt
   ```

   If you encounter build errors for native packages (e.g., `polars`, `scipy`), ensure Xcode CLT is installed:
   ```bash
   xcode-select --install
   ```

5. **Verify installation:**
   ```bash
   python -c "import fastmcp, pandas, polars, duckdb, pydantic; print('All dependencies OK')"
   ```

6. **(Optional) Install FastMCP for full MCP support:**
   ```bash
   pip install fastmcp
   ```

---

## Project Structure

```
SupplyChainMCP/
├── Forecasts/              # Place Excel forecast files here
├── Acknowledgements/       # Place JSON EDI 855 acknowledgements here
├── cache/                  # Incremental load cache (auto-created)
├── reports/                # Generated reports & dashboards (auto-created)
├── logs/                   # Application logs (auto-created)
│
├── services/               # Core business logic layer
│   ├── forecast_service.py
│   ├── acknowledgement_service.py
│   ├── matching_service.py
│   ├── analytics_service.py
│   ├── root_cause_service.py
│   └── cache_service.py
│
├── models/                 # Pydantic v2 data models
│   └── schemas.py
│
├── tests/                  # Unit & integration tests
│   ├── test_matching_service.py
│   ├── test_root_cause_service.py
│   └── test_acknowledgement_service.py
│
├── config.yaml             # Application configuration
├── config.py               # Config loader
├── server.py               # MCP server entrypoint
├── requirements.txt        # Python dependencies
├── pyproject.toml          # Poetry metadata
├── .env.example            # Environment template
├── README.md               # This file
│
└── .vscode/                # VS Code workspace settings
    ├── launch.json         # Debug configuration
    ├── tasks.json          # Build/test tasks
    └── settings.json       # Editor settings
```

---

## Configuration

### config.yaml

The application reads configuration from `config.yaml` at startup:

```yaml
app:
  name: SupplyChainMCP
  env: development
  data_dir: "./"
  forecasts_dir: "Forecasts"      # Relative to data_dir
  acknowledgements_dir: "Acknowledgements"
  cache_dir: "cache"
  reports_dir: "reports"
  logs_dir: "logs"
  max_workers: 4                  # Parallel processing threads

logging:
  level: INFO                     # DEBUG, INFO, WARNING, ERROR, CRITICAL
  file: "logs/supplychainmcp.log"
```

**Customizing config:**
- Set `env: production` to suppress debug logs
- Increase `max_workers` for larger datasets (default: 4)
- Change `forecasts_dir` and `acknowledgements_dir` to custom paths

### Environment Variables

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

---

## Data Input

### Forecast Files (Excel)

Place Excel workbooks (`.xlsx`, `.xlsm`) in `Forecasts/`:

**Supported formats:**
- **Wide format** (monthly columns): Vendor SKU | Description | Jan-2026 | Feb-2026 | ...
- **Long format** (1 row per forecast): Vendor SKU | Forecast Month | Forecast Qty
- **Mixed headers**: Titles, footers, and summary rows are auto-detected and skipped

**Expected columns:**
- Product identifiers: `UPC`, `Vendor SKU`, `Buyer Part Number`, `Retail Item Number`
- Metadata: `Description`, `Brand`, `Department`
- Forecast month columns: Date-like headers (`Jul-2026`, `2026-07`, `2026 P06`)
- Quantities: Numeric columns

**Example:**
```
Vendor SKU | Description  | Jul-26 | Aug-26 | Sep-26
SKU-12345  | Blue Widget  | 100    | 120    | 110
SKU-67890  | Red Gadget   | 50     | 55     | 60
```

### Acknowledgement Files (JSON)

Place JSON files (`.json`) in `Acknowledgements/` containing EDI 855 purchase order acknowledgements:

**Expected structure:**
```json
{
  "header": {
    "vendor": "Supplier Name",
    "customer": "Retailer Name",
    "po_number": "PO-12345",
    "po_date": "2026-07-01"
  },
  "lines": [
    {
      "vendor_sku": "SKU-12345",
      "buyer_part_number": "BUYER-001",
      "upc": "123456789",
      "description": "Blue Widget",
      "ordered_quantity": 100,
      "confirmed_quantity": 95,
      "price": 10.50,
      "status_code": "A",
      "delivery_date": "2026-07-20"
    }
  ]
}
```

**Field name variants supported:**
- `vendor_sku` | `vendorSku` | `seller_item_id`
- `buyer_part_number` | `buyerPartNumber`
- `upc` | `gtin`
- `ordered_quantity` | `orderedQty` | `ordered`
- `confirmed_quantity` | `confirmedQty` | `confirmed`
- `status_code` | `status`

---

## Running the Server

### Development Mode (Local Adapter)

```bash
source .venv/bin/activate
python server.py
```

Output:
```
2026-07-14 16:08:00 INFO SupplyChainMCP Loading forecasts...
2026-07-14 16:08:05 INFO SupplyChainMCP Loaded 99704 forecast records across 14 files
2026-07-14 16:08:06 INFO SupplyChainMCP MCP server initialized. Tools exposed: [...]
```

The server will:
1. Read `config.yaml`
2. Discover all Excel files in `Forecasts/`
3. Discover all JSON files in `Acknowledgements/`
4. Parse and normalize datasets
5. Build incremental cache
6. Register MCP tools
7. Log status and available tools

### VS Code Integration

Open the workspace and use the provided debug configuration:

```bash
code /path/to/SupplyChainMCP
```

In VS Code:
- Press `Ctrl+Shift+D` (or Cmd+Shift+D on macOS) to open the Run panel
- Select "**Python: Run MCP Server**" and click **Start Debugging** (F5)
- The server will launch with full debugging support

### Production Deployment

For production deployment with FastMCP:

```bash
pip install fastmcp
# Configure your MCP client to connect to this server
python server.py
```

---

## MCP Tools Reference

All tools are registered with the MCP server and can be invoked by an LLM or MCP client.

### Data Management Tools

#### `dataset_status()`
Returns summary of loaded datasets.

**Returns:**
```json
{
  "forecasts": 99704,
  "acks": 5000000
}
```

#### `refresh_forecasts()`
Reload all forecast files (respects incremental cache).

#### `refresh_acknowledgements()`
Reload all acknowledgement files (respects incremental cache).

#### `refresh_all()`
Reload both forecasts and acknowledgements.

---

### Analytics Tools

#### `forecast_summary()`
Monthly forecast totals.

**Returns:** DataFrame with columns `forecast_month`, `forecast_qty`

#### `forecast_vs_actual()`
Compare forecast vs actual confirmed quantities by month.

**Returns:** DataFrame with `month`, `forecast_qty`, `actual_qty`, fill rates

---

### Advanced Root Cause Analysis

#### `root_cause_analysis(product, vendor=None, customer=None, po_number=None, lookback_months=12, recent_weeks=8)`

**Parameters:**
- `product`: Product SKU or identifier
- `vendor`: (Optional) Vendor name or ID
- `customer`: (Optional) Customer/retailer name
- `po_number`: (Optional) Specific PO to investigate
- `lookback_months`: Historical lookback period (default: 12)
- `recent_weeks`: Recent period for trend detection (default: 8)

**Returns:**
```json
{
  "product": "SKU-12345",
  "summary": {
    "total_forecast": 12000,
    "total_confirmed": 9800,
    "overall_fill_rate": 0.817
  },
  "evidence": [
    {
      "monthly_sample": [
        {"forecast_month": "2026-07-01", "forecast_qty": 1000, "confirmed_qty": 950, "fill_rate": 0.95}
      ]
    }
  ],
  "conclusions": [
    {
      "cause": "vendor_under_supply",
      "confidence": "high",
      "evidence": {
        "slope": -0.05,
        "recent_avg": 0.80,
        "earlier_avg": 0.95
      }
    }
  ],
  "recommendations": [
    "Open vendor performance case and consider alternative suppliers or expedite shipments."
  ],
  "confidence": 0.85
}
```

**Root cause classifications:**
- `demand_exceeded_forecast`: Customer demand > forecast
- `demand_spike`: Abnormal demand spike detected
- `product_cut`: Forecast or orders suddenly dropped
- `vendor_under_supply`: Vendor fill rate declining
- `forecast_missing`: Orders exist but forecast is zero
- `unknown`: Insufficient data

---

## Example Usage

### Example 1: Check Overall Dataset Health

```python
from server import main, MCPAdapter

# Initialize server
main()

# The adapter exposes tools via the MCPAdapter instance
# In a real MCP client context, you'd invoke:
# tool: dataset_status
# Result: {"forecasts": 99704, "acks": 5000000}
```

### Example 2: Investigate a Product Shortage

```
User Query: "Why was SKU 1200511 short supplied?"

Tool: root_cause_analysis
Parameters: {
  "product": "1200511",
  "lookback_months": 12
}

Response:
{
  "product": "1200511",
  "summary": {
    "total_forecast": 5000,
    "total_confirmed": 900,
    "overall_fill_rate": 0.18
  },
  "conclusions": [
    {
      "cause": "demand_exceeded_forecast",
      "confidence": "high",
      "evidence": {
        "avg_forecast": 417,
        "avg_actual": 610
      }
    },
    {
      "cause": "vendor_under_supply",
      "confidence": "high",
      "evidence": {
        "slope": -0.08,
        "recent_avg": 0.72,
        "earlier_avg": 0.97
      }
    }
  ],
  "recommendations": [
    "Increase safety stock and engage demand planning to review forecast inputs.",
    "Open vendor performance case and consider alternative suppliers or expedite shipments."
  ]
}

AI Summary:
"Product 1200511 experienced a 18% fill rate. Historical analysis indicates customer demand 
exceeded forecast in 8 of 10 months (avg +46%). Concurrently, vendor fill rate declined from 
97% to 72%. Most likely root cause: demand spike combined with vendor supply deterioration. 
Recommend: engage demand planning, increase safety stock, and escalate vendor performance."
```

### Example 3: Forecast Accuracy Analysis

```
User Query: "Show forecast accuracy for July"

Tool: forecast_vs_actual
Result:
{
  "month": ["2026-07-01"],
  "forecast_qty": [50000],
  "actual_qty": [48500],
  "accuracy": [0.97]
}
```

---

## Analytics Capabilities

The server computes the following analytics:

### Demand Analysis
- **Demand Trend**: Linear regression to detect growth/decline
- **Demand Volatility**: Standard deviation of order patterns
- **Demand Spike Detection**: Z-score anomaly detection
- **Demand Seasonality**: Seasonal adjustment factors

### Forecast Accuracy
- **MAPE**: Mean Absolute Percentage Error
- **WMAPE**: Weighted MAPE
- **Forecast Bias**: Systematic over/under-forecasting
- **Forecast Consumption**: % of forecast consumed by actual orders

### Vendor Performance
- **Historical Fill Rate**: % of orders confirmed
- **Late Confirmations**: % of acknowledgements after expected date
- **Repeated Partial Confirmations**: Pattern detection
- **Vendor Reliability Score**: Composite metric (0–100)

### Product Performance
- **Shortage Count**: # of shortages in lookback period
- **Oversupply Count**: # of over-supplies
- **Product Cut Detection**: Sudden forecast/order drops
- **Repeated Shortage Pattern**: Chronic supply issues

### Inventory & Supply Risk
- **ABC Classification**: Pareto analysis by value
- **XYZ Classification**: Demand variability classification
- **Supply Risk Score**: Vendor + demand risk combination
- **Inventory Optimization Recommendations**

---

## Troubleshooting

### Issue: `ModuleNotFoundError: No module named 'services'`

**Solution:**
Ensure you're running from the project root and that Python can find the package:

```bash
cd /path/to/SupplyChainMCP
export PYTHONPATH=.
python server.py
```

Or use VS Code's built-in Python environment (which handles PYTHONPATH automatically).

---

### Issue: `FastMCP not available; using local MCPAdapter`

**Solution:**
The server is running with the fallback adapter (no FastMCP). To enable full MCP support:

```bash
pip install fastmcp
python server.py
```

This is optional for local development; the adapter is fully functional.

---

### Issue: `polars.exceptions.ShapeError: unable to append to a DataFrame`

**Solution:**
This occurs when forecast files have differing column sets. The current implementation auto-aligns schemas. If the error persists:

1. Check that forecast files follow a consistent structure
2. Inspect a problematic file for unexpected columns:
   ```bash
   python -c "import pandas as pd; df = pd.read_excel('Forecasts/file.xlsx'); print(df.columns)"
   ```
3. Verify no empty sheets or malformed headers

---

### Issue: `datetime parsing failed for column 'forecast_month'`

**Solution:**
The server uses flexible month parsing to support formats like `Jul-2026`, `2026-07`, `2026 P06`.
If your format is unsupported, edit `services/forecast_service.py`:

```python
# Add custom parsing in _try_parse_month()
try:
    dt = dateparser.parse(t, fuzzy=True, default=datetime(1900, 1, 1))
    if dt.year > 1900:
        return datetime(dt.year, dt.month, 1)
except Exception:
    return None
```

---

### Issue: Server crashes on large datasets (100k+ records)

**Solution:**
Increase available memory and adjust `max_workers`:

```yaml
# config.yaml
app:
  max_workers: 2  # Reduce to lower memory usage
```

Or run with environment settings:

```bash
export PYTHONUNBUFFERED=1
python -Xfrozen_modules=off server.py
```

---

### Issue: Incremental cache not working

**Solution:**
The cache is file-based (SQLite) in `cache/metadata.db`. To clear and rebuild:

```bash
rm -f cache/metadata.db
python server.py
```

---

## Development & Testing

### Running Tests

```bash
# All tests
pytest -q

# Verbose output
pytest -v

# Specific test file
pytest tests/test_root_cause_service.py -v

# Coverage report
pytest --cov=services --cov-report=html
```

### Test Files

- `tests/test_matching_service.py`: Product matching heuristics
- `tests/test_root_cause_service.py`: Root cause analysis pipeline
- `tests/test_acknowledgement_service.py`: JSON parsing & Pydantic validation

### Adding New Tests

```python
# tests/test_new_feature.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.your_service import YourService

def test_your_feature():
    svc = YourService()
    result = svc.your_method()
    assert result is not None
```

### Code Quality

- **Type Hints**: All functions use Python type hints (`-> ReturnType`)
- **Docstrings**: All modules, classes, and public methods have docstrings
- **Logging**: Use `logger.info()`, `logger.warning()`, `logger.exception()` (not `print`)
- **Error Handling**: Catch exceptions and log; fail gracefully with informative messages

---

## Extension Guide

### Adding a New Analytics Service

1. Create `services/my_analytics_service.py`:

```python
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

class MyAnalyticsService:
    def __init__(self, forecasts, acks):
        self.forecasts = forecasts
        self.acks = acks
    
    def my_analysis(self, product: str) -> dict:
        """Analyze my metric for a product."""
        # your implementation
        return {"result": "value"}
```

2. Register in `server.py`:

```python
from services.my_analytics_service import MyAnalyticsService

my_svc = MyAnalyticsService(forecasts_df, acks_df)

tools["my_analysis"] = lambda product: my_svc.my_analysis(product)
```

3. Add test in `tests/test_my_analytics_service.py`

4. Document in README (example usage, parameters, returns)

---

### Customizing Forecast Parsing

Edit `services/forecast_service.py`:

- `_KNOWN_HEADER_TOKENS`: Add known column names to improve header detection
- `_try_parse_month()`: Add custom date parsing logic
- `parse_file()`: Modify column normalization or filtering

---

### Adding New MCP Resources

MCP resources are read-only data exports. To add:

```python
# In server.py
resources = {
    "forecast_dataset": lambda: forecasts.to_pandas().to_json(),
    "ack_dataset": lambda: acks.to_json(),
}

# Register with MCP adapter
for name, func in resources.items():
    mcp.register_resource(name, func)
```

---

## License

SupplyChainMCP © 2026. All rights reserved.

---

## Support

For issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section
2. Review test examples in `tests/`
3. Check logs in `logs/supplychainmcp.log`
4. Inspect `config.yaml` for configuration issues

---

**Last Updated**: July 14, 2026


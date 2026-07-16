from __future__ import annotations
import logging
from pathlib import Path
from typing import Iterable, Optional, Dict
import pandas as pd
import polars as pl
from datetime import datetime
from dateutil import parser as dateparser
import os
import re

logger = logging.getLogger(__name__)


_KNOWN_HEADER_TOKENS = [
    "upc",
    "vendor",
    "vendor sku",
    "sku",
    "retail",
    "retail item",
    "description",
    "brand",
    "department",
    "forecast",
    "qty",
    "quantity",
    "month",
    "forecast month",
    "report date",
]


def _normalize_col_name(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


def _try_parse_month(token: str) -> Optional[datetime]:
    if token is None:
        return None
    t = str(token).strip()
    if not t:
        return None
    # Pandas uses names such as ``Unnamed: 32`` for empty, formatted Excel
    # columns.  Their trailing number must not be interpreted as a year.
    if _normalize_col_name(t).startswith("unnamed"):
        return None
    # common patterns: Jul-24, Jul 2024, 2024-07, 07/2024, 2024/07
    try:
        dt = pd.to_datetime(t, errors="coerce", dayfirst=False)
        if not pd.isna(dt):
            # normalize to start of month
            return datetime(dt.year, dt.month, 1)
    except Exception:
        pass

    try:
        # fallback to dateutil parser with fuzzy
        dt = dateparser.parse(t, fuzzy=True, default=datetime(1900, 1, 1))
        # require a year > 1900
        if dt.year > 1900:
            return datetime(dt.year, dt.month, 1)
    except Exception:
        return None

    return None


def _month_from_name_and_period(month_name: object, period: object) -> Optional[datetime]:
    """Return the calendar month named in a two-row forecast header.

    Ulta workbooks place period labels (``2026 P01``) in the row directly
    above the user-facing month names (``February``).  The period supplies a
    reliable year, while the month name supplies the actual calendar month.
    """
    month_text = str(month_name).strip()
    period_text = str(period).strip()
    if not month_text or not period_text:
        return None

    try:
        month_number = datetime.strptime(month_text[:3].title(), "%b").month
    except ValueError:
        return None

    match = re.search(r"\b(\d{4})\s*P\d{1,2}\b", period_text, flags=re.IGNORECASE)
    if not match:
        return None
    fiscal_year = int(match.group(1))
    # These reports use a February-to-January fiscal year: P01 is February
    # and P12 is January of the following calendar year.
    calendar_year = fiscal_year + (1 if month_number == 1 else 0)
    return datetime(calendar_year, month_number, 1)


def _source_snapshot_at(path: Path, mtime: float) -> datetime:
    """Return the report date embedded in a forecast filename, or its mtime."""
    match = re.search(r"(\d{4}-\d{2}-\d{2})(?=\.[^.]+$)", path.name)
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d")
    return datetime.fromtimestamp(mtime)


class ForecastService:
    """Discover and normalize forecast workbooks with robust header detection
    and incremental loading support.

    If a `cache_service` (SQLite-based) is provided the loader will skip
    files that have not changed since last processed (by mtime).
    """

    def __init__(self, forecasts_dir: str | Path, cache_service: Optional[object] = None):
        self.forecasts_dir = Path(forecasts_dir)
        self.cache = cache_service

    def discover_files(self) -> list[Path]:
        files = list(self.forecasts_dir.rglob("*.xlsx")) + list(self.forecasts_dir.rglob("*.xlsm"))
        files += list(self.forecasts_dir.rglob("*.csv"))
        logger.info("Discovered %d forecast files", len(files))
        return files

    def _detect_header_row(self, df: pd.DataFrame, max_rows: int = 20) -> int:
        # Scan top rows to find a candidate header row with at least two known tokens
        top_n = min(max_rows, len(df))
        for i in range(top_n):
            row = df.iloc[i].astype(str).fillna("")
            tokens = " ".join([_normalize_col_name(c) for c in row.values])
            count = sum(1 for t in _KNOWN_HEADER_TOKENS if t in tokens)
            if count >= 2:
                return i
        # fallback to 0
        return 0

    def parse_file(self, path: Path) -> pl.DataFrame:
        """Parse a single file. Returns empty DataFrame if nothing to process or skipped (incremental)."""
        # incremental skip
        try:
            mtime = path.stat().st_mtime
        except OSError:
            logger.exception("Cannot stat file: %s", path)
            return pl.DataFrame()

        cached = None
        if self.cache:
            cached = self.cache.get(str(path))
            if cached and cached.get("mtime") == mtime:
                logger.debug("Skipping unchanged forecast file %s", path)
                return pl.DataFrame()

        # read a few rows to detect header
        try:
            df_raw = pd.read_excel(path, sheet_name=0, engine="openpyxl", header=None, dtype=str, nrows=50)
        except Exception:
            # try CSV fallback
            try:
                df_raw = pd.read_csv(path, header=None, nrows=50, dtype=str)
            except Exception:
                logger.exception("Failed to read file: %s", path)
                return pl.DataFrame()

        header_row = self._detect_header_row(df_raw)

        # Read without a header so we can use the period row immediately above
        # the detected header row to map forecast columns to their displayed
        # calendar month names.
        try:
            if str(path).lower().endswith((".xlsx", ".xlsm")):
                sheet = pd.read_excel(path, sheet_name=0, engine="openpyxl", header=None, dtype=str)
            else:
                sheet = pd.read_csv(path, header=None, dtype=str)
        except Exception:
            logger.exception("Failed to read with detected header: %s (header=%s)", path, header_row)
            return pl.DataFrame()

        header = sheet.iloc[header_row].fillna("")
        period_row = sheet.iloc[header_row - 1].fillna("") if header_row else pd.Series("", index=sheet.columns)
        data = sheet.iloc[header_row + 1 :].copy()

        # A unique, readable column name is needed before melting.  Forecast
        # headers include the year to distinguish repeated months (for example
        # July 2026 and July 2027), while non-forecast headers retain their
        # source label.
        columns: list[str] = []
        header_months: Dict[str, datetime] = {}
        used_names: set[str] = set()
        for position, value in enumerate(header):
            month = _month_from_name_and_period(value, period_row.iloc[position])
            name = month.strftime("%B %Y") if month else str(value).strip()
            if not name or name.lower() == "nan":
                name = f"unnamed_{position}"
            base_name, suffix = name, 2
            while name in used_names:
                name = f"{base_name} ({suffix})"
                suffix += 1
            used_names.add(name)
            columns.append(name)
            if month:
                header_months[_normalize_col_name(name)] = month

        df = data
        df.columns = columns

        # normalize column names
        orig_cols = list(df.columns)
        norm_map: Dict[str, str] = {c: _normalize_col_name(c) for c in orig_cols}
        df.rename(columns=norm_map, inplace=True)

        # Use the Brand Partner's SKU as the common product key expected by
        # matching, filtering, and product-level analytics.
        if "brand partner sku#" in df.columns:
            df["vendor_sku"] = df["brand partner sku#"].astype("string").str.strip()
            df.loc[df["vendor_sku"].isin(["", "nan", "None"]), "vendor_sku"] = pd.NA

        if "ulta item description" in df.columns:
            df["product_description"] = df["ulta item description"]

            # Forecast workbooks include an "Overall Result" total row.  It
            # has no product SKU and would otherwise be added to the actual
            # item-level forecasts, overstating the total.
            non_product_rows = int(df["vendor_sku"].isna().sum())
            if non_product_rows:
                logger.info("Dropping %d non-product forecast summary rows from %s", non_product_rows, path)
                df = df[df["vendor_sku"].notna()].copy()

        # Prefer the explicit month names in the second header row.  Fall back
        # to conventional date-like column headers for other forecast layouts.
        month_cols: Dict[str, datetime] = dict(header_months)
        for c in df.columns:
            if c in month_cols:
                continue
            dt = _try_parse_month(c)
            if dt:
                month_cols[c] = dt

        # also check columns where header is like 'forecast Jul 2024' or similar
        if not month_cols:
            for c in df.columns:
                # split tokens and test each
                for tok in str(c).replace("_"," ").split():
                    dt = _try_parse_month(tok)
                    if dt:
                        month_cols[c] = dt
                        break

        if not month_cols:
            logger.warning("No monthly forecast columns detected in %s", path)
            return pl.DataFrame()

        id_cols = [c for c in df.columns if c not in month_cols]

        # melt to long format
        try:
            long = df.melt(id_vars=id_cols, value_vars=list(month_cols.keys()), var_name="forecast_month", value_name="forecast_qty")
        except Exception:
            logger.exception("Failed to melt forecast file: %s", path)
            return pl.DataFrame()

        # map forecast_month to normalized month date
        long["forecast_month_parsed"] = long["forecast_month"].apply(lambda x: month_cols.get(x, _try_parse_month(x)))
        long["forecast_month_parsed"] = pd.to_datetime(long["forecast_month_parsed"], errors="coerce")
        long["forecast_qty"] = pd.to_numeric(long["forecast_qty"], errors="coerce").fillna(0)

        # add source file and update cache
        long["source_file"] = str(path)
        long["_source_snapshot_at"] = _source_snapshot_at(path, mtime)

        if self.cache:
            self.cache.set(str(path), mtime, {"rows": int(len(long))})

        pl_df = pl.from_pandas(long)
        return pl_df

    def load_all(self, incremental: bool = True) -> pl.DataFrame:
        parts: list[pl.DataFrame] = []
        for p in self.discover_files():
            try:
                df = self.parse_file(p)
                if df.is_empty():
                    continue
                parts.append(df)
            except Exception:
                logger.exception("Failed to parse forecast: %s", p)
        if not parts:
            return pl.DataFrame()

        # Align columns across parts: ensure same column set and order
        all_cols: list[str] = []
        for df in parts:
            for c in df.columns:
                if c not in all_cols:
                    all_cols.append(c)

        # Determine a target dtype for each column by inspecting parts
        col_type_candidates: dict[str, set[str]] = {c: set() for c in all_cols}
        for df in parts:
            for c, dt in df.schema.items():
                col_type_candidates[c].add(str(dt))

        def pick_dtype(candidates: set[str]):
            # prefer string if present, then float, int, bool, datetime
            s = " ".join(candidates).lower()
            if "utf" in s or "str" in s or "string" in s:
                return pl.Utf8
            if "float" in s:
                return pl.Float64
            if "int" in s:
                return pl.Int64
            if "bool" in s:
                return pl.Boolean
            if "datetime" in s or "date" in s:
                return pl.Datetime
            # fallback to Utf8 to maximize compatibility
            return pl.Utf8

        target_schema: dict[str, pl.DataType] = {c: pick_dtype(col_type_candidates.get(c, set())) for c in all_cols}

        aligned: list[pl.DataFrame] = []
        for df in parts:
            # add missing columns with appropriate types
            missing = [c for c in all_cols if c not in df.columns]
            if missing:
                for c in missing:
                    df = df.with_columns(pl.lit(None).cast(target_schema[c]).alias(c))

            # cast existing columns to target types to avoid SchemaError
            for c in all_cols:
                if c in df.columns:
                    try:
                        df = df.with_columns(pl.col(c).cast(target_schema[c]).alias(c))
                    except Exception:
                        # best-effort: if cast fails, cast to Utf8
                        df = df.with_columns(pl.col(c).cast(pl.Utf8).alias(c))

            # reorder columns to a consistent ordering
            df = df.select(all_cols)
            aligned.append(df)

        result = pl.concat(aligned, how="vertical")

        # Coerce key columns to strict types for downstream analytics
        # Use safe casting with null fallback for unparseable values
        if "forecast_month_parsed" in result.columns:
            try:
                # forecast_month_parsed should already be datetime from parsing
                result = result.with_columns(
                    pl.col("forecast_month_parsed").cast(pl.Date, strict=False)
                )
            except Exception as e:
                logger.debug("Could not cast forecast_month_parsed to Date: %s", e)

        if "forecast_qty" in result.columns:
            try:
                result = result.with_columns(
                    pl.col("forecast_qty").cast(pl.Float64, strict=False)
                )
            except Exception as e:
                logger.debug("Could not cast forecast_qty to Float64: %s", e)

        # Each workbook is a snapshot.  When a later snapshot contains the
        # same product and month, it supersedes (rather than adds to) the
        # quantity in the earlier workbook.
        dedupe_keys = ["vendor_sku", "forecast_month_parsed"]
        if all(column in result.columns for column in dedupe_keys) and "_source_snapshot_at" in result.columns:
            identified = result.filter(
                pl.col("vendor_sku").is_not_null() & (pl.col("vendor_sku").cast(pl.Utf8).str.strip_chars() != "")
            )
            before = len(result)
            identified = identified.sort("_source_snapshot_at").unique(
                subset=dedupe_keys, keep="last", maintain_order=True
            )
            # Keep unidentified rows only for layouts that do not provide a
            # Brand Partner SKU column.  The standard Ulta layout removed its
            # non-product summary rows above.
            unidentified = result.filter(
                pl.col("vendor_sku").is_null() | (pl.col("vendor_sku").cast(pl.Utf8).str.strip_chars() == "")
            )
            result = pl.concat([identified, unidentified], how="vertical")
            logger.info("Replaced %d superseded forecast snapshot rows", before - len(result))

        if "_source_snapshot_at" in result.columns:
            result = result.drop("_source_snapshot_at")

        # forecast_month is a string; try to parse it first
        if "forecast_month" in result.columns:
            try:
                # attempt to parse common date formats: YYYY-MM, YYYY Pxx, etc.
                result = result.with_columns(
                    pl.col("forecast_month").str.strptime(pl.Date, format="%Y-%m", strict=False)
                    .alias("forecast_month_parsed_from_str")
                )
                # if that succeeded, use it; otherwise keep forecast_month as string
                if "forecast_month_parsed_from_str" in result.columns and result["forecast_month_parsed_from_str"].null_count() < len(result):
                    result = result.drop("forecast_month")
                    result = result.rename({"forecast_month_parsed_from_str": "forecast_month"})
            except Exception as e:
                logger.debug("Could not parse forecast_month column: %s", e)

        logger.info("Loaded %d forecast records across %d files", len(result), len(parts))
        return result


__all__ = ["ForecastService"]

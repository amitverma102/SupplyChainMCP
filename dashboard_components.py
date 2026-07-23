from __future__ import annotations
import base64
from io import BytesIO
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

try:
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
    ST_AGGRID_AVAILABLE = True
except ImportError:
    ST_AGGRID_AVAILABLE = False

try:
    from streamlit_option_menu import option_menu
    HAS_OPTION_MENU = True
except ImportError:
    HAS_OPTION_MENU = False


def load_app_style(theme: str = "dark") -> None:
    is_light = theme.lower() == "light"
    page_bg = "#f7f9fc" if is_light else "#09112b"
    text_color = "#1f2937" if is_light else "#e6edf7"
    card_bg = "rgba(255, 255, 255, 0.92)" if is_light else "rgba(255, 255, 255, 0.05)"
    border_color = "rgba(15, 23, 42, 0.12)" if is_light else "rgba(255, 255, 255, 0.1)"
    secondary_text = "#4b5563" if is_light else "#a6b8d9"
    explore_button_bg = "#0a84ff" if is_light else "#0d4b9f"
    st.markdown(
        f"""
        <style>
        .stApp {{
            background: {page_bg};
            color: {text_color};
        }}
        .kpi-card {{
            background: {card_bg};
            border: 1px solid {border_color};
            border-radius: 18px;
            padding: 18px 20px;
            margin-bottom: 16px;
            min-height: 130px;
        }}
        .kpi-card-title {{
            color: {secondary_text};
            font-size: 0.92rem;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }}
        .kpi-card-value {{
            font-size: 1.9rem;
            font-weight: 700;
            color: {text_color};
            margin-bottom: 6px;
        }}
        .kpi-card-delta {{
            color: #0d9488;
            font-size: 0.95rem;
        }}
        .kpi-card-footer {{
            margin-top: 12px;
            color: {secondary_text};
            font-size: 0.85rem;
        }}
        .section-header {{
            font-size: 1.25rem;
            font-weight: 700;
            color: {text_color};
            margin-top: 24px;
            margin-bottom: 12px;
        }}
        .section-subheader {{
            color: {secondary_text};
        }}
        .small-button {{
            border-radius: 10px;
            background-color: #0a84ff;
            color: white;
        }}
        /* KPI action buttons use keys such as kpi_0.  Keep their resting
           state consistent with the blue background previously shown only
           while hovering in the dark theme. */
        div[class*="st-key-kpi_"] button {{
            background-color: {explore_button_bg};
            border-color: {explore_button_bg};
            color: white;
        }}
        div[class*="st-key-kpi_"] button:hover {{
            background-color: {explore_button_bg};
            border-color: {explore_button_bg};
            color: white;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_menu(page: str, menu_items: list[str]) -> str:

    with st.sidebar:

        if HAS_OPTION_MENU:

            default_icons = [

                "speedometer2",

                "bar-chart-line",

                "receipt-cutoff",

                "scissors",

                "graph-up",

                "person-badge",

                "box-seam",

                "forecast",

                "clipboard-data",

                "shield-exclamation",

                "robot",

                "gear",

            ]

            icons = default_icons[:len(menu_items)]

            if len(icons) < len(menu_items):

                icons += ["dot"] * (len(menu_items) - len(icons))

            return option_menu(

                menu_title=None,

                options=menu_items,

                icons=icons,

                menu_icon="cast",

                default_index=(

                    menu_items.index(page)

                    if page in menu_items else 0

                ),

                styles={

                    "container": {

                        "padding": "0!important",

                        "background-color": "#091127",

                    },

                    "icon": {

                        "color": "#8eb8ff",

                        "font-size": "18px",

                    },

                    "nav-link": {

                        "font-size": "0.95rem",

                        "text-align": "left",

                        "margin": "0px 0px 4px 0px",

                        "color": "#c6d6f5",

                        "padding": "8px 12px",

                        "border-radius": "10px",

                    },

                    "nav-link-selected": {

                        "background-color": "#0d4b9f",

                        "color": "white",

                    },

                },

            )

        return st.radio(

            "Navigation",

            menu_items,

            index=(

                menu_items.index(page)

                if page in menu_items else 0

            ),

        )
def render_kpi_cards(metrics: list[dict], columns: int = 4) -> Optional[str]:
    cols = st.columns(columns)
    target_page: Optional[str] = None
    for idx, metric in enumerate(metrics):
        with cols[idx % columns]:
            st.markdown(
                f"""
                <div class='kpi-card'>
                    <div class='kpi-card-title'>{metric['label']}</div>
                    <div class='kpi-card-value'>{metric['value']}</div>
                    <div class='kpi-card-delta'>{metric.get('delta', '')}</div>
                    <div class='kpi-card-footer'>{metric.get('detail', '')}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if metric.get("action"):
                if st.button(metric["action"], key=f"kpi_{idx}"):
                    target_page = metric.get("target")
    return target_page


def prepare_calendar_data(df: pd.DataFrame, x: Optional[str] = None) -> pd.DataFrame:
    """Normalize calendar columns and chronologically order a chart's x-axis.

    Plotly treats string values such as ``April 2026`` as categories, which can
    result in alphabetical ordering.  Converting calendar-like columns to real
    dates (or numbers for years) gives both charts and AgGrid calendar sorting.
    """
    if df.empty:
        return df

    result = df.copy()
    candidates = [x] if x in result.columns else list(result.columns)
    sort_column: Optional[str] = None
    for column in candidates:
        name = str(column).lower().replace("_", " ")
        if not any(token in name for token in ("date", "month", "year", "period")):
            continue

        source = result[column]
        non_null_count = source.notna().sum()
        if non_null_count == 0:
            continue
        parsed = (
            pd.to_numeric(source, errors="coerce")
            if "year" in name and not any(token in name for token in ("date", "month", "period"))
            else pd.to_datetime(source, errors="coerce", format="mixed")
        )
        if parsed.notna().sum() < non_null_count * 0.8:
            continue
        result[column] = parsed
        if column == x:
            sort_column = column

    if sort_column:
        result = result.sort_values(sort_column, kind="stable")
    return result


def prepare_table_data(df: pd.DataFrame) -> pd.DataFrame:
    """Remove import artefacts and normalize product descriptions for display."""
    result = prepare_calendar_data(df)
    unnamed_columns = [
        column for column in result.columns if str(column).strip().lower().startswith("unnamed")
    ]
    result = result.drop(columns=unnamed_columns, errors="ignore")

    description_names = {
        "product_description",
        "product description",
        "description",
        "ulta item description",
    }
    description_columns = [
        column
        for column in result.columns
        if str(column).strip().lower().replace("_", " ") in description_names
    ]
    if description_columns:
        # Prefer the canonical description, but fill it from source-specific
        # fields when it is blank.  Only one description is shown in the UI.
        descriptions = (
            result[description_columns]
            .replace(r"^\s*$", pd.NA, regex=True)
            .bfill(axis=1)
            .iloc[:, 0]
        )
        result = result.drop(columns=description_columns)
        result["Product Description"] = descriptions

    if "vendor_sku" in result.columns and "Product Description" in result.columns:
        columns = list(result.columns)
        columns.remove("Product Description")
        vendor_sku_index = columns.index("vendor_sku") + 1
        columns.insert(vendor_sku_index, "Product Description")
        result = result[columns]
    return result


def render_aggrid_table(df: pd.DataFrame, height: int = 400, fit_columns: bool = True) -> None:
    df = prepare_table_data(df)

    if ST_AGGRID_AVAILABLE:
        options = GridOptionsBuilder.from_dataframe(df)
        options.configure_default_column(editable=False, groupable=True, filter=True, resizable=True)
        options.configure_selection(selection_mode="single", use_checkbox=False)
        options.configure_grid_options(domLayout="normal")
        if fit_columns:
            options.configure_column("", flex=1)
        AgGrid(
            df,
            height=height,
            gridOptions=options.build(),
            update_mode=GridUpdateMode.NO_UPDATE,
            allow_unsafe_jscode=True,
        )
    else:
        st.warning("Install `streamlit-aggrid` for a rich table experience. Falling back to Streamlit data frame.")
        st.dataframe(df)


def download_dataframe(df: pd.DataFrame, label: str = "Download CSV") -> None:
    csv_buffer = df.to_csv(index=False).encode("utf-8")
    st.download_button(label, csv_buffer, file_name=f"{label.replace(' ', '_').lower()}.csv", mime="text/csv")


def plot_line_chart(df: pd.DataFrame, x: str, y: str, color: Optional[str] = None, title: Optional[str] = None) -> None:
    if df.empty:
        st.info("No data available for this chart.")
        return
    fig = px.line(prepare_calendar_data(df, x=x), x=x, y=y, color=color, title=title, template="plotly_dark")
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch")


def plot_bar_chart(df: pd.DataFrame, x: str, y: str, color: Optional[str] = None, title: Optional[str] = None) -> None:
    if df.empty:
        st.info("No data available for this chart.")
        return
    fig = px.bar(prepare_calendar_data(df, x=x), x=x, y=y, color=color, title=title, template="plotly_dark")
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch")


def plot_gauge(value: float, title: str, subtitle: Optional[str] = None) -> None:
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number+delta",
            value=value * 100 if value <= 1 else value,
            number={"suffix": "%" if value <= 1 else ""},
            delta={"reference": 100 if value <= 1 else 0, "relative": False},
            gauge={
                "axis": {"range": [0, 100] if value <= 1 else [0, value * 1.5]},
                "bar": {"color": "#0dbd8b"},
                "steps": [
                    {"range": [0, 50], "color": "#962d3e"},
                    {"range": [50, 80], "color": "#f4b400"},
                    {"range": [80, 100], "color": "#0dbd8b"},
                ],
            },
            title={"text": title if not subtitle else f"{title}<br><span style='font-size:0.75em;color:#c0c9d9'>{subtitle}</span>"},
        )
    )
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor="rgba(0,0,0,0)", font_color="#ffffff")
    st.plotly_chart(fig, use_container_width=True)


def render_markdown_card(title: str, subtitle: str, value: str) -> None:
    st.markdown(
        f"""
        <div class='kpi-card'>
            <div class='kpi-card-title'>{title}</div>
            <div class='kpi-card-value'>{value}</div>
            <div class='kpi-card-footer'>{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

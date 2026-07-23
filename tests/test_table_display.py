import pandas as pd

from dashboard_components import prepare_table_data


def test_prepare_table_data_removes_unnamed_and_duplicate_description_columns() -> None:
    source = pd.DataFrame(
        {
            "vendor_sku": ["SKU-1"],
            "product_description": [""],
            "description": ["Primary description"],
            "ulta item description": ["Duplicate description"],
            "Unnamed: 12": ["spreadsheet artefact"],
            "unnamed_18": ["another artefact"],
        }
    )

    result = prepare_table_data(source)

    assert result.columns.tolist() == ["vendor_sku", "Product Description"]
    assert result.loc[0, "Product Description"] == "Primary description"

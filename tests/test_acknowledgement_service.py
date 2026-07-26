import sys
from pathlib import Path
import json
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.acknowledgement_service import AcknowledgementService
from services.cache_service import CacheService


def test_parse_edi_header_dates(tmp_path):
    path = tmp_path / "ack.json"
    path.write_text(json.dumps({
        "Header": {"OrderHeader": {
            "PurchaseOrderNumber": "PO-1",
            "PurchaseOrderDate": "2026-01-05",
            "AcknowledgementDate": "2026-01-07",
            "Vendor": "Supplier X",
        }},
        "LineItem": [{
            "OrderLine": {"VendorPartNumber": "SKU-1", "OrderQty": 1},
            "LineItemAcknowledgement": [{"ItemScheduleQty": 1, "ItemScheduleDate": "2026-01-12"}],
        }],
    }))

    row = AcknowledgementService(tmp_path).parse_file(path).iloc[0]

    assert row["po_date"] == "2026-01-05"
    assert row["ack_date"] == "2026-01-07"


def test_parse_acknowledgement_json():
    # Create a temporary JSON file with test ack data
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        test_data = {
            "header": {
                "vendor": "Supplier X",
                "customer": "Walmart",
                "po_number": "PO-12345",
            },
            "lines": [
                {
                    "vendor_sku": "SKU-001",
                    "buyer_part_number": "BUYER-001",
                    "upc": "123456789",
                    "description": "Widget",
                    "ordered_quantity": 100,
                    "confirmed_quantity": 95,
                    "price": 10.50,
                    "status_code": "A",
                    "delivery_date": "2026-07-20",
                },
                {
                    "vendorSku": "SKU-002",
                    "buyerPartNumber": "BUYER-002",
                    "gtin": "987654321",
                    "description": "Gadget",
                    "orderedQty": 50,
                    "confirmedQty": 50,
                    "price": 20.00,
                    "status": "A",
                },
            ],
        }
        json.dump(test_data, f)
        temp_path = f.name

    try:
        # Test without cache
        svc = AcknowledgementService(Path(temp_path).parent)
        df = svc.parse_file(Path(temp_path))
        assert not df.empty
        assert len(df) == 2
        assert df.iloc[0]["vendor"] == "Supplier X"
        assert df.iloc[0]["ordered_qty"] == 100.0
        assert df.iloc[1]["confirmed_qty"] == 50.0

        # Test with cache (verify cache records file mtime)
        with tempfile.TemporaryDirectory() as cache_dir:
            cache = CacheService(Path(cache_dir) / "test.db")
            svc_cached = AcknowledgementService(Path(temp_path).parent, cache_service=cache)
            df1 = svc_cached.parse_file(Path(temp_path))
            assert len(df1) == 2
            # Verify cache was updated
            cached_info = cache.get(str(Path(temp_path)))
            assert cached_info is not None
            assert cached_info.get("rows") == 2
            cache.close()
    finally:
        Path(temp_path).unlink()

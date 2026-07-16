import sys
from pathlib import Path

# Ensure project root is on sys.path so tests can import local packages
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.matching_service import MatchingService


def test_match_exact_and_fuzzy():
    svc = MatchingService()
    candidate = {"vendor_sku": "ABC-123", "description": "Blue widget size L"}
    targets = [
        {"vendor_sku": "ABC-123", "description": "Blue widget large"},
        {"vendor_sku": "XYZ-999", "description": "Red widget"},
    ]
    match, score = svc.match(candidate, targets)
    assert match is not None
    assert score >= 98

from __future__ import annotations
from rapidfuzz import fuzz
from typing import Optional, Tuple


class MatchingService:
    """Product matching engine using prioritized keys and fuzzy matching."""

    def __init__(self):
        pass

    def score_description(self, a: str | None, b: str | None) -> float:
        if not a or not b:
            return 0.0
        return fuzz.token_set_ratio(a, b)

    def match(self, candidate: dict, targets: Iterable[dict]) -> Tuple[Optional[dict], float]:
        """Attempt to match a candidate product to targets.

        Priority:
        1. Exact vendor_sku
        2. Exact buyer_part_number
        3. Exact UPC/GTIN
        4. Fuzzy description
        Returns best match and confidence 0-100.
        """
        best = None
        best_score = 0.0
        for t in targets:
            score = 0.0
            # strict matches
            if candidate.get("vendor_sku") and candidate.get("vendor_sku") == t.get("vendor_sku"):
                score = 100.0
            elif candidate.get("buyer_part_number") and candidate.get("buyer_part_number") == t.get("buyer_part_number"):
                score = 98.0
            elif candidate.get("upc") and candidate.get("upc") == t.get("upc"):
                score = 99.0
            else:
                score = self.score_description(candidate.get("description"), t.get("description"))

            if score > best_score:
                best_score = score
                best = t

        return best, best_score


__all__ = ["MatchingService"]

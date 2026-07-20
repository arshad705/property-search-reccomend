from typing import Literal, Optional

from pydantic import BaseModel


class ValuationRequest(BaseModel):
    town: str
    flat_type: str
    # Not used in the median computation (comparison is by town + flat_type);
    # optional so non-HDB listings (which can lack a floor area, e.g. landed)
    # still get an honest insufficient_data verdict instead of a 422.
    floor_area_sqm: Optional[float] = None
    asking_price: int
    # Optional: "low", "mid", or "high" (matches the "Floor Level" values
    # 99.co reports per listing). Plain str rather than a strict Literal since
    # 99.co's exact vocabulary isn't fully confirmed — unrecognized values are
    # ignored rather than rejected (see _matches_floor_level).
    floor_level: Optional[str] = None


class ValuationResponse(BaseModel):
    median_transacted_price: int
    comparable_transactions: int
    # "insufficient_data": zero comparable transactions were found at all —
    # distinct from a low but nonzero count, which is still a real (if
    # low-confidence) comparison. Confirmed live: without this, zero
    # comparables silently produced a fabricated "fairly_priced, 0% premium"
    # verdict (median defaulted to the asking price itself), which looks
    # exactly like a real, confident match despite having zero actual basis.
    valuation_verdict: Literal["fairly_priced", "overpriced", "underpriced", "insufficient_data"]
    premium_pct: float
    lookback_years: int
    floor_level_matched: bool

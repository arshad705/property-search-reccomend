from typing import Literal, Optional

from pydantic import BaseModel


class ListingSearchRequest(BaseModel):
    # HDB flat types ("2-room" ... "5-room", "executive") plus whole property
    # categories: "condo", "executive-condo", "landed". One field, broadened
    # vocabulary — deliberately NOT a separate property_type field, so the
    # agents' natural-language hand-off has one less value to garble.
    flat_type: str
    town: str
    max_price: int
    min_floor_area_sqm: Optional[float] = None
    # Optional buyer preference ("low"/"mid"/"high"). 99.co's /search-property
    # has no server-side floor filter — this is applied client-side against
    # each candidate's /listing-details-by-url floor_level, see listing_service.py.
    floor_level: Optional[str] = None
    # Bedroom-count filter for condo/executive-condo/landed searches (e.g. a
    # "3-bedroom condo"). Ignored for HDB flat types, whose bedroom count is
    # already implied by the flat_type itself.
    bedrooms: Optional[int] = None


class Coordinates(BaseModel):
    lat: float
    lng: float


class Listing(BaseModel):
    listing_id: str
    address: str
    flat_type: str
    asking_price: int
    # Always present for HDB listings (confirmed live). Nullable only for the
    # non-HDB categories (landed listings sometimes report land area instead
    # of floor area) — which never reach valuation anyway (HDB-only data).
    floor_area_sqm: Optional[float] = None
    storey_range: Optional[str] = None  # not available from 99.co's API
    town: str
    coordinates: Coordinates
    nearest_mrt_name: Optional[str] = None
    nearest_mrt_distance_m: Optional[int] = None
    listing_url: Optional[str] = None
    # From 99.co's /listing-details-by-url "Floor Level" field (e.g. "Mid"),
    # lowercased. Feed this straight into checkValuation's floor_level param
    # for a floor-aware valuation of this specific listing.
    floor_level: Optional[str] = None


class ListingSearchResponse(BaseModel):
    listings: list[Listing]
    source: Literal["cache", "live", "fixture"]
    retrieved_at: str

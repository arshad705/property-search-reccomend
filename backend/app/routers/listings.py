from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.listing import ListingSearchRequest, ListingSearchResponse
from app.services import event_bus
from app.services.listing_service import ListingSourceUnavailableError, search_listings

router = APIRouter()


@router.post(
    "/tools/listings",
    response_model=ListingSearchResponse,
    operation_id="searchListings",
    description="Search live HDB resale listings by flat type, town, max price, and optional minimum floor area.",
)
def search_listings_endpoint(
    request: ListingSearchRequest, db: Session = Depends(get_db)
) -> ListingSearchResponse:
    min_area_note = f" (min {request.min_floor_area_sqm:.0f} sqm)" if request.min_floor_area_sqm else ""
    event_bus.publish(
        "listings",
        "start",
        f"Searching {request.flat_type} flats in {request.town} under ${request.max_price:,}...{min_area_note}",
    )
    try:
        result = search_listings(db, request)
    except ListingSourceUnavailableError as exc:
        # Confirmed live: this used to surface as a generic, undiagnosable
        # 500 (an unhandled httpx.HTTPStatusError from a 429 quota-exhausted
        # response) — the agent then had no way to distinguish "the listings
        # source is genuinely down" from "no listings matched," and either
        # hallucinated a false "no results" or gave a vague apology. A clear
        # 503 with the real reason lets that be reported honestly instead.
        event_bus.publish("listings", "done", f"Listings source unavailable: {exc}")
        raise HTTPException(status_code=503, detail=f"Listings source temporarily unavailable: {exc}") from exc
    event_bus.publish(
        "listings", "done", f"Found {len(result.listings)} matching listing(s) ({result.source})"
    )
    return result

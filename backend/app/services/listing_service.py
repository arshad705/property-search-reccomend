import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ApiCache
from app.schemas.listing import Listing, ListingSearchRequest, ListingSearchResponse

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"
CACHE_TTL = timedelta(hours=1)
# Town name -> 99.co location id/type is effectively static (a real-world HDB
# town boundary doesn't change), unlike listing search results — cached far
# longer to cut a real, confirmed source of wasted RapidAPI quota: every
# distinct search previously re-resolved the same town via /autocomplete even
# though the mapping never changes between queries.
TOWN_LOCATION_CACHE_TTL = timedelta(days=30)
SQFT_TO_SQM = 0.09290304

# 99.co's /search-property has no HDB "flat_type" query param — only a
# generic `rooms` bedroom-count range filter, used here purely as a coarse
# server-side narrowing pass (saves quota by shrinking the raw page) — never
# trusted alone to determine the actual flat_type; precise confirmation
# happens per-listing in _flat_type_matches via subCategory/title. This range
# is intentionally TIGHT, not wide — confirmed live that widening it (e.g.
# "4-room": "2,4" instead of "3,3") backfires: a real "4-room flat in
# Clementi" search returned only 1 genuine hdb_4r match in the raw
# page_size=10 sample, because the extra "beds=2" net pulled in far more
# numerous real 3-room listings that drowned out the true 4-room ones in the
# fixed-size page. Reverting to "3,3" (beds=3 is what real hdb_4r listings
# consistently carry) raised that to 8 genuine matches out of 10. A tight
# range that matches the common case densely, backed by _flat_type_matches
# to reject the rare stray non-match, beats a wide range that dilutes the
# sample with mostly-irrelevant results.
_ROOM_RANGE_BY_FLAT_TYPE = {
    "2-room": "1,1",
    "3-room": "2,2",
    "4-room": "3,3",
    "5-room": "3,4",
    "executive": "4,5",
}

# Non-HDB property categories accepted in the same flat_type field, mapped to
# 99.co's /search-property main_category param (confirmed values: hdb, condo,
# landed — see the project spec's API table). Executive condos are legally a
# condo hybrid and live under 99.co's condo category; they're narrowed
# client-side in _flat_type_matches. NOTE: the exact subCategory vocabulary
# for condo/EC/landed listings has NOT been confirmed live yet (unlike the
# hdb_Nr values) — the EC filter below matches subCategory or title text
# defensively; verify against real listings when quota use is approved.
_MAIN_CATEGORY_BY_PROPERTY_TYPE = {
    "condo": "condo",
    "executive-condo": "condo",
    "landed": "landed",
}


def _is_hdb_request(flat_type: str) -> bool:
    return flat_type.lower() not in _MAIN_CATEGORY_BY_PROPERTY_TYPE

# The real, authoritative signal for HDB flat_type, confirmed live: every
# /search-property listing carries a `subCategory` field (e.g. "hdb_4r") that
# lines up exactly with its own `title` text (e.g. "4 Room (4A) HDB for Sale")
# — unlike `beds`, this never disagreed with the title across dozens of
# inspected listings. "2-room" -> "hdb_2r" follows the same confirmed
# "hdb_Nr" pattern as 3/4/5-room but wasn't directly observed live (no 2-room
# resale listings turned up in any sampled search — they're rare on the
# resale market); worth reconfirming if a real one is ever seen.
_HDB_SUBCATEGORY_BY_FLAT_TYPE = {
    "2-room": "hdb_2r",
    "3-room": "hdb_3r",
    "4-room": "hdb_4r",
    "5-room": "hdb_5r",
    "executive": "hdb_executive",
}

# Some listings carry subCategory "unknown" instead of a real hdb_Nr value
# (confirmed live — e.g. some Toa Payoh 1-room/3-room listings). Even then,
# the listing's own title still states the room count in plain text (e.g.
# "3 Room HDB for Sale in ..."), so this regex is the fallback signal before
# giving up and falling through to the floor-area heuristic below.
_TITLE_ROOM_COUNT_RE = re.compile(r"^(\d+)\s*Room", re.IGNORECASE)
_ROOM_COUNT_BY_FLAT_TYPE = {
    "2-room": "2",
    "3-room": "3",
    "4-room": "4",
    "5-room": "5",
}

# Last-resort fallback only, for the rare listing where neither subCategory
# nor title yields a confirmed room count (e.g. a bare "HDB for Sale" title).
# Approximate floor-area floors — official HDB sizes vary by block design
# era — set low enough to keep legitimate smaller variants but high enough
# to reject the clearly-mismatched sizes seen live before this fix (e.g. a
# 91 sqm listing masquerading as "5-room").
_MIN_FLOOR_AREA_SQM_BY_FLAT_TYPE = {
    "2-room": 35.0,
    "3-room": 55.0,
    "4-room": 80.0,
    "5-room": 100.0,
    "executive": 125.0,
}


def _flat_type_matches(raw: dict, request: ListingSearchRequest) -> bool:
    flat_type = request.flat_type.lower()

    if flat_type == "condo":
        # main_category=condo scoping is server-side; accept everything it
        # returns (including ECs — a buyer asking generically for a "condo"
        # shouldn't have executive condos hidden from them).
        return True
    if flat_type == "landed":
        # Likewise scoped server-side via main_category=landed.
        return True
    if flat_type == "executive-condo":
        # ECs live under main_category=condo, narrowed client-side. The exact
        # subCategory value hasn't been confirmed live — match subCategory or
        # the listing's own title text defensively.
        subcategory = (raw.get("subCategory") or "").lower()
        title = (raw.get("title") or "").lower()
        return "executive" in subcategory or "executive condo" in title or " ec " in f" {title} "

    expected_subcategory = _HDB_SUBCATEGORY_BY_FLAT_TYPE.get(flat_type)
    subcategory = raw.get("subCategory")
    if expected_subcategory and subcategory and subcategory != "unknown":
        return subcategory == expected_subcategory

    title_match = _TITLE_ROOM_COUNT_RE.match(raw.get("title") or "")
    expected_room_count = _ROOM_COUNT_BY_FLAT_TYPE.get(flat_type)
    if title_match and expected_room_count:
        return title_match.group(1) == expected_room_count

    # Neither subCategory nor title confirmed a room count — fall back to
    # the floor-area heuristic rather than rejecting outright.
    floor_area_sqm = round((raw.get("floorAreaSqft") or 0) * SQFT_TO_SQM, 1)
    min_area = _MIN_FLOOR_AREA_SQM_BY_FLAT_TYPE.get(flat_type)
    return min_area is None or floor_area_sqm >= min_area


def _cache_key(request: ListingSearchRequest) -> str:
    raw = json.dumps(request.model_dump(), sort_keys=True)
    return f"listings:{hashlib.sha256(raw.encode()).hexdigest()}"


def _read_cache(db: Session, key: str) -> dict | None:
    row = db.query(ApiCache).filter(ApiCache.cache_key == key).first()
    if row and row.expires_at > datetime.utcnow():
        return row.response_json
    return None


def _write_cache(db: Session, key: str, payload: dict, ttl: timedelta = CACHE_TTL) -> None:
    row = db.query(ApiCache).filter(ApiCache.cache_key == key).first()
    expires_at = datetime.utcnow() + ttl
    if row:
        row.response_json = payload
        row.expires_at = expires_at
    else:
        db.add(ApiCache(cache_key=key, response_json=payload, expires_at=expires_at))
    db.commit()


def _filter_fixture_listings(listings: list[dict], request: ListingSearchRequest) -> list[dict]:
    matches = [
        listing
        for listing in listings
        if listing["town"].lower() == request.town.lower()
        and listing["flat_type"].lower() == request.flat_type.lower()
        and listing["asking_price"] <= request.max_price
        and (
            request.min_floor_area_sqm is None
            or listing["floor_area_sqm"] >= request.min_floor_area_sqm
        )
    ]
    if request.floor_level:
        tier_matches = [listing for listing in matches if listing.get("floor_level") == request.floor_level.lower()]
        if tier_matches:
            return tier_matches
    return matches


def _fetch_from_fixture(request: ListingSearchRequest) -> list[dict]:
    data = json.loads((FIXTURES_DIR / "listings_sample.json").read_text())
    return _filter_fixture_listings(data["listings"], request)


def _map_99co_listing(raw: dict, request: ListingSearchRequest) -> dict:
    # floorAreaSqft is always present on HDB listings (confirmed live) but can
    # be null on landed listings, which report land area instead.
    floor_area_sqft = raw.get("floorAreaSqft")
    floor_area_sqm = round(floor_area_sqft * SQFT_TO_SQM, 1) if floor_area_sqft else None
    nearest_mrt = raw.get("nearestMrt") or {}
    return {
        "listing_id": raw["id"],
        "address": raw["address"],
        "flat_type": request.flat_type,
        "asking_price": raw["price"],
        "floor_area_sqm": floor_area_sqm,
        "storey_range": None,
        "town": raw.get("neighbourhood") or raw.get("region") or request.town,
        "coordinates": {"lat": raw["lat"], "lng": raw["lng"]},
        "nearest_mrt_name": nearest_mrt.get("name"),
        "nearest_mrt_distance_m": nearest_mrt.get("distance"),
    }


def _matches_request(listing: dict, request: ListingSearchRequest) -> bool:
    # No town check here — /search-property's own query_ids/query_type scoping
    # (see _resolve_town_location) handles that server-side now. An earlier
    # client-side substring check on neighbourhood/address wrongly excluded
    # real matches: e.g. searching "Clementi" legitimately returns listings in
    # "Sunset Way" or "West Coast Drive" (both part of Clementi's HDB town per
    # 99.co's own scoping), neither of which contains the word "Clementi".
    # Flat_type itself is confirmed earlier, in _fetch_live, via
    # _flat_type_matches against the raw 99.co listing (subCategory/title) —
    # this only checks the buyer's explicit numeric filters.
    if listing["asking_price"] > request.max_price:
        return False
    if (
        request.min_floor_area_sqm is not None
        and listing["floor_area_sqm"] is not None
        and listing["floor_area_sqm"] < request.min_floor_area_sqm
    ):
        return False
    return True


class ListingSourceUnavailableError(RuntimeError):
    """The upstream 99.co API (via RapidAPI) rejected a request outright —
    e.g. monthly quota exhausted (429) or an auth failure — as opposed to a
    town simply not resolving to a known location. Distinct from returning
    None so callers don't confuse "no listings for this town" with "the data
    source itself is down," which used to surface as a generic, undiagnosable
    500 rather than an honest, specific error."""


def _town_cache_key(town: str) -> str:
    return f"town_location:{town.strip().lower()}"


def _resolve_town_location(client: httpx.Client, headers: dict, town: str, db: Session) -> tuple[str, str] | None:
    # /search-property's query_ids param needs a location id — passing a town
    # name directly doesn't scope anything. Confirmed live: an unscoped
    # "singapore"-wide search's "relevance" sort is non-deterministic between
    # identical calls (the same query returned Clementi listings on one call
    # and none on the next), so real matches could randomly vanish. Resolving
    # via /autocomplete's "HDB Town" group and passing query_type=hdb_town
    # explicitly gives a deterministic, properly-scoped result set instead.
    cache_key = _town_cache_key(town)
    cached = _read_cache(db, cache_key)
    if cached is not None:
        return (cached["id"], cached["type"]) if cached["id"] else None

    try:
        response = client.get(
            f"https://{settings.rapidapi_host}/autocomplete",
            headers=headers,
            params={"query": town},
        )
        response.raise_for_status()
        sections = response.json().get("data", {}).get("sections", [])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403, 429):
            raise ListingSourceUnavailableError(
                f"99.co API rejected the request ({exc.response.status_code}): {exc.response.text}"
            ) from exc
        return None
    except httpx.HTTPError:
        return None

    resolved = None
    for section in sections:
        if section.get("group") == "HDB Town" and section.get("locations"):
            location = section["locations"][0]
            resolved = (location["id"], location["type"])
            break

    # Cache the resolution (including "not found", as {"id": None, "type":
    # None}) so a town that doesn't resolve isn't re-queried every time either.
    _write_cache(
        db,
        cache_key,
        {"id": resolved[0] if resolved else None, "type": resolved[1] if resolved else None},
        ttl=TOWN_LOCATION_CACHE_TTL,
    )
    return resolved


def _fetch_listing_details(client: httpx.Client, headers: dict, listing_id: str) -> dict:
    # /search-property and /listing-details have no URL/slug field at all
    # (confirmed by inspecting both responses directly). /listing-details-by-url
    # is confirmed live to only care about the ID at the end of whatever URL
    # you pass it — any slug text works — and its response includes a real,
    # official `shareUrl`. So we pass a throwaway URL just to carry the real
    # ID, then use the shareUrl 99.co itself returns rather than guessing one.
    # Its `details` object also has a "Floor Level" field (e.g. "Mid") that
    # /search-property doesn't expose — grabbed here for free since we're
    # already making this call for the shareUrl.
    placeholder_url = f"https://www.99.co/singapore/sale/property/listing-{listing_id}"
    try:
        response = client.get(
            f"https://{settings.rapidapi_host}/listing-details-by-url",
            headers=headers,
            params={"url": placeholder_url},
        )
        response.raise_for_status()
        data = response.json().get("data", {})
    except httpx.HTTPError:
        return {"listing_url": None, "floor_level": None}

    floor_level = data.get("details", {}).get("Floor Level")
    return {
        "listing_url": data.get("shareUrl"),
        "floor_level": floor_level.lower() if floor_level else None,
    }


def _select_price_diverse(candidates: list[dict], count: int) -> list[dict]:
    # Confirmed live: 99.co's /search-property result order is not
    # price-sorted, so naively taking the first `count` matches (in whatever
    # order the API happens to return, or the order floor-tier matches were
    # found in) silently clustered results toward whichever end of the price
    # range appeared earliest — e.g. a real "$1.2M budget" search returned
    # only ~$480k-$669k listings, even though genuine matches near $1.1M-1.15M
    # existed in the very same raw sample but were never reached. Spreads the
    # selection evenly across the sorted price range instead, so the
    # shortlist actually represents the buyer's stated budget.
    if len(candidates) <= count:
        return candidates
    sorted_candidates = sorted(candidates, key=lambda c: c["asking_price"])
    if count <= 1:
        return [sorted_candidates[0]]
    last_index = len(sorted_candidates) - 1
    seen_indices: set[int] = set()
    selected = []
    for i in range(count):
        index = round(i * last_index / (count - 1))
        if index not in seen_indices:
            seen_indices.add(index)
            selected.append(sorted_candidates[index])
    return selected


# Final result count returned to listing_agent, unchanged from before this
# floor-level fix — still the safe cap under Orchestrate's 30-step recursion
# limit (see below).
RESULT_COUNT = 3

# Always oversample the raw page rather than requesting exactly RESULT_COUNT,
# for two independent reasons confirmed live:
# 1. 99.co's /search-property has no floor-level filter at all (only
#    rooms/price/page_size/query_ids are supported) — floor_level is only
#    knowable per-listing via the extra /listing-details-by-url call, so a
#    stated floor preference needs a wider pool to find RESULT_COUNT
#    tier-matches in.
# 2. _flat_type_matches now rejects any raw listing whose real subCategory
#    (or title/floor-area fallback) doesn't confirm the requested flat_type —
#    necessary (see _HDB_SUBCATEGORY_BY_FLAT_TYPE above), but it shrinks the
#    candidate pool. With the old page_size=3 default this was confirmed to
#    sometimes reject all 3 raw results outright, silently returning zero
#    listings for a perfectly valid query. Oversampling uniformly (whether or
#    not a floor preference is stated) keeps enough true-match candidates in
#    play after type-confirmation.
SAMPLE_SIZE = 10

# Cap on how many candidates get a /listing-details-by-url call (the real
# quota cost driver — one RapidAPI call per candidate) when a floor
# preference is stated. Confirmed live this was previously uncapped up to
# SAMPLE_SIZE (10) per search, since finding a price-diverse tier-matching
# set requires knowing every candidate's floor_level before selecting — a
# real, confirmed contributor to exhausting the RapidAPI free-tier monthly
# quota. 6 (2x RESULT_COUNT) keeps most of the price-diversity benefit
# (spreads across up to 6 known candidates instead of just the first 3
# found) while meaningfully cutting the worst case from 10 to 6 detail calls.
MAX_DETAIL_FETCHES_FOR_FLOOR_FILTER = 2 * RESULT_COUNT


def _fetch_live(request: ListingSearchRequest, db: Session) -> list[dict]:
    headers = {
        "X-RapidAPI-Key": settings.rapidapi_key,
        "X-RapidAPI-Host": settings.rapidapi_host,
    }
    flat_type = request.flat_type.lower()
    params = {
        "listing_type": "sale",
        "main_category": _MAIN_CATEGORY_BY_PROPERTY_TYPE.get(flat_type, "hdb"),
        "price_max": request.max_price,
        # SAMPLE_SIZE, not RESULT_COUNT — see SAMPLE_SIZE's comment. Detail
        # calls (each listing's shareUrl + floor_level, one RapidAPI call
        # apiece) are bounded separately below (RESULT_COUNT or
        # MAX_DETAIL_FETCHES_FOR_FLOOR_FILTER), so this doesn't multiply
        # quota cost by itself; it only widens the pool _matches_request and
        # the floor-tier logic get to pick from.
        "page_size": SAMPLE_SIZE,
    }
    if _is_hdb_request(flat_type):
        # Tight range matching the common case densely — see the map's comment.
        params["rooms"] = _ROOM_RANGE_BY_FLAT_TYPE.get(flat_type, "1,5")
    elif request.bedrooms:
        # For condos/EC/landed, 99.co's beds field IS the actual bedroom
        # count, so an exact range is correct when the buyer stated one.
        params["rooms"] = f"{request.bedrooms},{request.bedrooms}"

    with httpx.Client(timeout=15.0) as client:
        resolved = _resolve_town_location(client, headers, request.town, db)
        if resolved:
            query_ids, query_type = resolved
            params["query_ids"] = query_ids
            params["query_type"] = query_type
        else:
            # Fall back to an unscoped island-wide search if the town couldn't
            # be resolved — better to return some results than none, though
            # this inherits the non-determinism noted above.
            params["query_ids"] = "singapore"

        try:
            response = client.get(f"https://{settings.rapidapi_host}/search-property", headers=headers, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403, 429):
                raise ListingSourceUnavailableError(
                    f"99.co API rejected the request ({exc.response.status_code}): {exc.response.text}"
                ) from exc
            raise
        data = response.json()

        raw_listings = data.get("data", {}).get("results", {}).get("listings", [])
        type_confirmed = [raw for raw in raw_listings if _flat_type_matches(raw, request)]
        mapped = [_map_99co_listing(raw, request) for raw in type_confirmed]
        candidates = [listing for listing in mapped if _matches_request(listing, request)]

        if not request.floor_level:
            # Price-diverse selection needs only asking_price, already known
            # pre-detail-fetch — so still only RESULT_COUNT detail calls
            # (one per selected listing), same quota cost as before.
            selected = _select_price_diverse(candidates, RESULT_COUNT)
            for listing in selected:
                listing.update(_fetch_listing_details(client, headers, listing["listing_id"]))
            return selected

        # Floor preference stated: floor_level is only knowable via the detail
        # call, so — to pick a price-diverse set of tier-matches rather than
        # just the first RESULT_COUNT found in raw API order — fetch details
        # for candidates up to MAX_DETAIL_FETCHES_FOR_FLOOR_FILTER (not the
        # full SAMPLE_SIZE — see that constant's comment) before selecting.
        wanted_tier = request.floor_level.lower()
        for listing in candidates[:MAX_DETAIL_FETCHES_FOR_FLOOR_FILTER]:
            listing.update(_fetch_listing_details(client, headers, listing["listing_id"]))
        inspected = candidates[:MAX_DETAIL_FETCHES_FOR_FLOOR_FILTER]

        tier_matches = [listing for listing in inspected if listing.get("floor_level") == wanted_tier]
        other_candidates = [listing for listing in inspected if listing.get("floor_level") != wanted_tier]

        if len(tier_matches) >= RESULT_COUNT:
            return _select_price_diverse(tier_matches, RESULT_COUNT)
        return tier_matches + _select_price_diverse(other_candidates, RESULT_COUNT - len(tier_matches))


def search_listings(db: Session, request: ListingSearchRequest) -> ListingSearchResponse:
    key = _cache_key(request)
    cached = _read_cache(db, key)
    if cached is not None:
        return ListingSearchResponse(**cached, source="cache")

    if settings.use_fixtures or not settings.rapidapi_key:
        listings = _fetch_from_fixture(request)
        retrieved_at = datetime.utcnow().isoformat() + "Z"
        return ListingSearchResponse(
            listings=[Listing(**listing) for listing in listings],
            source="fixture",
            retrieved_at=retrieved_at,
        )

    listings = _fetch_live(request, db)
    retrieved_at = datetime.utcnow().isoformat() + "Z"
    _write_cache(
        db,
        key,
        {"listings": listings, "retrieved_at": retrieved_at},
    )
    return ListingSearchResponse(
        listings=[Listing(**listing) for listing in listings],
        source="live",
        retrieved_at=retrieved_at,
    )

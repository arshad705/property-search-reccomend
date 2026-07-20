import json
import statistics
from datetime import datetime
from pathlib import Path

import httpx

from app.config import settings
from app.schemas.valuation import ValuationRequest, ValuationResponse

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"
DATA_GOV_SG_URL = "https://data.gov.sg/api/action/datastore_search"

# Verdict is based on how far the asking price sits from the median
# transacted price for comparable flats.
DISCREPANCY_THRESHOLD_PCT = 5.0

# Confirmed live that data.gov.sg's datastore_search returns records in a
# fixed (apparently insertion/id) order by default, NOT sorted by recency —
# for a common town+flat_type combo, an unsorted limit=100 query returned
# only 2017-01 to 2017-07 data out of 1,977 total matches since 2017. That
# silently produced a median 41% lower than a recency-sorted equivalent
# query. Fixed by requesting `sort=month desc` and additionally filtering to
# the last LOOKBACK_YEARS client-side (in case a rare town+flat_type combo
# doesn't have 100 transactions within the window — better to report fewer,
# genuinely-recent comparables than pad the count with stale ones).
LOOKBACK_YEARS = 5

# 99.co reports a listing's own "Floor Level" as Low/Mid/High (see
# listing_service.py's _fetch_listing_details). data.gov.sg has no equivalent
# categorical field, only a 3-storey `storey_range` band (e.g. "10 TO 12") —
# this is an approximate, building-height-agnostic mapping from that band's
# starting storey to the same Low/Mid/High vocabulary, not a precise or
# officially-defined cutoff.
FLOOR_LEVEL_STOREY_START = {
    "low": (1, 6),
    "mid": (7, 15),
    "high": (16, 999),
}
MIN_COMPARABLES_FOR_FLOOR_FILTER = 5

# data.gov.sg's `town` field always uses one of these 26 official HDB planning
# area names. Listing sources (e.g. 99.co's `neighbourhood`, like "Bishan
# East") are finer-grained real-estate marketing areas that don't exactly
# match — so we normalize by finding which official town name is contained
# in whatever town string we're given, rather than requiring an exact match.
_HDB_TOWNS = [
    "ANG MO KIO", "BEDOK", "BISHAN", "BUKIT BATOK", "BUKIT MERAH",
    "BUKIT PANJANG", "BUKIT TIMAH", "CENTRAL AREA", "CHOA CHU KANG",
    "CLEMENTI", "GEYLANG", "HOUGANG", "JURONG EAST", "JURONG WEST",
    "KALLANG/WHAMPOA", "MARINE PARADE", "PASIR RIS", "PUNGGOL",
    "QUEENSTOWN", "SEMBAWANG", "SENGKANG", "SERANGOON", "TAMPINES",
    "TOA PAYOH", "WOODLANDS", "YISHUN",
]


# data.gov.sg's resale transaction dataset covers HDB flats ONLY — there is
# no comparable public dataset for condos, executive condos, or landed homes
# in this app. Requests for those categories short-circuit to an honest
# insufficient_data verdict without any API call.
_HDB_FLAT_TYPES = {"1 ROOM", "2 ROOM", "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE", "MULTI-GENERATION"}


def _normalize_flat_type(flat_type: str) -> str:
    return flat_type.replace("-", " ").strip().upper()


def _normalize_town(town: str) -> str:
    town_upper = town.upper()
    for hdb_town in _HDB_TOWNS:
        if hdb_town in town_upper:
            return hdb_town
    return town_upper


def _cutoff_month() -> str:
    now = datetime.utcnow()
    return f"{now.year - LOOKBACK_YEARS:04d}-{now.month:02d}"


def _storey_range_start(storey_range: str) -> int | None:
    try:
        return int(storey_range.strip().split(" TO ")[0])
    except (ValueError, IndexError, AttributeError):
        return None


def _matches_floor_level(storey_range: str, floor_level: str) -> bool:
    bounds = FLOOR_LEVEL_STOREY_START.get(floor_level.lower())
    start = _storey_range_start(storey_range)
    if bounds is None or start is None:
        return False
    low, high = bounds
    return low <= start <= high


def _fetch_from_fixture(request: ValuationRequest) -> list[dict]:
    data = json.loads((FIXTURES_DIR / "valuation_sample.json").read_text())
    town = _normalize_town(request.town)
    flat_type = _normalize_flat_type(request.flat_type)
    return [
        txn
        for txn in data["transactions"]
        if txn["town"].upper() == town
        and txn["flat_type"].upper() == flat_type
    ]


def _fetch_live(request: ValuationRequest) -> list[dict]:
    town = _normalize_town(request.town)
    flat_type = _normalize_flat_type(request.flat_type)
    params = {
        "resource_id": settings.data_gov_sg_resource_id,
        "q": json.dumps({"town": town, "flat_type": flat_type}),
        "sort": "month desc",
        "limit": 100,
    }
    with httpx.Client(timeout=10.0) as client:
        response = client.get(DATA_GOV_SG_URL, params=params)
        response.raise_for_status()
        data = response.json()

    records = data.get("result", {}).get("records", [])
    cutoff = _cutoff_month()
    return [
        txn
        for txn in records
        if txn.get("town", "").upper() == town
        and txn.get("flat_type", "").upper() == flat_type
        and txn.get("month", "") >= cutoff
    ]


def check_valuation(request: ValuationRequest) -> ValuationResponse:
    if _normalize_flat_type(request.flat_type) not in _HDB_FLAT_TYPES:
        # Condo / executive condo / landed — no transaction data source, so
        # no comparison is possible. Report that honestly (and skip the
        # pointless data.gov.sg round-trip).
        return ValuationResponse(
            median_transacted_price=request.asking_price,
            comparable_transactions=0,
            valuation_verdict="insufficient_data",
            premium_pct=0.0,
            lookback_years=LOOKBACK_YEARS,
            floor_level_matched=False,
        )

    if settings.use_fixtures:
        transactions = _fetch_from_fixture(request)
    else:
        transactions = _fetch_live(request)

    floor_level_matched = False
    if request.floor_level:
        floor_matched = [
            txn for txn in transactions if _matches_floor_level(txn.get("storey_range", ""), request.floor_level)
        ]
        if len(floor_matched) >= MIN_COMPARABLES_FOR_FLOOR_FILTER:
            transactions = floor_matched
            floor_level_matched = True
        # Otherwise too few floor-specific comparables to trust a median from
        # them alone — fall back to the full (already town+flat_type+recency
        # filtered) set rather than report a number from 1-2 data points.

    prices = [int(float(txn["resale_price"])) for txn in transactions]

    if not prices:
        # Confirmed live: defaulting median to the asking price here (as this
        # used to do) makes premium_pct compute to exactly 0% every time,
        # producing a fabricated "fairly_priced" verdict indistinguishable
        # from a real, confident comparison — even though zero transactions
        # means there is no comparison at all. Report that honestly instead.
        return ValuationResponse(
            median_transacted_price=request.asking_price,
            comparable_transactions=0,
            valuation_verdict="insufficient_data",
            premium_pct=0.0,
            lookback_years=LOOKBACK_YEARS,
            floor_level_matched=floor_level_matched,
        )

    median_price = int(statistics.median(prices))
    premium_pct = round((request.asking_price - median_price) / median_price * 100, 1)

    if premium_pct > DISCREPANCY_THRESHOLD_PCT:
        verdict = "overpriced"
    elif premium_pct < -DISCREPANCY_THRESHOLD_PCT:
        verdict = "underpriced"
    else:
        verdict = "fairly_priced"

    return ValuationResponse(
        median_transacted_price=median_price,
        comparable_transactions=len(prices),
        valuation_verdict=verdict,
        premium_pct=premium_pct,
        lookback_years=LOOKBACK_YEARS,
        floor_level_matched=floor_level_matched,
    )

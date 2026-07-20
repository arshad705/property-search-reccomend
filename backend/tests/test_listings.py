import httpx
import pytest

from app.schemas.listing import ListingSearchRequest
from app.services.listing_service import (
    ListingSourceUnavailableError,
    _flat_type_matches,
    _resolve_town_location,
    _select_price_diverse,
)


class _FakeClient:
    """Records every .get() call and returns canned httpx.Response objects,
    keyed by a substring of the requested URL — enough to unit-test
    _resolve_town_location's caching and error behavior without a real
    network call."""

    def __init__(self, responses: dict[str, httpx.Response]):
        self._responses = responses
        self.call_count = 0

    def get(self, url, headers=None, params=None):
        self.call_count += 1
        for key, response in self._responses.items():
            if key in url:
                return response
        raise AssertionError(f"Unexpected URL in test: {url}")


def _autocomplete_response(town_id="htbishan", town_type="hdb_town"):
    request = httpx.Request("GET", "https://example.com/autocomplete")
    return httpx.Response(
        200,
        request=request,
        json={"data": {"sections": [{"group": "HDB Town", "locations": [{"id": town_id, "type": town_type}]}]}},
    )


def _error_response(status_code):
    request = httpx.Request("GET", "https://example.com/autocomplete")
    return httpx.Response(status_code, request=request, text="quota exceeded")


def test_resolve_town_location_caches_across_calls(db_session):
    fake_client = _FakeClient({"autocomplete": _autocomplete_response()})

    first = _resolve_town_location(fake_client, {}, "Bishan-Test-Cache", db_session)
    second = _resolve_town_location(fake_client, {}, "Bishan-Test-Cache", db_session)

    assert first == ("htbishan", "hdb_town")
    assert second == ("htbishan", "hdb_town")
    assert fake_client.call_count == 1  # second call served from cache, no real HTTP request


def test_resolve_town_location_raises_on_quota_exhaustion(db_session):
    fake_client = _FakeClient({"autocomplete": _error_response(429)})

    with pytest.raises(ListingSourceUnavailableError):
        _resolve_town_location(fake_client, {}, "Some-Unresolved-Town", db_session)


def test_select_price_diverse_spreads_across_the_price_range():
    # Confirmed live: 99.co's result order isn't price-sorted, so naively
    # taking the first N matches clustered a real "$1.2M budget" search
    # toward only the cheapest ~$480k-$669k listings, even though genuine
    # matches near $1.15M existed in the same raw sample.
    candidates = [
        {"listing_id": "a", "asking_price": 480_000},
        {"listing_id": "b", "asking_price": 1_070_000},
        {"listing_id": "c", "asking_price": 599_999},
        {"listing_id": "d", "asking_price": 668_888},
        {"listing_id": "e", "asking_price": 1_128_000},
    ]
    selected = _select_price_diverse(candidates, 3)
    prices = sorted(c["asking_price"] for c in selected)
    assert prices == [480_000, 668_888, 1_128_000]


def test_select_price_diverse_returns_all_when_fewer_than_count():
    candidates = [{"listing_id": "a", "asking_price": 500_000}, {"listing_id": "b", "asking_price": 600_000}]
    assert _select_price_diverse(candidates, 3) == candidates


def test_flat_type_matches_uses_subcategory_as_authoritative_signal():
    # 99.co's `beds` field is confirmed (live) to be an unreliable HDB
    # flat_type proxy — beds=3 alone spans 80-125 sqm listings — but its
    # own `subCategory` field is authoritative and always agrees with title.
    request = ListingSearchRequest(flat_type="5-room", town="Clementi", max_price=1_100_000)
    mismatched = {"subCategory": "hdb_4r", "title": "4 Room (4S) HDB for Sale", "floorAreaSqft": 980}
    genuine = {"subCategory": "hdb_5r", "title": "5 Room (5I) HDB for Sale", "floorAreaSqft": 1302}

    assert _flat_type_matches(mismatched, request) is False
    assert _flat_type_matches(genuine, request) is True


def test_flat_type_matches_falls_back_to_title_when_subcategory_unknown():
    request = ListingSearchRequest(flat_type="3-room", town="Toa Payoh", max_price=600_000)
    matching_title = {"subCategory": "unknown", "title": "3 Room HDB for Sale in 138C Lorong 1A", "floorAreaSqft": 1184}
    mismatched_title = {"subCategory": "unknown", "title": "1 Room HDB for Sale in 104 Potong Pasir", "floorAreaSqft": 796}

    assert _flat_type_matches(matching_title, request) is True
    assert _flat_type_matches(mismatched_title, request) is False


def test_flat_type_matches_accepts_all_condos_for_condo_request():
    request = ListingSearchRequest(flat_type="condo", town="Bishan", max_price=2_000_000)
    condo = {"subCategory": "condo", "title": "3 Bedroom Condo for Sale in Sky Habitat", "floorAreaSqft": 1200}
    ec = {"subCategory": "executive_condo", "title": "3 Bedroom Executive Condo for Sale", "floorAreaSqft": 1100}

    assert _flat_type_matches(condo, request) is True
    assert _flat_type_matches(ec, request) is True  # buyer asking "condo" shouldn't have ECs hidden


def test_flat_type_matches_narrows_executive_condo_via_subcategory_or_title():
    request = ListingSearchRequest(flat_type="executive-condo", town="Bishan", max_price=2_000_000)
    ec_by_subcategory = {"subCategory": "executive_condo", "title": "3 Bedroom for Sale", "floorAreaSqft": 1100}
    ec_by_title = {"subCategory": "unknown", "title": "3 Bedroom Executive Condo for Sale", "floorAreaSqft": 1100}
    plain_condo = {"subCategory": "condo", "title": "3 Bedroom Condo for Sale", "floorAreaSqft": 1200}

    assert _flat_type_matches(ec_by_subcategory, request) is True
    assert _flat_type_matches(ec_by_title, request) is True
    assert _flat_type_matches(plain_condo, request) is False


def test_search_listings_returns_condo_fixture_results(client):
    response = client.post(
        "/tools/listings",
        json={"flat_type": "condo", "town": "Bishan", "max_price": 2000000},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["listings"]) == 1
    assert body["listings"][0]["flat_type"] == "condo"
    assert body["listings"][0]["asking_price"] == 1680000


def test_search_listings_returns_executive_condo_fixture_results(client):
    response = client.post(
        "/tools/listings",
        json={"flat_type": "executive-condo", "town": "Bishan", "max_price": 2000000},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["listings"]) == 1
    assert body["listings"][0]["flat_type"] == "executive-condo"
    assert body["listings"][0]["asking_price"] == 1450000


def test_flat_type_matches_falls_back_to_floor_area_when_unconfirmed():
    # Neither subCategory nor a parseable title room-count is available —
    # last-resort floor-area heuristic decides.
    request = ListingSearchRequest(flat_type="5-room", town="Clementi", max_price=1_100_000)
    undersized = {"subCategory": "unknown", "title": "HDB for Sale", "floorAreaSqft": 980}
    genuine = {"subCategory": "unknown", "title": "HDB for Sale", "floorAreaSqft": 1302}

    assert _flat_type_matches(undersized, request) is False
    assert _flat_type_matches(genuine, request) is True


def test_search_listings_returns_matching_fixture_results(client):
    response = client.post(
        "/tools/listings",
        json={
            "flat_type": "4-room",
            "town": "Bishan",
            "max_price": 850000,
            "min_floor_area_sqm": None,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "fixture"
    assert len(body["listings"]) == 3
    assert all(listing["asking_price"] <= 850000 for listing in body["listings"])


def test_search_listings_filters_by_max_price(client):
    response = client.post(
        "/tools/listings",
        json={
            "flat_type": "4-room",
            "town": "Bishan",
            "max_price": 800000,
            "min_floor_area_sqm": None,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["listings"]) == 1
    assert body["listings"][0]["asking_price"] == 798000


def test_search_listings_no_match_returns_empty_list(client):
    response = client.post(
        "/tools/listings",
        json={
            "flat_type": "5-room",
            "town": "Bishan",
            "max_price": 850000,
            "min_floor_area_sqm": None,
        },
    )

    assert response.status_code == 200
    assert response.json()["listings"] == []


def test_search_listings_filters_by_floor_level(client):
    response = client.post(
        "/tools/listings",
        json={
            "flat_type": "4-room",
            "town": "Bishan",
            "max_price": 850000,
            "floor_level": "mid",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["listings"]) == 1
    assert body["listings"][0]["asking_price"] == 820000
    assert body["listings"][0]["floor_level"] == "mid"


def test_search_listings_floor_level_falls_back_when_tier_unavailable(client):
    # Only the 798000 "low" listing is under this price cap — no "mid" exists
    # within budget, so the fallback should still return it rather than an
    # empty list, consistent with valuation_service's honest fallback pattern.
    response = client.post(
        "/tools/listings",
        json={
            "flat_type": "4-room",
            "town": "Bishan",
            "max_price": 800000,
            "floor_level": "mid",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["listings"]) == 1
    assert body["listings"][0]["asking_price"] == 798000
    assert body["listings"][0]["floor_level"] == "low"

import json
import math
from pathlib import Path

import httpx

from app.config import settings
from app.schemas.geospatial import Amenity, Coordinates, GeospatialRequest, GeospatialResponse

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
NEARBY_SEARCH_URL = "https://places.googleapis.com/v1/places:searchNearby"

# Google Places (New) has no Singapore-specific "MRT station" or "hawker
# centre" type — these are the closest matches in its global taxonomy.
# "subway_station" (not "train_station", which matched SMRT's corporate
# office instead of an actual station — confirmed empirically) correctly
# returns real MRT stations by name (e.g. "Bishan", "Braddell"). "transit_station"
# is too broad and pulls in bus stops. "food_court" also catches non-hawker
# mall food courts, a known imprecision.
#
# The 2026-07 additions (convenience_store through synagogue) are all
# documented Places API (New) Table A types, mapped 1:1 — but not yet
# verified against live Singapore data the way subway_station was; check
# result quality on first real use. There is no generic queryable
# "place_of_worship" type in Table A — buyers asking generically should be
# routed to the specific type(s) matching their request (mosque, church,
# temple, synagogue).
AMENITY_TYPE_TO_GOOGLE_TYPE = {
    "mrt": "subway_station",
    "school": "school",
    "hawker_centre": "food_court",
    "convenience_store": "convenience_store",
    "shopping_mall": "shopping_mall",
    "mosque": "mosque",
    "church": "church",
    "temple": "hindu_temple",
    "synagogue": "synagogue",
}


def haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    earth_radius_m = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(earth_radius_m * c)


def _summarize(amenities: list[Amenity]) -> str:
    if not amenities:
        return "No amenities found within the requested radius."

    counts: dict[str, int] = {}
    for amenity in amenities:
        counts[amenity.type] = counts.get(amenity.type, 0) + 1

    parts = [f"{count} {amenity_type.replace('_', ' ')}(s)" for amenity_type, count in counts.items()]
    return ", ".join(parts) + " nearby."


def _fetch_from_fixture(request: GeospatialRequest) -> GeospatialResponse:
    data = json.loads((FIXTURES_DIR / "geospatial_sample.json").read_text())
    amenities = [
        Amenity(**amenity)
        for amenity in data["amenities"]
        if amenity["type"] in request.amenity_types and amenity["distance_m"] <= request.radius_m
    ]
    return GeospatialResponse(
        coordinates=Coordinates(**data["coordinates"]),
        amenities=amenities,
        amenity_summary=_summarize(amenities),
    )


def _geocode(client: httpx.Client, address: str) -> Coordinates:
    response = client.get(GEOCODE_URL, params={"address": address, "key": settings.google_maps_api_key})
    response.raise_for_status()
    results = response.json().get("results", [])
    if not results:
        raise ValueError(f"Google Geocoding API could not geocode address: {address}")
    location = results[0]["geometry"]["location"]
    return Coordinates(lat=location["lat"], lng=location["lng"])


def _search_nearby(client: httpx.Client, origin: Coordinates, google_type: str, radius_m: int) -> list[dict]:
    response = client.post(
        NEARBY_SEARCH_URL,
        headers={
            "X-Goog-Api-Key": settings.google_maps_api_key,
            # Basic-tier fields only — keeps this in the cheaper/more generous
            # free-quota SKU rather than the Pro tier (see project spec).
            "X-Goog-FieldMask": "places.displayName,places.location,places.types",
        },
        json={
            "includedTypes": [google_type],
            "maxResultCount": 20,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": origin.lat, "longitude": origin.lng},
                    "radius": radius_m,
                }
            },
        },
    )
    response.raise_for_status()
    return response.json().get("places", [])


def _fetch_live(request: GeospatialRequest) -> GeospatialResponse:
    with httpx.Client(timeout=15.0) as client:
        origin = _geocode(client, request.address)

        amenities: list[Amenity] = []
        for amenity_type in request.amenity_types:
            google_type = AMENITY_TYPE_TO_GOOGLE_TYPE.get(amenity_type)
            if not google_type:
                continue
            for place in _search_nearby(client, origin, google_type, request.radius_m):
                location = place["location"]
                distance_m = haversine_distance_m(
                    origin.lat, origin.lng, location["latitude"], location["longitude"]
                )
                if distance_m <= request.radius_m:
                    amenities.append(
                        Amenity(
                            name=place["displayName"]["text"],
                            type=amenity_type,
                            distance_m=distance_m,
                        )
                    )

    amenities.sort(key=lambda a: a.distance_m)
    return GeospatialResponse(
        coordinates=origin,
        amenities=amenities,
        amenity_summary=_summarize(amenities),
    )


def lookup_amenities(request: GeospatialRequest) -> GeospatialResponse:
    if settings.use_fixtures or not settings.google_maps_api_key:
        return _fetch_from_fixture(request)
    return _fetch_live(request)

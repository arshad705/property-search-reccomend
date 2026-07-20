def test_lookup_amenities_filters_by_type_and_radius(client):
    response = client.post(
        "/tools/geospatial",
        json={
            "address": "123 Bishan Street 12",
            "amenity_types": ["mrt", "hawker_centre"],
            "radius_m": 500,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["coordinates"] == {"lat": 1.3536, "lng": 103.8486}
    names = [amenity["name"] for amenity in body["amenities"]]
    assert names == ["Bishan MRT"]
    assert "1 mrt(s)" in body["amenity_summary"]


def test_lookup_amenities_excludes_types_not_requested(client):
    response = client.post(
        "/tools/geospatial",
        json={
            "address": "123 Bishan Street 12",
            "amenity_types": ["school"],
            "radius_m": 1000,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["amenities"]) == 1
    assert body["amenities"][0]["type"] == "school"


def test_lookup_amenities_supports_new_amenity_types(client):
    response = client.post(
        "/tools/geospatial",
        json={
            "address": "123 Bishan Street 12",
            "amenity_types": ["convenience_store", "shopping_mall", "mosque", "church", "temple"],
            "radius_m": 1000,
        },
    )

    assert response.status_code == 200
    body = response.json()
    types_found = {amenity["type"] for amenity in body["amenities"]}
    assert types_found == {"convenience_store", "shopping_mall", "mosque", "church", "temple"}
    names = [amenity["name"] for amenity in body["amenities"]]
    assert "7-Eleven Bishan St 13" in names
    assert "Junction 8" in names
    assert "Masjid An-Naeem" in names

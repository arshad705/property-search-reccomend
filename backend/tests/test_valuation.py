def test_check_valuation_fairly_priced(client):
    response = client.post(
        "/tools/valuation",
        json={
            "town": "Bishan",
            "flat_type": "4-room",
            "floor_area_sqm": 93,
            "asking_price": 820000,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["comparable_transactions"] == 12
    assert body["valuation_verdict"] == "fairly_priced"


def test_check_valuation_overpriced(client):
    response = client.post(
        "/tools/valuation",
        json={
            "town": "Bishan",
            "flat_type": "4-room",
            "floor_area_sqm": 93,
            "asking_price": 900000,
        },
    )

    assert response.status_code == 200
    assert response.json()["valuation_verdict"] == "overpriced"


def test_check_valuation_underpriced(client):
    response = client.post(
        "/tools/valuation",
        json={
            "town": "Bishan",
            "flat_type": "4-room",
            "floor_area_sqm": 93,
            "asking_price": 700000,
        },
    )

    assert response.status_code == 200
    assert response.json()["valuation_verdict"] == "underpriced"


def test_check_valuation_reports_lookback_years(client):
    response = client.post(
        "/tools/valuation",
        json={"town": "Bishan", "flat_type": "4-room", "floor_area_sqm": 93, "asking_price": 820000},
    )

    assert response.json()["lookback_years"] == 5


def test_check_valuation_with_enough_floor_matches_filters_to_that_tier(client):
    response = client.post(
        "/tools/valuation",
        json={
            "town": "Bishan",
            "flat_type": "4-room",
            "floor_area_sqm": 93,
            "asking_price": 820000,
            "floor_level": "low",
        },
    )

    body = response.json()
    assert body["floor_level_matched"] is True
    # Only the 6 low-floor (storeys 1-6) fixture transactions should be used.
    assert body["comparable_transactions"] == 6
    assert body["median_transacted_price"] == 786500


def test_check_valuation_falls_back_when_floor_level_unrecognized(client):
    response = client.post(
        "/tools/valuation",
        json={
            "town": "Bishan",
            "flat_type": "4-room",
            "floor_area_sqm": 93,
            "asking_price": 820000,
            "floor_level": "penthouse",
        },
    )

    body = response.json()
    assert body["floor_level_matched"] is False
    assert body["comparable_transactions"] == 12


def test_check_valuation_returns_insufficient_data_for_non_hdb_types(client):
    # data.gov.sg only has HDB resale transactions — a condo/EC/landed
    # valuation must be honestly unanswerable, never a fake 0% "fair" verdict.
    for flat_type in ["condo", "executive-condo", "landed"]:
        response = client.post(
            "/tools/valuation",
            json={"town": "Bishan", "flat_type": flat_type, "asking_price": 1_500_000},
        )

        assert response.status_code == 200, flat_type
        body = response.json()
        assert body["valuation_verdict"] == "insufficient_data", flat_type
        assert body["comparable_transactions"] == 0, flat_type


def test_check_valuation_reports_insufficient_data_with_zero_comparables(client):
    # Confirmed live: passing a neighbourhood name (e.g. "Marymount") instead
    # of the official HDB town ("Bishan") finds zero real transactions —
    # this used to silently default median to the asking price itself,
    # fabricating a "fairly_priced, 0% premium" verdict from no data at all.
    response = client.post(
        "/tools/valuation",
        json={
            "town": "Marymount",
            "flat_type": "4-room",
            "floor_area_sqm": 93,
            "asking_price": 820000,
        },
    )

    body = response.json()
    assert body["comparable_transactions"] == 0
    assert body["valuation_verdict"] == "insufficient_data"

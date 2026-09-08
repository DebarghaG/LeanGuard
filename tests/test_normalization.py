from decimal import localcontext

import pytest
from leanguard.tau import normalize, scaled


@pytest.mark.parametrize("precision", [2, 28, 50])
@pytest.mark.parametrize(
    "value,factor,expected",
    [(123.45, 100, 12345), (10**40 + 1, 100, (10**40 + 1) * 100), (-1.25, 1000, -1250)],
)
def test_scaled_is_exact_independent_of_decimal_context(precision, value, factor, expected):
    with localcontext() as context:
        context.prec = precision
        assert scaled(value, factor) == expected


@pytest.mark.parametrize(
    "value", [0.001, "1.000000000000000000000000000001", float("nan"), float("inf"), float("-inf")]
)
def test_scaled_rejects_nonrepresentable_quantities(value):
    with pytest.raises(ValueError, match="exactly representable"):
        scaled(value, 100)


def test_schedule_normalization_handles_overnight_and_partial_observations():
    from leanguard.tau import epoch

    flight = {
        "scheduled_departure_time_est": "23:00:00",
        "scheduled_arrival_time_est": "01:00:00+1",
        "dates": {"2024-02-29": {"status": "available"}},
    }
    result = normalize(flight)["dates"]["2024-02-29"]
    assert result["departure_epoch"] == epoch("2024-02-29T23:00:00")
    assert result["arrival_epoch"] == epoch("2024-03-01T01:00:00")
    partial = {"dates": {"2024-02-29": result}}
    normalized = normalize(partial)["dates"]["2024-02-29"]
    assert "departure_epoch" not in normalized and "arrival_epoch" not in normalized


def test_itinerary_times_use_known_delay_and_actual_arrival():
    from leanguard.tau import epoch

    flight = {
        "scheduled_departure_time_est": "09:00:00",
        "scheduled_arrival_time_est": "10:00:00",
        "dates": {
            "2024-05-20": {
                "status": "delayed",
                "estimated_departure_time_est": "2024-05-20T12:00:00",
                "estimated_arrival_time_est": "2024-05-20T13:00:00",
            }
        },
    }
    times = normalize(flight)["dates"]["2024-05-20"]
    assert times["departure_epoch"] == epoch("2024-05-20T12:00:00")
    assert times["arrival_epoch"] == epoch("2024-05-20T13:00:00")
    flight["dates"]["2024-05-20"].update(
        status="landed",
        actual_departure_time_est="2024-05-20T12:15:00",
        actual_arrival_time_est="2024-05-20T13:15:00",
    )
    times = normalize(flight)["dates"]["2024-05-20"]
    assert times["arrival_epoch"] == epoch("2024-05-20T13:15:00")


@pytest.mark.parametrize(
    "day,clock",
    [
        ("2024-02-30", "12:00:00"),
        ("2024-05-20", "25:00:00"),
        ("2024-05-20", "12:00:00Z"),
        ("2024-05-20", "12:00:00-05:00"),
        ("2024-05-20", "12:00:00+bad"),
    ],
)
def test_schedule_normalization_rejects_malformed_times(day, clock):
    from leanguard.tau import scheduled_epoch

    with pytest.raises(ValueError):
        scheduled_epoch(day, clock)


def test_exact_unit_conversion():
    assert normalize({"price": 12.34, "gb_amount": 1.5}) == {
        "price": 1234,
        "gb_amount": 1.5,
        "gb_amount_milli": 1500,
    }


def test_plain_date_values_are_json_data():
    import json
    from datetime import UTC, date, datetime

    from leanguard.tau import jsonable

    value = jsonable(
        {
            "date": date(2025, 2, 28),
            "nested": [datetime(2025, 2, 25, 12, 8, tzinfo=UTC)],
        }
    )
    assert json.loads(json.dumps(value)) == {
        "date": "2025-02-28",
        "nested": ["2025-02-25T12:08:00+00:00"],
    }

"""Forward-only temporal semantics for source timestamps and analysis dates."""

from shared import hevy_client
from shared.timezone import analysis_date_for_timestamp, temporal_metadata


def _workout(start, end=None):
    return {
        "id": "temporal-w1",
        "title": "Evening Lift",
        "start_time": start,
        "end_time": end or start,
        "exercises": [],
    }


def test_hevy_before_pacific_utc_day_rollover_stays_same_day():
    row = hevy_client.workout_to_row(
        _workout("2026-07-01T23:30:00Z", "2026-07-02T00:15:00Z")
    )
    assert row["date"] == "2026-07-01"


def test_hevy_evening_after_utc_midnight_does_not_become_tomorrow_pdt():
    # 00:30 UTC on July 2 is 17:30 PDT on July 1.
    row = hevy_client.workout_to_row(
        _workout("2026-07-02T00:30:00Z", "2026-07-02T01:30:00Z")
    )
    assert row["date"] == "2026-07-01"
    assert row["analysis_date"] == "2026-07-01"
    assert row["source_date"] == "2026-07-02"


def test_hevy_evening_after_utc_midnight_does_not_become_tomorrow_pst():
    # 00:30 UTC on January 2 is 16:30 PST on January 1.
    row = hevy_client.workout_to_row(
        _workout("2026-01-02T00:30:00Z", "2026-01-02T01:30:00Z")
    )
    assert row["date"] == "2026-01-01"


def test_home_timezone_derivation_handles_dst_spring_transition():
    # The local clock jumps from 01:59 PST to 03:00 PDT; both instants remain
    # on the same Pacific analysis date.
    assert analysis_date_for_timestamp("2026-03-08T09:30:00Z") == "2026-03-08"
    assert analysis_date_for_timestamp("2026-03-08T10:30:00Z") == "2026-03-08"


def test_home_timezone_derivation_handles_dst_fall_transition():
    # 01:30 occurs twice (PDT, then PST), but both absolute instants belong to
    # the same Pacific calendar day.
    assert analysis_date_for_timestamp("2026-11-01T08:30:00Z") == "2026-11-01"
    assert analysis_date_for_timestamp("2026-11-01T09:30:00Z") == "2026-11-01"


def test_utc_midnight_crossing_is_converted_before_day_attribution():
    assert analysis_date_for_timestamp("2026-07-01T23:59:59Z") == "2026-07-01"
    assert analysis_date_for_timestamp("2026-07-02T00:00:01Z") == "2026-07-01"


def test_trustworthy_source_offset_can_define_event_local_day():
    metadata = temporal_metadata(
        "2026-07-02T00:30:00+05:30",
        source_timezone_trusted=True,
    )
    assert metadata["analysis_date"] == "2026-07-02"
    assert metadata["source_utc_offset"] == "+05:30"
    assert metadata["analysis_utc_offset"] == "+05:30"
    assert metadata["date_derivation"] == "source_offset"


def test_naive_or_missing_timestamp_does_not_invent_an_absolute_instant():
    naive = temporal_metadata("2026-07-02 00:30:00")
    assert naive["source_date"] == "2026-07-02"
    assert "analysis_date" not in naive
    assert "analysis_timezone" not in naive

    fallback = temporal_metadata(
        "2026-07-02 00:30:00",
        allow_naive_source_date=True,
    )
    assert fallback["analysis_date"] == "2026-07-02"
    assert fallback["date_derivation"] == "source_date_fallback"
    assert "analysis_timezone" not in fallback

    assert hevy_client.workout_to_row(_workout("2026-07-02 00:30:00")) is None
    assert hevy_client.workout_to_row(_workout(None)) is None


def test_hevy_preserves_source_timestamps_and_adds_analysis_metadata():
    start = "2026-07-02T00:30:00+00:00"
    end = "2026-07-02T01:45:00+00:00"
    row = hevy_client.workout_to_row(_workout(start, end))

    assert row["start_time"] == start
    assert row["end_time"] == end
    assert row["source_start_time"] == start
    assert row["source_end_time"] == end
    assert row["source_date"] == "2026-07-02"
    assert row["source_utc_offset"] == "+00:00"
    assert row["analysis_date"] == "2026-07-01"
    assert row["analysis_timezone"] == "America/Los_Angeles"
    assert row["date_derivation"] == "home_timezone"


def test_absolute_hevy_instant_does_not_fabricate_travel_timezone():
    # This instant could have occurred during travel, but Hevy supplies no
    # trustworthy event-local timezone. The system therefore uses the home
    # timezone and does not claim a source timezone such as Asia/Tokyo.
    row = hevy_client.workout_to_row(
        _workout("2026-07-02T06:30:00Z", "2026-07-02T07:30:00Z")
    )
    assert row["date"] == "2026-07-01"
    assert row["analysis_timezone"] == "America/Los_Angeles"
    assert row["date_derivation"] == "home_timezone"
    assert "source_timezone" not in row


def test_hevy_body_measurement_uses_home_day_for_aware_instant():
    metrics = hevy_client.body_measurement_to_metrics(
        {"date": "2026-07-02T00:30:00Z", "weight_kg": 75}
    )
    assert metrics
    assert {metric[3] for metric in metrics} == {"2026-07-01"}

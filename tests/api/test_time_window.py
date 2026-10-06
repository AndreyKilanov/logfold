"""Time windows: since, until and split_at on both engines, and the diff of two parts of one log."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import logfold
from conftest import requires_native
from logfold import ConfigError
from logfold.api.windows import split_windows, to_micros, window

FORMAT = r"regex:^(?P<ts>\S+) (?P<lvl>[A-Z]+) (?P<msg>.*)$"
BASE = datetime(2026, 10, 6, 0, 0, 0)
RECORDS = 1200


def stamp(second: int) -> str:
    return (BASE + timedelta(seconds=second)).strftime("%Y-%m-%dT%H:%M:%S")


def at(second: int) -> str:
    return stamp(second)


def write_log(path: Path, untimed_every: int = 0) -> Path:
    lines = []
    for i in range(RECORDS):
        label = "no-time" if untimed_every and i % untimed_every == untimed_every - 1 else stamp(i)
        shape = i % 4
        if shape == 0:
            lines.append(f"{label} INFO user u{i % 11} logged in from 10.0.0.{i % 200}")
        elif shape == 1:
            lines.append(f"{label} WARN disk usage {50 + i % 40}% on /dev/sda{i % 3}")
        elif shape == 2:
            lines.append(f"{label} ERROR request {i} failed with status {500 + i % 4}")
        else:
            lines.append(f"{label} INFO cache miss for key k{i % 97}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def log(tmp_path: Path) -> Path:
    return write_log(tmp_path / "timed.log")


def counts(result: logfold.AnalysisResult) -> tuple[int, int, int, int]:
    run = result.run
    return run.records, run.out_of_range, run.untimed, run.lines


def table(result: logfold.AnalysisResult) -> list[tuple[str, int]]:
    return [(t.text, t.count) for t in result.templates]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-06", datetime(2026, 10, 6)),
        ("2026-10-06T12:30:00", datetime(2026, 10, 6, 12, 30)),
        ("2026-10-06 12:30:00", datetime(2026, 10, 6, 12, 30)),
        ("2026-10-06T12:30:00Z", datetime(2026, 10, 6, 12, 30, tzinfo=timezone.utc)),
        ("2026-10-06T15:30:00+03:00", datetime(2026, 10, 6, 12, 30, tzinfo=timezone.utc)),
        ("  2026-10-06T12:30:00.250  ", datetime(2026, 10, 6, 12, 30, 0, 250_000)),
    ],
)
def test_times_are_read_as_iso_8601(text: str, expected: datetime) -> None:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    aware = expected if expected.tzinfo else expected.replace(tzinfo=timezone.utc)
    assert to_micros(text, "since") == (aware - epoch) // timedelta(microseconds=1)


def test_a_datetime_object_is_accepted_and_a_zone_is_converted() -> None:
    naive = datetime(2026, 10, 6, 12, 0)
    aware = datetime(2026, 10, 6, 15, 0, tzinfo=timezone(timedelta(hours=3)))
    assert to_micros(naive, "since") == to_micros(aware, "since")
    assert to_micros(None, "since") is None


@pytest.mark.parametrize("text", ["", "yesterday", "12:00", "2026-13-01", "2026-10-06T25:00:00"])
def test_a_bad_time_is_a_config_error_with_a_hint(text: str) -> None:
    with pytest.raises(ConfigError, match="ISO 8601") as caught:
        to_micros(text, "since")
    assert caught.value.hint


def test_since_must_be_before_until() -> None:
    with pytest.raises(ConfigError, match="before"):
        window("2026-10-06T12:00", "2026-10-06T12:00")
    assert window("2026-10-06T12:00", None)[1] is None
    with pytest.raises(ConfigError, match="split_at needs"):
        split_windows(None, None, None)
    with pytest.raises(ConfigError):
        split_windows("2026-10-06T13:00", None, "2026-10-06T12:00")


def test_the_window_is_half_open(log: Path) -> None:
    result = logfold.analyze(log, format=FORMAT, since=at(100), until=at(200), engine="python")
    assert result.run.records == 100
    assert result.run.out_of_range == RECORDS - 100
    inclusive_end = logfold.analyze(log, format=FORMAT, since=at(100), until=at(201), engine="python")
    assert inclusive_end.run.records == 101


def test_one_bound_is_enough(log: Path) -> None:
    from_only = logfold.analyze(log, format=FORMAT, since=at(1000), engine="python")
    until_only = logfold.analyze(log, format=FORMAT, until=at(1000), engine="python")
    assert from_only.run.records == RECORDS - 1000
    assert until_only.run.records == 1000
    assert from_only.run.records + until_only.run.records == RECORDS


def test_no_bound_changes_nothing(log: Path) -> None:
    plain = logfold.analyze(log, format=FORMAT, engine="python")
    bounded = logfold.analyze(log, format=FORMAT, since="1999-01-01", until="2999-01-01", engine="python")
    assert table(plain) == table(bounded)
    assert (bounded.run.out_of_range, bounded.run.untimed) == (0, 0)


def test_records_outside_do_not_count_in_the_shares(log: Path) -> None:
    result = logfold.analyze(log, format=FORMAT, since=at(0), until=at(400), engine="python")
    assert sum(t.count for t in result.templates) == result.run.records == 400


def test_a_run_name_shows_the_window(log: Path) -> None:
    result = logfold.analyze(log, format=FORMAT, since=at(0), until=at(60), engine="python")
    assert result.run.name.endswith("[2026-10-06T00:00:00, 2026-10-06T00:01:00)")
    assert logfold.analyze(log, format=FORMAT, engine="python").run.name == str(log)


def test_records_without_a_time_are_left_out_counted_and_warned_about(tmp_path: Path) -> None:
    path = write_log(tmp_path / "gaps.log", untimed_every=5)
    result = logfold.analyze(path, format=FORMAT, since=at(0), until=at(RECORDS), engine="python")
    assert result.run.untimed == RECORDS // 5
    assert result.run.records == RECORDS - RECORDS // 5
    assert any("without a usable timestamp" in warning for warning in result.warnings)
    unbounded = logfold.analyze(path, format=FORMAT, engine="python")
    assert unbounded.run.records == RECORDS
    assert unbounded.run.untimed == 0
    assert not any("timestamp" in warning for warning in unbounded.warnings)


def test_a_zone_in_the_bound_is_converted_to_utc(log: Path) -> None:
    plus_three = logfold.analyze(log, format=FORMAT, since="2026-10-06T03:00:00+03:00", until=at(120), engine="python")
    utc = logfold.analyze(log, format=FORMAT, since=at(0), until=at(120), engine="python")
    assert counts(plus_three) == counts(utc)


def test_a_format_without_a_time_refuses_a_window(log: Path) -> None:
    with pytest.raises(ConfigError, match="no timestamp") as caught:
        logfold.analyze(log, format="plain", since=at(0))
    assert caught.value.hint
    logfold.analyze(log, format="plain", engine="python")


def test_a_window_with_nothing_inside_is_an_empty_result_with_a_warning(log: Path) -> None:
    result = logfold.analyze(log, format=FORMAT, since="2030-01-01", engine="python")
    assert result.run.records == 0
    assert result.templates == ()
    assert any("no records" in warning for warning in result.warnings)


@requires_native
@pytest.mark.parametrize("strategy", ["sequential", "chunked"])
def test_both_engines_agree(log: Path, strategy: str) -> None:
    python = logfold.analyze(log, format=FORMAT, since=at(150), until=at(930), engine="python")
    native = logfold.analyze(
        log, format=FORMAT, since=at(150), until=at(930), engine="native", strategy=strategy, chunk_bytes=4096
    )
    assert counts(native) == counts(python)
    assert table(native) == table(python)


@requires_native
def test_both_engines_agree_on_records_without_a_time(tmp_path: Path) -> None:
    path = write_log(tmp_path / "gaps.log", untimed_every=4)
    python = logfold.analyze(path, format=FORMAT, since=at(300), engine="python")
    native = logfold.analyze(path, format=FORMAT, since=at(300), engine="native")
    assert counts(native) == counts(python)
    assert table(native) == table(python)


@requires_native
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    start=st.one_of(st.none(), st.integers(0, RECORDS + 50)),
    span=st.one_of(st.none(), st.integers(1, RECORDS)),
    chunk=st.sampled_from([2048, 4096, 1 << 20]),
)
def test_any_window_gives_the_same_result_on_every_engine(
    log: Path, start: int | None, span: int | None, chunk: int
) -> None:
    since = None if start is None else at(start)
    until = None if span is None else at((start or 0) + span)
    python = logfold.analyze(log, format=FORMAT, since=since, until=until, engine="python")
    native = logfold.analyze(
        log, format=FORMAT, since=since, until=until, engine="native", strategy="chunked", chunk_bytes=chunk
    )
    assert counts(native) == counts(python)
    assert table(native) == table(python)
    assert python.run.records + python.run.out_of_range + python.run.untimed == RECORDS


def two_halves(tmp_path: Path, log: Path, cut: int) -> tuple[Path, Path]:
    lines = log.read_text(encoding="utf-8").splitlines()
    first = tmp_path / "first.log"
    second = tmp_path / "second.log"
    first.write_text("\n".join(lines[:cut]) + "\n", encoding="utf-8")
    second.write_text("\n".join(lines[cut:]) + "\n", encoding="utf-8")
    return first, second


@pytest.mark.parametrize("engine", ["python", "native"])
def test_split_at_equals_the_diff_of_two_hand_cut_files(tmp_path: Path, log: Path, engine: str) -> None:
    if engine == "native":
        pytest.importorskip("logfold._core")
    first, second = two_halves(tmp_path, log, 500)
    cut = logfold.diff(log, split_at=at(500), format=FORMAT, engine=engine, min_count=1, significance=1.0)
    hand = logfold.diff(first, second, format=FORMAT, engine=engine, min_count=1, significance=1.0)
    assert (cut.before.records, cut.after.records) == (500, RECORDS - 500)
    assert cut.new_templates == hand.new_templates
    assert cut.disappeared == hand.disappeared
    assert cut.changed == hand.changed
    assert cut.unchanged == hand.unchanged


@requires_native
def test_split_at_gives_the_same_result_on_both_engines(log: Path) -> None:
    python = logfold.diff(log, split_at=at(700), format=FORMAT, engine="python", min_count=1)
    native = logfold.diff(log, split_at=at(700), format=FORMAT, engine="native", min_count=1)
    assert (native.new_templates, native.disappeared, native.changed) == (
        python.new_templates,
        python.disappeared,
        python.changed,
    )


def test_split_at_names_both_runs_by_their_window(log: Path) -> None:
    result = logfold.diff(log, split_at=at(600), format=FORMAT, engine="python")
    assert result.before.name.endswith("[..., 2026-10-06T00:10:00)")
    assert result.after.name.endswith("[2026-10-06T00:10:00, ...)")


def test_since_and_until_bound_the_whole_range_of_a_split(log: Path) -> None:
    result = logfold.diff(log, split_at=at(600), since=at(300), until=at(900), format=FORMAT, engine="python")
    assert (result.before.records, result.after.records) == (300, 300)


def test_a_spike_inside_one_log_is_found(tmp_path: Path) -> None:
    lines = []
    for i in range(2000):
        lines.append(f"{stamp(i)} INFO request {i} served in {i % 40} ms")
        if i >= 1000 and i % 5 == 0:
            lines.append(f"{stamp(i)} ERROR payment gateway timeout for order {i}")
    path = tmp_path / "incident.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = logfold.diff(path, split_at=at(1000), format=FORMAT, engine="python")
    assert [e.text for e in result.new_templates] == ["payment gateway timeout for order <NUM>"]
    assert [e.text for e in result.new_alerts] == ["payment gateway timeout for order <NUM>"]


def test_split_at_needs_one_input_and_diff_needs_two_otherwise(log: Path) -> None:
    with pytest.raises(ConfigError, match="one input"):
        logfold.diff(log, log, split_at=at(10))
    with pytest.raises(ConfigError, match="two inputs"):
        logfold.diff(log)


def test_split_at_cannot_be_used_with_saved_results(log: Path) -> None:
    saved = logfold.analyze(log, format=FORMAT, engine="python")
    with pytest.raises(ConfigError, match="split_at"):
        logfold.diff(saved, split_at=at(10))
    with pytest.raises(ConfigError, match="since"):
        logfold.diff(saved, saved, since=at(10))


def test_split_at_cannot_read_standard_input(log: Path) -> None:
    with pytest.raises(ConfigError, match="standard input"):
        logfold.diff("-", split_at=at(10), format=FORMAT)


def test_a_time_that_is_not_a_string_or_a_datetime_is_a_config_error(log: Path) -> None:
    with pytest.raises(ConfigError, match="datetime or an ISO 8601 string"):
        logfold.analyze(log, format=FORMAT, since=1760000000)  # type: ignore[arg-type]


def test_a_format_without_a_time_refuses_a_split(log: Path) -> None:
    with pytest.raises(ConfigError, match="no timestamp"):
        logfold.diff(log, split_at=at(10), format="plain")


def test_the_counters_are_saved_and_loaded(log: Path, tmp_path: Path) -> None:
    result = logfold.analyze(log, format=FORMAT, since=at(100), until=at(200), engine="python")
    payload = json.loads(result.to_json())
    assert (payload["run"]["out_of_range"], payload["run"]["untimed"]) == (RECORDS - 100, 0)
    result.save(tmp_path / "window.json")
    loaded = logfold.load_analysis(tmp_path / "window.json")
    assert (loaded.run.records, loaded.run.out_of_range, loaded.run.untimed) == (100, RECORDS - 100, 0)


def test_a_result_saved_before_the_window_existed_still_loads(log: Path, tmp_path: Path) -> None:
    result = logfold.analyze(log, format=FORMAT, engine="python")
    payload = json.loads(result.to_json())
    del payload["run"]["out_of_range"], payload["run"]["untimed"]
    old = tmp_path / "old.json"
    old.write_text(json.dumps(payload), encoding="utf-8")
    loaded = logfold.load_analysis(old)
    assert (loaded.run.out_of_range, loaded.run.untimed) == (0, 0)

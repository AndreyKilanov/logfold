"""``Miner``: records arrive in batches, and the result is the one of ``analyze`` over the same records."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import jsonschema
import pytest

import logfold
from conftest import requires_native
from corpora import app_lines, write
from logfold import ConfigError, StateError
from logfold.ext.formats import PlainFormat

pytestmark = requires_native

SCHEMA = Path(__file__).parents[2] / "docs" / "schema" / "analysis-v1.schema.json"
TRACE_START = r"^\d{4}-\d\d-\d\d "


@pytest.fixture
def stream() -> list[str]:
    return app_lines(2500, 5)


def rows(result: logfold.AnalysisResult) -> list[tuple[object, ...]]:
    return [(t.text, t.count, t.first_seen, t.last_seen, t.example, t.level, dict(t.levels)) for t in result.templates]


def counters(result: logfold.AnalysisResult) -> tuple[int, int, int, bool]:
    run = result.run
    return run.lines, run.records, run.unparsed, run.tz_aware


def batches(items: list[str], size: int) -> list[list[str]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


def analyzed(tmp_path: Path, stream: list[str]) -> logfold.AnalysisResult:
    log = write(tmp_path / "all.log", stream)
    return logfold.analyze(str(log), format="app", strategy="sequential")


@pytest.mark.parametrize("size", [1, 13, 700, 10_000])
def test_add_many_gives_the_result_of_analyze_whatever_the_batches(
    tmp_path: Path, stream: list[str], size: int
) -> None:
    miner = logfold.Miner(format="app")
    taken = sum(miner.add_many(batch) for batch in batches(stream, size))
    expected = analyzed(tmp_path, stream)
    result = miner.result()
    assert taken == len(stream)
    assert rows(result) == rows(expected)
    assert counters(result) == counters(expected)
    assert result.meta.config_hash == expected.meta.config_hash


@pytest.mark.parametrize("size", [1, 64, 10_000])
def test_add_lines_with_line_feeds_gives_the_result_of_analyze(tmp_path: Path, stream: list[str], size: int) -> None:
    miner = logfold.Miner(format="app")
    for batch in batches([line + "\n" for line in stream], size):
        miner.add_lines(batch)
    miner.flush()
    assert rows(miner.result()) == rows(analyzed(tmp_path, stream))


def test_add_log_message_mines_one_record_and_skips_a_blank_one() -> None:
    miner = logfold.Miner()
    assert miner.add_log_message("user 7 logged in") == 1
    assert miner.add_log_message("   ") == 0
    assert miner.result().run.records == 1


def test_a_multi_line_record_waits_for_the_next_record_or_a_flush() -> None:
    miner = logfold.Miner(format=PlainFormat("traces", record_start=TRACE_START, multiline=True))
    assert miner.add_lines(["2026-10-04 boom\n", "  at frame 1\n", "  at frame 2\n"]) == 0
    assert miner.result().run.records == 0
    assert miner.add_lines(["2026-10-04 next\n"]) == 1
    assert miner.flush() == 1
    assert miner.flush() == 0
    result = miner.result()
    assert result.run.records == 2
    assert "2026-10-04 boom\n  at frame 1\n  at frame 2" in {t.example for t in result.templates}


def test_new_templates_are_reported_once_and_in_creation_order() -> None:
    miner = logfold.Miner()
    assert miner.new_templates() == []
    miner.add_many(["job 1 finished", "job 2 finished"])
    assert miner.new_templates() == ["job <NUM> finished"]
    assert miner.new_templates() == []
    miner.add_many(["the disk caught fire and burned down"])
    assert miner.new_templates() == ["the disk caught fire and burned down"]


def test_the_format_gives_the_level_and_time_of_a_record() -> None:
    miner = logfold.Miner(format="app")
    miner.add_many(["2026-10-04T00:00:01Z ERROR request 5 failed", "2026-10-04T00:00:09Z INFO request 6 failed"])
    (template,) = miner.result().templates
    assert template.level == "ERROR"
    assert dict(template.levels) == {"INFO": 1, "ERROR": 1}
    assert template.first_seen is not None
    assert template.last_seen is not None
    assert template.last_seen > template.first_seen


def test_a_stream_cannot_detect_its_format() -> None:
    with pytest.raises(ConfigError, match="no file to detect"):
        logfold.Miner(format="auto")


def test_the_default_format_is_plain() -> None:
    miner = logfold.Miner()
    miner.add_many(["2026-10-04T00:00:01Z ERROR boom"])
    (template,) = miner.result().templates
    assert template.level is None
    assert template.text.startswith("<TS>")


def test_invalid_options_are_refused() -> None:
    with pytest.raises(ConfigError):
        logfold.Miner(sim_th=2.0)
    with pytest.raises(ConfigError, match="state_format"):
        logfold.Miner(state_format="yaml")
    with pytest.raises(logfold.FormatError):
        logfold.Miner(format="regex:(")


@pytest.mark.parametrize("form", ["json", "binary"])
def test_a_saved_miner_continues_in_analyze_and_the_other_way_round(
    tmp_path: Path, stream: list[str], form: str
) -> None:
    head, tail = stream[:1200], stream[1200:]
    first = logfold.Miner(format="app", state_format=form)
    first.add_many(head)
    state = tmp_path / "miner.state"
    first.save_state(state)

    log = write(tmp_path / "tail.log", tail)
    resumed = logfold.analyze(str(log), format="app", strategy="sequential", load_state=state)
    uninterrupted = analyzed(tmp_path, stream)
    assert sum(t.count for t in resumed.templates) == len(tail)

    again = logfold.Miner(format="app", load_state=state)
    again.add_many(tail)
    assert rows(again.result()) == rows(resumed)
    saved_by_analyze = tmp_path / "analyze.state"
    logfold.analyze(str(tmp_path / "all.log"), format="app", strategy="sequential", save_state=saved_by_analyze)
    assert uninterrupted.run.records == len(stream)
    from_analyze = logfold.Miner(format="app", load_state=saved_by_analyze)
    assert from_analyze.result().run.records == 0
    assert from_analyze.new_templates() == []


def test_a_state_of_a_miner_can_be_matched_against(tmp_path: Path, stream: list[str]) -> None:
    miner = logfold.Miner(format="app")
    miner.add_many(stream)
    state = tmp_path / "miner.json"
    miner.save_state(state)
    log = write(tmp_path / "again.log", stream)
    matched = logfold.match(state, str(log), format="app")
    assert matched.run.unmatched is not None
    assert matched.run.unmatched.records == 0
    assert sum(t.count for t in matched.templates) == len(stream)


def test_a_state_mined_with_other_settings_is_refused(tmp_path: Path, stream: list[str]) -> None:
    miner = logfold.Miner(format="app")
    miner.add_many(stream[:100])
    state = tmp_path / "miner.json"
    miner.save_state(state)
    with pytest.raises(StateError):
        logfold.Miner(format="app", sim_th=0.7, load_state=state)
    with pytest.raises(StateError):
        logfold.Miner(format="app", load_state=tmp_path / "missing.json")


def test_the_result_is_valid_json_of_the_analysis_schema(stream: list[str]) -> None:
    miner = logfold.Miner(format="app")
    miner.add_many(stream)
    document = json.loads(miner.result().to_json())
    jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(document)


def test_examples_follow_the_requested_mode() -> None:
    raw = logfold.Miner(examples="raw")
    masked = logfold.Miner(examples="masked")
    none = logfold.Miner(examples="none")
    for miner in (raw, masked, none):
        miner.add_many(["user 42 logged in from 10.0.0.1"])
    assert raw.result().templates[0].example == "user 42 logged in from 10.0.0.1"
    assert masked.result().templates[0].example == "user <NUM> logged in from <IP>"
    assert none.result().templates[0].example is None


def test_a_lone_surrogate_is_read_as_the_replacement_character() -> None:
    miner = logfold.Miner()
    assert miner.add_many(["bad \udcff byte"]) == 1
    assert "�" in miner.result().templates[0].example  # type: ignore[operator]


def test_several_threads_lose_no_record() -> None:
    miner = logfold.Miner()
    per_thread, threads = 2000, 8

    def feed(worker: int) -> None:
        for start in range(0, per_thread, 50):
            miner.add_many(f"worker {worker} request {n} done" for n in range(start, start + 50))

    pool = [threading.Thread(target=feed, args=(worker,)) for worker in range(threads)]
    for thread in pool:
        thread.start()
    for thread in pool:
        thread.join()
    result = miner.result()
    assert result.run.records == per_thread * threads
    assert sum(t.count for t in result.templates) == per_thread * threads


def test_the_unparsed_records_are_counted_and_warned_about() -> None:
    miner = logfold.Miner(format="app")
    miner.add_many(["not a log line"] * 5 + ["2026-10-04T00:00:01Z INFO ok"])
    result = miner.result()
    assert result.run.unparsed == 5
    assert any("did not match the format" in warning for warning in result.warnings)


def test_a_blank_miner_has_no_templates() -> None:
    result = logfold.Miner().result()
    assert result.templates == ()
    assert result.run.records == 0
    assert result.run.name == "stream"


@pytest.mark.parametrize("method", ["add_many", "add_lines"])
def test_a_single_string_is_not_mined_one_character_at_a_time(method: str) -> None:
    miner = logfold.Miner()
    with pytest.raises(ConfigError, match="not one string"):
        getattr(miner, method)("one record")
    assert miner.result().run.records == 0


def test_a_settings_file_that_says_auto_gives_plain_to_a_stream() -> None:
    settings = logfold.Settings(format="auto")
    miner = logfold.Miner(config=settings)
    assert miner.add_many(["x y z"]) == 1
    with pytest.raises(ConfigError, match="no file to detect"):
        logfold.Miner(format="auto", config=settings)


def test_one_miner_per_thread_gives_each_the_result_of_its_own_records() -> None:
    sources = {
        name: [f"{name} request {n} done" for n in range(1500)] + [f"{name} disk {n} full" for n in range(500)]
        for name in ("api", "worker", "billing", "mailer")
    }
    miners = {name: logfold.Miner() for name in sources}

    def feed(name: str) -> None:
        for start in range(0, len(sources[name]), 100):
            miners[name].add_many(sources[name][start : start + 100])

    pool = [threading.Thread(target=feed, args=(name,)) for name in sources]
    for thread in pool:
        thread.start()
    for thread in pool:
        thread.join()
    for name, records in sources.items():
        alone = logfold.Miner()
        alone.add_many(records)
        assert [(t.text, t.count) for t in miners[name].result().templates] == [
            (t.text, t.count) for t in alone.result().templates
        ]

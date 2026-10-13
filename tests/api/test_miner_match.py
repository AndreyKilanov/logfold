"""``Miner.match_many`` and ``Miner.match``: records are assigned to the templates of a miner and nothing is learned."""

from __future__ import annotations

from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from corpora import app_lines, write
from logfold import ConfigError, TemplateMatch

pytestmark = requires_native

UNKNOWN = [
    "2026-10-04T00:00:00Z INFO the disk caught fire and burned down",
    "2026-10-04T00:00:01Z INFO w0 w1 w2 w0 w1 w2 w0 w1 w2 w0 w1 w2",
]


@pytest.fixture
def stream() -> list[str]:
    return app_lines(1500, 7)


@pytest.fixture
def trained(stream: list[str]) -> logfold.Miner:
    miner = logfold.Miner(format="app")
    miner.add_many(stream)
    return miner


def counts_by_text(matches: list[TemplateMatch | None]) -> dict[str, int]:
    found: dict[str, int] = {}
    for match in matches:
        if match is not None:
            found[match.text] = found.get(match.text, 0) + 1
    return found


def test_the_answers_are_those_of_the_match_command(tmp_path: Path, trained: logfold.Miner, stream: list[str]) -> None:
    probe = [*stream[:400], *UNKNOWN]
    state = tmp_path / "model.json"
    trained.save_state(state)
    expected = logfold.match(state, write(tmp_path / "probe.log", probe), format="app")

    matches = trained.match_many(probe)

    assert len(matches) == len(probe)
    assert counts_by_text(matches) == {t.text: t.count for t in expected.templates}
    assert expected.run.unmatched is not None
    assert matches.count(None) == expected.run.unmatched.records == len(UNKNOWN)


def test_a_match_names_the_template_as_the_result_reports_it(trained: logfold.Miner, stream: list[str]) -> None:
    by_text = {t.text: t.id for t in trained.result().templates}
    for match in trained.match_many(stream[:200]):
        assert match is not None
        assert by_text[match.text] == match.id


def test_matching_learns_nothing(trained: logfold.Miner, stream: list[str]) -> None:
    trained.new_templates()
    before = trained.result()
    trained.match_many([*stream, *UNKNOWN])
    trained.match(UNKNOWN[0])
    after = trained.result()
    assert [(t.text, t.count) for t in after.templates] == [(t.text, t.count) for t in before.templates]
    assert after.run.records == before.run.records
    assert after.run.lines == before.run.lines
    assert trained.new_templates() == []


def test_the_answer_for_a_record_does_not_depend_on_the_batch(trained: logfold.Miner, stream: list[str]) -> None:
    probe = [*stream[:300], *UNKNOWN]
    whole = trained.match_many(probe)
    one_by_one = [trained.match(record) for record in probe]
    halves = [*trained.match_many(probe[:150]), *trained.match_many(probe[150:])]
    assert one_by_one == whole
    assert halves == whole


def test_blank_and_unparsed_records_have_no_template(trained: logfold.Miner, stream: list[str]) -> None:
    answers = trained.match_many(["", "   ", "no timestamp and no level here", stream[0]])
    assert answers[:3] == [None, None, None]
    assert answers[3] is not None


def test_a_miner_without_templates_matches_nothing() -> None:
    miner = logfold.Miner()
    assert miner.match_many([]) == []
    assert miner.match_many(["job 1 finished"]) == [None]
    assert miner.match("job 1 finished") is None


def test_a_loaded_state_is_matched_against(tmp_path: Path, trained: logfold.Miner, stream: list[str]) -> None:
    state = tmp_path / "model.json"
    trained.save_state(state)
    loaded = logfold.Miner(format="app", load_state=state)
    assert loaded.match_many(stream[:100]) == trained.match_many(stream[:100])
    assert loaded.result().run.records == 0


def test_a_template_that_was_generalized_is_named_with_its_current_text() -> None:
    miner = logfold.Miner(format="plain")
    miner.add_many(["cache miss for key kab"])
    assert miner.match("cache miss for key kab") == TemplateMatch(
        miner.result().templates[0].id, "cache miss for key kab"
    )
    miner.add_many(["cache miss for key kcd"])
    (template,) = miner.result().templates
    assert miner.match("cache miss for key kzz") == TemplateMatch(template.id, "cache miss for key <*>")


def test_a_single_string_is_refused() -> None:
    miner = logfold.Miner()
    with pytest.raises(ConfigError, match="not one string"):
        miner.match_many("job 1 finished")  # type: ignore[arg-type]


def test_a_lone_surrogate_does_not_break_matching() -> None:
    miner = logfold.Miner()
    miner.add_many(["job 1 finished"])
    assert miner.match("job \ud800 finished") == miner.match("job \N{REPLACEMENT CHARACTER} finished")

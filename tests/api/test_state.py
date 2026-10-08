"""State files in ``analyze()``: continue from a saved miner, save one, and refuse what cannot be used."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from corpora import app_lines, write
from logfold import ConfigError, EngineError, StateError

pytestmark = requires_native


@pytest.fixture
def stream() -> list[str]:
    return app_lines(3000, 21)


def split(tmp_path: Path, stream: list[str], at: int) -> tuple[Path, Path, Path]:
    return (
        write(tmp_path / "all.log", stream),
        write(tmp_path / "a.log", stream[:at]),
        write(tmp_path / "b.log", stream[at:]),
    )


def mine(path: Path, **options: object) -> logfold.AnalysisResult:
    return logfold.analyze(str(path), format="app", strategy="sequential", **options)  # type: ignore[arg-type]


@pytest.mark.parametrize("form", ["json", "binary"])
@pytest.mark.parametrize("at", [1, 700, 2999])
def test_a_resumed_run_saves_the_state_of_an_uninterrupted_run(
    tmp_path: Path, stream: list[str], form: str, at: int
) -> None:
    whole, first, second = split(tmp_path, stream, at)
    mine(whole, save_state=tmp_path / "whole.state", state_format=form)
    mine(first, save_state=tmp_path / "first.state", state_format=form)
    mine(second, load_state=tmp_path / "first.state", save_state=tmp_path / "resumed.state", state_format=form)
    assert (tmp_path / "resumed.state").read_bytes() == (tmp_path / "whole.state").read_bytes()


def test_the_report_of_a_resumed_run_counts_only_its_own_records(tmp_path: Path, stream: list[str]) -> None:
    _, first, second = split(tmp_path, stream, 1500)
    mine(first, save_state=tmp_path / "s.json")
    alone = mine(second)
    resumed = mine(second, load_state=tmp_path / "s.json")
    assert resumed.run.records == alone.run.records == len(stream) - 1500
    assert sum(template.count for template in resumed.templates) == resumed.run.records
    assert all(template.count > 0 for template in resumed.templates), (
        "templates of the state that did not occur are left out"
    )


def test_a_state_can_be_continued_again_and_again(tmp_path: Path, stream: list[str]) -> None:
    parts = [stream[:1000], stream[1000:2000], stream[2000:]]
    files = [write(tmp_path / f"p{i}.log", part) for i, part in enumerate(parts)]
    whole = write(tmp_path / "all.log", stream)
    mine(whole, save_state=tmp_path / "whole.json")
    mine(files[0], save_state=tmp_path / "s.json")
    mine(files[1], load_state=tmp_path / "s.json", save_state=tmp_path / "s.json")
    mine(files[2], load_state=tmp_path / "s.json", save_state=tmp_path / "s.json")
    assert (tmp_path / "s.json").read_bytes() == (tmp_path / "whole.json").read_bytes()


def test_a_gzip_state_round_trips(tmp_path: Path, stream: list[str]) -> None:
    _, first, second = split(tmp_path, stream, 1500)
    mine(first, save_state=tmp_path / "s.json.gz")
    assert gzip.decompress((tmp_path / "s.json.gz").read_bytes()).startswith(b'{"kind":"logfold-state"')
    assert mine(second, load_state=tmp_path / "s.json.gz").run.records == len(stream) - 1500


def test_the_state_holds_templates_not_example_lines(tmp_path: Path, stream: list[str]) -> None:
    """A template seen once is its masked line, so the words stay; the values the masks hide do not appear."""
    line = "2026-10-04T10:00:00Z INFO user alice paid order 4711 from 10.9.8.7"
    first = write(tmp_path / "a.log", [*stream[:50], line])
    mine(first, save_state=tmp_path / "s.json")
    text = (tmp_path / "s.json").read_text(encoding="utf-8")
    assert "example" not in text
    assert "4711" not in text
    assert "10.9.8.7" not in text
    assert '"user","alice","paid","order","<NUM>","from","<IP>"' in text, "the masked template itself is kept"


@pytest.mark.parametrize(
    "change",
    [{"depth": 5}, {"sim_th": 0.5}, {"max_children": 50}, {"max_templates": 500}, {"masks": []}],
    ids=["depth", "sim_th", "max_children", "max_templates", "masks"],
)
def test_a_state_mined_with_other_settings_is_refused(
    tmp_path: Path, stream: list[str], change: dict[str, object]
) -> None:
    _, first, second = split(tmp_path, stream, 1500)
    mine(first, save_state=tmp_path / "s.json")
    with pytest.raises(StateError, match=r"other masks or parameters|other parameters") as caught:
        mine(second, load_state=tmp_path / "s.json", **change)
    assert caught.value.hint


def test_the_format_is_not_part_of_the_check(tmp_path: Path, stream: list[str]) -> None:
    _, first, second = split(tmp_path, stream, 1500)
    mine(first, save_state=tmp_path / "s.json")
    result = logfold.analyze(str(second), format="plain", strategy="sequential", load_state=tmp_path / "s.json")
    assert result.run.records > 0


def test_a_saved_state_is_continued_sequentially(tmp_path: Path, stream: list[str]) -> None:
    _, first, second = split(tmp_path, stream, 1500)
    mine(first, save_state=tmp_path / "s.json")
    auto = logfold.analyze(str(second), format="app", load_state=tmp_path / "s.json", chunk_bytes=2048)
    assert auto.metrics.strategy == "sequential"
    with pytest.raises(ConfigError, match="sequential strategy only") as caught:
        logfold.analyze(str(second), format="app", strategy="chunked", load_state=tmp_path / "s.json")
    assert caught.value.hint


def test_the_pure_python_engine_cannot_use_state_files_yet(tmp_path: Path, stream: list[str]) -> None:
    _, first, _ = split(tmp_path, stream, 1500)
    with pytest.raises(EngineError, match="native engine"):
        logfold.analyze(str(first), format="app", engine="python", save_state=tmp_path / "s.json")


def test_a_missing_state_file_is_an_error_that_names_it(tmp_path: Path, stream: list[str]) -> None:
    _, first, _ = split(tmp_path, stream, 1500)
    with pytest.raises(StateError, match=r"missing\.json"):
        mine(first, load_state=tmp_path / "missing.json")


def test_damaged_state_files_are_refused(tmp_path: Path, stream: list[str]) -> None:
    _, first, second = split(tmp_path, stream, 1500)
    for form in ("json", "binary"):
        good = tmp_path / f"good.{form}"
        mine(first, save_state=good, state_format=form)
        data = good.read_bytes()
        for name, damaged in (
            ("cut", data[: len(data) // 2]),
            ("flipped", data[:100] + bytes([data[100] ^ 4]) + data[101:]),
            ("empty", b""),
            ("text", b"this is not a state"),
        ):
            path = tmp_path / f"{form}-{name}.state"
            path.write_bytes(damaged)
            with pytest.raises(StateError):
                mine(second, load_state=path)


def test_an_unknown_state_format_is_a_configuration_error(tmp_path: Path, stream: list[str]) -> None:
    _, first, _ = split(tmp_path, stream, 1500)
    with pytest.raises(ConfigError, match="state_format"):
        mine(first, save_state=tmp_path / "s.json", state_format="yaml")


def test_saving_alone_does_not_change_the_result(tmp_path: Path, stream: list[str]) -> None:
    _, first, _ = split(tmp_path, stream, 1500)
    plain = mine(first)
    saved = mine(first, save_state=tmp_path / "s.json")
    assert [(t.id, t.count) for t in plain.templates] == [(t.id, t.count) for t in saved.templates]

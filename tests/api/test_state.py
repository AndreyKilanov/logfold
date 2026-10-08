"""State files in ``analyze()``: continue from a saved miner, save one, and refuse what cannot be used."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from corpora import app_lines, write
from logfold import ConfigError, StateError
from logfold.config import MiningConfig, config_fingerprint

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


def test_a_saved_state_can_be_continued_in_parallel(tmp_path: Path, stream: list[str]) -> None:
    """Every chunk starts from a copy of the loaded tree; the result is deterministic and counts every record."""
    _, first, second = split(tmp_path, stream, 1500)
    mine(first, save_state=tmp_path / "s.json")
    sequential = mine(second, load_state=tmp_path / "s.json")
    outcomes = []
    for strategy, threads in (("chunked", 1), ("chunked", 4)):
        parallel = logfold.analyze(
            str(second),
            format="app",
            strategy=strategy,
            threads=threads,
            chunk_bytes=8192,
            load_state=tmp_path / "s.json",
        )
        assert parallel.metrics.strategy == "chunked"
        assert parallel.run.records == sequential.run.records
        assert sum(t.count for t in parallel.templates) == sequential.run.records
        outcomes.append([(t.id, t.count) for t in parallel.templates])
    assert outcomes[0] == outcomes[1], "the number of threads does not change the result"
    shared = {t.text for t in sequential.templates} & {t.text for t in parallel.templates}
    assert len(shared) >= 0.9 * len(sequential.templates)


def test_auto_continues_a_big_input_in_parallel_and_says_so(tmp_path: Path, stream: list[str]) -> None:
    _, first, second = split(tmp_path, stream, 1500)
    mine(first, save_state=tmp_path / "s.json")
    big = logfold.analyze(str(second), format="app", load_state=tmp_path / "s.json", chunk_bytes=8192)
    assert big.metrics.strategy == "chunked"
    assert any("continued in parallel" in warning for warning in big.warnings)
    small = logfold.analyze(str(second), format="app", load_state=tmp_path / "s.json")
    assert small.metrics.strategy == "sequential", "an input of one chunk is mined in one piece"
    assert not any("continued in parallel" in warning for warning in small.warnings)
    exact = mine(second, load_state=tmp_path / "s.json", chunk_bytes=8192)
    assert exact.metrics.strategy == "sequential", "the exact continuation is one option away"
    assert not any("continued in parallel" in warning for warning in exact.warnings)


def test_a_parallel_resume_saves_a_state_that_loads_again(tmp_path: Path, stream: list[str]) -> None:
    first = write(tmp_path / "a.log", stream[:1000])
    second = write(tmp_path / "b.log", stream[1000:2000])
    third = write(tmp_path / "c.log", stream[2000:])
    mine(first, save_state=tmp_path / "s.json")
    logfold.analyze(
        str(second),
        format="app",
        strategy="chunked",
        chunk_bytes=8192,
        load_state=tmp_path / "s.json",
        save_state=tmp_path / "s.json",
    )
    assert mine(third, load_state=tmp_path / "s.json").run.records == len(stream) - 2000


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


def test_a_state_path_that_cannot_be_written_fails_before_the_run(tmp_path: Path, stream: list[str]) -> None:
    _, first, _ = split(tmp_path, stream, 1500)
    consumed: list[int] = []
    with pytest.raises(StateError, match=r"cannot write"):
        mine(first, save_state=tmp_path / "no-such-folder" / "s.json", progress=consumed.append)
    assert consumed == [], "the log was not read: a mistyped folder must not cost the whole run"


def test_a_signed_file_with_a_broken_tree_is_refused(tmp_path: Path, stream: list[str]) -> None:
    """The checksum only says that the bytes are those that were written; the tree is checked on its own."""
    _, first, second = split(tmp_path, stream, 1500)
    mine(first, save_state=tmp_path / "s.json")
    header, body, _ = (tmp_path / "s.json").read_text(encoding="utf-8").split("\n")[:3]
    document = json.loads(body)
    leaf = next(node for node in document["nodes"] if node["k"])
    leaf["k"].append(10**6)
    body = json.dumps(document, separators=(",", ":"), ensure_ascii=False)
    signed = f"{header}\n{body}\n"
    digest = hashlib.sha256(signed.encode("utf-8")).hexdigest()
    (tmp_path / "forged.json").write_text(f'{signed}{{"sha256":"{digest}"}}\n', encoding="utf-8", newline="")
    with pytest.raises(StateError, match="damaged state file"):
        mine(second, load_state=tmp_path / "forged.json")


def test_the_fingerprint_of_the_default_settings_is_pinned() -> None:
    """A state is refused when the fingerprint of its settings differs, so changing how it is computed (a new field of
    MiningConfig, another masks default) would silently invalidate every saved state: change this value on purpose, with
    a changelog entry, never by accident."""
    assert config_fingerprint(MiningConfig()) == "721277182c26"


@pytest.mark.parametrize(
    "options",
    [{"strategy": "chunked"}, {"strategy": "chunked", "warm_start": True}, {"strategy": "auto"}],
    ids=["chunked", "warm-start", "auto"],
)
def test_a_state_saved_by_a_parallel_run_can_be_loaded(tmp_path: Path, options: dict[str, object]) -> None:
    """The tree that the merge of chunks builds must pass the same checks as a tree mined in one piece."""
    big = write(tmp_path / "big.log", app_lines(12000, 3))
    state = tmp_path / "parallel.json"
    saved = logfold.analyze(str(big), format="app", chunk_bytes=50_000, threads=4, save_state=state, **options)  # type: ignore[arg-type]
    if options["strategy"] == "chunked":
        assert saved.metrics.strategy == "chunked", "the state is meant to come from the merge of chunks"
    again = write(tmp_path / "again.log", app_lines(500, 4))
    resumed = mine(again, load_state=state)
    assert resumed.run.records == 500

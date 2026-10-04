from __future__ import annotations

from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from logfold import ConfigError, FormatError, MaskRule, MiningConfig, SourceError
from logfold.errors import EngineError


def test_analyze_returns_templates_sorted_by_count(corpus_dir: Path) -> None:
    result = logfold.analyze(str(corpus_dir / "app.log"), format="app")
    counts = [t.count for t in result.templates]
    assert counts == sorted(counts, reverse=True)
    assert result.run.records == sum(counts)
    assert result.run.lines == 1500
    assert result.meta.schema_version == 1
    assert result.meta.format == "app"
    assert result.top(3) == result.templates[:3]
    assert result.top(0) == ()


def test_template_fields(corpus_dir: Path) -> None:
    result = logfold.analyze(str(corpus_dir / "app.log"), format="app")
    template = next(t for t in result.templates if t.level == "ERROR")
    assert len(template.id) == 16
    assert template.first_seen is not None
    assert template.first_seen.tzinfo is not None
    assert template.first_seen <= template.last_seen  # type: ignore[operator]
    assert template.example
    assert sum(template.levels.values()) == template.count


def test_path_objects_and_lists_are_accepted(corpus_dir: Path) -> None:
    single = logfold.analyze(corpus_dir / "app.log", format="app")
    several = logfold.analyze([corpus_dir / "app.log", corpus_dir / "app_nonl.log"], format="app")
    assert several.run.records == single.run.records + 400
    assert several.run.files == 2


def test_naive_timestamps_stay_naive(corpus_dir: Path) -> None:
    result = logfold.analyze(str(corpus_dir / "syslog.log"), format="syslog")
    assert result.run.tz_aware is False
    assert result.templates[0].first_seen is not None
    assert result.templates[0].first_seen.tzinfo is None


@pytest.mark.parametrize("mode", ["raw", "masked", "none"])
def test_examples_modes(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "one.log"
    path.write_text("2026-10-04T10:00:00Z INFO connect from 10.1.2.3 ok\n", encoding="utf-8")
    result = logfold.analyze(str(path), format="app", examples=mode)  # type: ignore[arg-type]
    example = result.templates[0].example
    if mode == "raw":
        assert example == "connect from 10.1.2.3 ok"
    elif mode == "masked":
        assert example == "connect from <IP> ok"
    else:
        assert example is None


def test_progress_callback_receives_bytes(corpus_dir: Path) -> None:
    seen: list[int] = []
    path = corpus_dir / "app.log"
    logfold.analyze(str(path), format="app", progress=seen.append)
    assert sum(seen) >= path.stat().st_size - 2


def test_config_hash_changes_with_masks(corpus_dir: Path) -> None:
    path = str(corpus_dir / "app.log")
    default = logfold.analyze(path, format="app")
    again = logfold.analyze(path, format="app")
    other = logfold.analyze(path, format="app", masks=[MaskRule("n", r"\d+", "<N>", True)])
    assert default.meta.config_hash == again.meta.config_hash
    assert default.meta.config_hash != other.meta.config_hash


@pytest.mark.parametrize("engine", ["python", pytest.param("native", marks=requires_native)])
def test_errors_are_library_errors(tmp_path: Path, engine: str) -> None:
    with pytest.raises(SourceError):
        logfold.analyze(str(tmp_path / "missing.log"), format="plain", engine=engine)
    with pytest.raises(FormatError):
        logfold.analyze(str(tmp_path / "missing.log"), format="regex:(unclosed", engine=engine)
    with pytest.raises(FormatError):
        logfold.analyze(str(tmp_path / "missing.log"), format="no-such-format", engine=engine)


def test_invalid_options() -> None:
    with pytest.raises(ConfigError):
        MiningConfig(depth=2)
    with pytest.raises(ConfigError):
        MiningConfig(sim_th=1.5)
    with pytest.raises(ConfigError):
        MiningConfig(delimiters="é")
    with pytest.raises(ConfigError):
        logfold.ExecutionConfig(threads=0)
    with pytest.raises(ConfigError):
        logfold.DiffConfig(threshold_ratio=0.5)
    with pytest.raises(ConfigError):
        logfold.analyze([], format="plain")


def test_empty_pattern_mask_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text("x\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        logfold.analyze(str(path), format="plain", masks=[MaskRule("bad", "a*", "<A>")])


def test_unknown_engine_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("LOGFOLD_ENGINE", "bogus")
    with pytest.raises(ConfigError):
        logfold.analyze(str(path), format="plain")


def test_python_engine_via_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text("hello world\n", encoding="utf-8")
    monkeypatch.setenv("LOGFOLD_ENGINE", "python")
    result = logfold.analyze(str(path), format="plain")
    assert result.metrics.engine == "python"
    assert result.meta.degraded is True
    assert result.warnings == ()


def test_native_unavailable_raises_for_explicit_choice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from logfold.engines import native

    monkeypatch.setattr(native, "_core", None)
    path = tmp_path / "a.log"
    path.write_text("x\n", encoding="utf-8")
    with pytest.raises(EngineError):
        logfold.analyze(str(path), format="plain", engine="native")
    fallback = logfold.analyze(str(path), format="plain")
    assert fallback.metrics.engine == "python"
    assert any("native extension is unavailable" in w for w in fallback.warnings)


def test_gzip_input(tmp_path: Path) -> None:
    import gzip

    path = tmp_path / "a.log.gz"
    with gzip.open(path, "wb") as stream:
        stream.write(b"2026-10-04T10:00:00Z INFO hello\n" * 50)
    for engine in ("python", "auto"):
        result = logfold.analyze(str(path), format="auto", engine=engine)
        assert result.run.records == 50


@requires_native
def test_chunked_is_deterministic_across_threads_and_close_to_sequential(corpus_dir: Path) -> None:
    from corpora import app_lines, write

    big = write(corpus_dir / "app_big.log", app_lines(40_000, 21))
    path = str(big)

    def run(threads: int) -> list[tuple[str, int]]:
        result = logfold.analyze(path, format="app", strategy="chunked", threads=threads, chunk_bytes=200_000)
        assert result.metrics.strategy == "chunked"
        assert result.metrics.chunks > 5
        return [(t.text, t.count) for t in result.templates]

    baseline = run(1)
    for threads in (2, 4, 8):
        assert run(threads) == baseline
    sequential = logfold.analyze(path, format="app", strategy="sequential")
    assert sum(c for _t, c in baseline) == sequential.run.records == 40_000
    assert {t for t, _c in baseline} == {t.text for t in sequential.templates}

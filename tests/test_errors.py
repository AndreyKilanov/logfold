from __future__ import annotations

import copy
import pickle
from pathlib import Path

import pytest

import logfold
from logfold.errors import (
    ConfigError,
    FormatDetectionError,
    FormatError,
    LogfoldError,
    NoLevelsError,
    SourceError,
    UnknownFormatError,
    UnknownMatcherError,
    UnknownReporterError,
    UnknownSuffixError,
    read_error,
    write_error,
)
from logfold.ext import registry
from logfold.formats.auto import detect_format


def test_a_plain_error_has_no_hint() -> None:
    error = LogfoldError("boom")
    assert str(error) == "boom"
    assert error.hint is None


def test_the_hint_is_not_part_of_the_message() -> None:
    error = ConfigError("bad value", hint="try another")
    assert str(error) == "bad value"
    assert error.hint == "try another"


def test_new_errors_keep_the_old_base_classes() -> None:
    assert issubclass(UnknownFormatError, FormatError)
    assert issubclass(UnknownFormatError, ValueError)
    assert issubclass(UnknownReporterError, ConfigError)
    assert issubclass(UnknownMatcherError, ConfigError)
    assert issubclass(FormatDetectionError, FormatError)


def test_unknown_format_carries_the_name_and_the_closest_one() -> None:
    with pytest.raises(UnknownFormatError) as caught:
        registry.get_format("nginxx")
    error = caught.value
    assert error.name == "nginxx"
    assert "nginx" in error.known
    assert error.known == tuple(sorted(error.known))
    assert error.hint == "did you mean 'nginx'?"
    assert str(error).startswith("unknown format 'nginxx'; known formats: ")


def test_unknown_reporter_and_matcher_have_hints() -> None:
    with pytest.raises(UnknownReporterError) as reporter:
        registry.get_reporter("jsno")
    assert reporter.value.hint == "did you mean 'json'?"
    with pytest.raises(UnknownMatcherError) as matcher:
        registry.get_matcher("exat")
    assert matcher.value.hint == "did you mean 'exact'?"


def test_no_close_name_means_no_hint() -> None:
    with pytest.raises(UnknownFormatError) as caught:
        registry.get_format("qqqqqqqq")
    assert caught.value.hint is None


def test_undetected_format_reports_the_guesses(tmp_path: Path) -> None:
    path = tmp_path / "free.txt"
    path.write_text("just some words here\n" * 30, encoding="utf-8")
    with pytest.raises(FormatDetectionError) as caught:
        detect_format([str(path)])
    error = caught.value
    assert error.path == str(path)
    assert len(error.guesses) == 3
    assert all(0.0 <= share <= 1.0 for _name, share in error.guesses)
    assert str(error).startswith(f"could not detect the log format of '{path}' (best guesses: ")
    assert error.hint is not None
    assert "plain" in error.hint


def test_read_error_shows_the_reason_once() -> None:
    error = read_error("C:\\logs\\app.log", FileNotFoundError(2, "No such file or directory"))
    assert isinstance(error, SourceError)
    assert str(error) == "cannot read 'C:\\logs\\app.log': no such file"


def test_read_error_ignores_the_localized_system_text() -> None:
    error = read_error("x.log", PermissionError(13, "Zugriff verweigert"))
    assert str(error) == "cannot read 'x.log': permission denied"


def test_read_error_keeps_a_reason_text_it_did_not_get_from_the_system() -> None:
    error = read_error("x.gz", OSError("Not a gzipped file (b'ab')"))
    assert str(error) == "cannot read 'x.gz': Not a gzipped file (b'ab')"


def test_the_library_raises_the_new_errors() -> None:
    with pytest.raises(UnknownFormatError):
        logfold.analyze("x.log", format="nope")
    with pytest.raises(logfold.SourceError, match=r"cannot read '.*missing\.log': no such file"):
        logfold.analyze("missing.log", format="plain")


def _samples() -> list[LogfoldError]:
    return [
        ConfigError("bad value", hint="try another"),
        SourceError("cannot read 'x': no such file"),
        UnknownFormatError("nginxx", ["nginx", "app"]),
        UnknownReporterError("jsno", ["json", "csv"]),
        UnknownMatcherError("exat", ["exact"]),
        FormatDetectionError("p.log", (("plain", 0.5), ("jsonl", 0.0))),
        UnknownSuffixError("report", [".html", ".csv"]),
        NoLevelsError("nginx"),
    ]


@pytest.mark.parametrize("error", _samples(), ids=lambda error: type(error).__name__)
@pytest.mark.parametrize("clone", [lambda error: pickle.loads(pickle.dumps(error)), copy.copy, copy.deepcopy])
def test_errors_survive_pickle_and_copy(error: LogfoldError, clone) -> None:
    again = clone(error)
    assert type(again) is type(error)
    assert str(again) == str(error)
    assert again.hint == error.hint
    assert again.__dict__ == error.__dict__


def test_unknown_suffix_error_names_the_suffixes_and_keeps_its_base() -> None:
    error = UnknownSuffixError("out/report.xyz", [".html", ".csv"])
    assert isinstance(error, ConfigError)
    assert error.suffixes == (".csv", ".html")
    assert str(error) == "cannot choose a report format for 'out/report.xyz': the suffix '.xyz' is not known"
    assert error.hint is not None
    assert ".csv, .html" in error.hint
    assert "it has no suffix" in str(UnknownSuffixError("report", [".html"]))


def test_no_levels_error_names_the_format() -> None:
    error = NoLevelsError("nginx")
    assert isinstance(error, ConfigError)
    assert str(error) == "cannot filter by level: the nginx format gives no levels"
    assert error.format == "nginx"
    assert error.hint is not None


def test_write_error_gives_a_fixed_reason_for_the_usual_failures() -> None:
    assert str(write_error("a/b.html", FileNotFoundError(2, "Das System kann nicht"))) == (
        "cannot write 'a/b.html': the folder does not exist"
    )
    assert str(write_error("x", PermissionError(13, "Zugriff verweigert"))) == "cannot write 'x': permission denied"
    assert str(write_error("x", IsADirectoryError(21, "Is a directory"))) == "cannot write 'x': is a directory"
    assert str(write_error("x", OSError(28, "No space left on device"))) == "cannot write 'x': No space left on device"
    assert isinstance(write_error("x", OSError("boom")), SourceError)

"""The rules matcher: pairs written by the user in a file, from the file to a diff."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import logfold
from logfold.api.matching import resolve_matcher
from logfold.cli import exit_codes
from logfold.cli.app import app
from logfold.errors import ConfigError
from logfold.plugins import matchers
from logfold.plugins.matchers import RulesMatcher, load_rules

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})

RULE = "WARN retry failed after <NUM> attempts <=> WARN retry gave up after <NUM> attempts"


def rules_file(tmp_path: Path, text: str, name: str = "rules.txt") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def runs(tmp_path: Path) -> tuple[Path, Path]:
    steady = [f"INFO request {i} served" for i in range(30)]
    before = tmp_path / "before.log"
    after = tmp_path / "after.log"
    before.write_text("\n".join([*steady, *(f"WARN retry failed after {i} attempts" for i in range(8))]) + "\n")
    after.write_text("\n".join([*steady, *(f"WARN retry gave up after {i} attempts" for i in range(8))]) + "\n")
    return before, after


def test_the_file_has_one_rule_per_line_with_comments_and_blank_lines(tmp_path: Path) -> None:
    bom = "\N{ZERO WIDTH NO-BREAK SPACE}"
    path = rules_file(tmp_path, f"{bom}# renamed in 4.2\n\n  {RULE}  \n   # another\na b <=> c d\n")
    assert load_rules(path) == [
        ("WARN retry failed after <NUM> attempts", "WARN retry gave up after <NUM> attempts"),
        ("a b", "c d"),
    ]


@pytest.mark.parametrize(
    ("text", "line"),
    [("no separator here\n", 1), (f"{RULE}\n <=> only right\n", 2), (f"{RULE}\nleft only <=> \n", 2)],
)
def test_a_line_that_is_not_a_rule_names_the_file_and_the_line(tmp_path: Path, text: str, line: int) -> None:
    path = rules_file(tmp_path, text)
    with pytest.raises(ConfigError, match=rf"rules\.txt:{line}:"):
        load_rules(path)


def test_an_unreadable_or_oversized_file_is_a_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="cannot read the rules file"):
        load_rules(tmp_path / "missing.txt")
    binary = tmp_path / "binary.txt"
    binary.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ConfigError, match="cannot read the rules file"):
        load_rules(binary)
    monkeypatch.setattr(matchers, "MAX_RULES_BYTES", 10)
    with pytest.raises(ConfigError, match="larger than"):
        load_rules(rules_file(tmp_path, RULE))


def test_the_name_alone_needs_a_file_and_the_prefix_reads_one(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="needs a file") as raised:
        resolve_matcher("rules")
    assert raised.value.hint is not None
    assert "rules:FILE" in raised.value.hint
    matcher = resolve_matcher(f"rules:{rules_file(tmp_path, RULE)}")
    assert isinstance(matcher, RulesMatcher)
    assert len(matcher.rules) == 1


@pytest.mark.parametrize("engine", ["native", "python"])
def test_diff_pairs_the_reworded_message_with_the_rule_and_not_without_it(
    runs: tuple[Path, Path], tmp_path: Path, engine: str
) -> None:
    path = rules_file(tmp_path, RULE)
    exact = logfold.diff(*map(str, runs), format="plain", engine=engine, matcher="exact", min_count=1)
    assert (len(exact.new_templates), len(exact.disappeared)) == (1, 1)
    paired = logfold.diff(*map(str, runs), format="plain", engine=engine, matcher=f"rules:{path}", min_count=1)
    assert paired.config.matcher == f"rules:{path}"
    assert (len(paired.new_templates), len(paired.disappeared)) == (0, 0)


def test_a_bad_rules_file_fails_before_any_log_is_read(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="rules file"):
        logfold.diff(str(tmp_path / "a.log"), str(tmp_path / "b.log"), matcher=f"rules:{tmp_path / 'none.txt'}")


def test_the_cli_takes_the_rules_file_and_reports_a_bad_one(runs: tuple[Path, Path], tmp_path: Path) -> None:
    path = rules_file(tmp_path, RULE)
    ok = runner.invoke(
        app, ["diff", *map(str, runs), "-f", "plain", "--matcher", f"rules:{path}", "-q", "--min-count", "1"]
    )
    assert ok.exit_code == 0, ok.output
    bad = runner.invoke(
        app, ["diff", *map(str, runs), "-f", "plain", "--matcher", "rules:" + str(tmp_path / "none.txt")]
    )
    assert bad.exit_code == exit_codes.ERROR
    assert "rules file" in bad.stderr
    bare = runner.invoke(app, ["diff", *map(str, runs), "-f", "plain", "--matcher", "rules"])
    assert bare.exit_code == exit_codes.ERROR
    assert "rules:FILE" in bare.stderr

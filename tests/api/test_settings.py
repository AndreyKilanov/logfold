"""The settings file ``logfold.toml``: what it may hold, how it is found, and how the library uses it."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

import logfold
from corpora import app_lines, write
from logfold import ConfigError, Settings, load_config
from logfold.config import DEFAULT_MASKS, DiffConfig, ExecutionConfig, MaskRule, MiningConfig
from logfold.settings import MAX_CONFIG_BYTES, find_config, read_settings

FULL = """
format = "app"
multiline = false

[mining]
depth = 5
sim_th = 0.5
max_children = 50
max_templates = 2000
masks = "none"

[execution]
strategy = "sequential"
threads = 2
chunk_mb = 8
warm_start = true

[output]
top = 7
examples = "masked"
report = "markdown"
level = "warn"
only_alerts = true

[analyze]
min_count = 3

[diff]
threshold_ratio = 3.0
min_count = 5
min_new_count = 2
significance = 0.05
matcher = "overlap"
recount = false
fail_on_new = true
fail_on_new_alerts = true
"""


@pytest.fixture(autouse=True)
def no_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOGFOLD_CONFIG", raising=False)


def settings_file(folder: Path, text: str) -> Path:
    path = folder / "logfold.toml"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def test_a_full_file_is_read_into_typed_settings(tmp_path: Path) -> None:
    settings = read_settings(settings_file(tmp_path, FULL))
    assert settings.format == "app"
    assert settings.multiline is False
    assert settings.mining == MiningConfig(depth=5, sim_th=0.5, max_children=50, max_templates=2000, masks=())
    assert settings.execution == ExecutionConfig(strategy="sequential", threads=2, chunk_bytes=8 << 20, warm_start=True)
    assert settings.diff == DiffConfig(
        threshold_ratio=3.0, min_count=5, min_new_count=2, significance=0.05, matcher="overlap", recount=False
    )
    assert (settings.top, settings.examples, settings.report, settings.level, settings.only_alerts) == (
        7,
        "masked",
        "markdown",
        "warn",
        True,
    )
    assert (settings.analyze_min_count, settings.fail_on_new, settings.fail_on_new_alerts) == (3, True, True)
    assert settings.source == str(tmp_path / "logfold.toml")


def test_an_empty_file_and_no_file_both_give_the_defaults(tmp_path: Path) -> None:
    assert dataclasses.replace(read_settings(settings_file(tmp_path, "")), source=None) == Settings()
    assert load_config() == Settings()


def test_the_masks_can_be_default_none_or_your_own_rules(tmp_path: Path) -> None:
    default = read_settings(settings_file(tmp_path, '[mining]\nmasks = "default"\n'))
    assert default.mining.masks == DEFAULT_MASKS
    own = read_settings(
        settings_file(
            tmp_path,
            '[[mining.masks]]\nname = "order"\npattern = "ORD-[0-9]+"\ntoken = "<ORDER>"\n'
            '[[mining.masks]]\nname = "id"\npattern = "[0-9a-f]{8}"\ntoken = "<ID>"\nascii = true\n',
        )
    )
    assert own.mining.masks == (MaskRule("order", "ORD-[0-9]+", "<ORDER>"), MaskRule("id", "[0-9a-f]{8}", "<ID>", True))


@pytest.mark.parametrize(
    ("text", "message", "hint"),
    [
        ("formt = 'app'\n", "unknown key 'formt'", "did you mean 'format'?"),
        ("[mining]\ndepht = 4\n", "unknown key 'depht' in [mining]", "did you mean 'depth'?"),
        ("[minning]\ndepth = 4\n", "unknown key 'minning'", "did you mean 'mining'?"),
        ("[diff]\nsignificanse = 0.1\n", "unknown key 'significanse' in [diff]", "did you mean 'significance'?"),
        ("[mining]\nqqqq = 1\n", "unknown key 'qqqq'", "known: "),
        ("[execution]\nengine = 'native'\n", "unknown key 'engine'", None),
        ("plugins_dir = '/tmp/x'\n", "unknown key 'plugins_dir'", None),
        ("[mining.masks]\nname = 'x'\n", "unknown key 'masks'", None),
    ],
)
def test_an_unknown_key_names_the_file_and_the_closest_known_one(
    tmp_path: Path, text: str, message: str, hint: str | None
) -> None:
    path = settings_file(tmp_path, text)
    with pytest.raises(ConfigError) as caught:
        read_settings(path)
    assert str(path) in str(caught.value)
    assert message in str(caught.value) or "mining.masks" in str(caught.value)
    if hint is not None:
        assert hint in (caught.value.hint or "")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[mining]\nsim_th = 'high'\n", "'mining.sim_th' must be a number, found 'high'"),
        ("[mining]\ndepth = true\n", "'mining.depth' must be an integer"),
        ("[mining]\ndepth = 2\n", "'mining.depth' must be an integer of at least 3"),
        ("[mining]\nmasks = 3\n", "'mining.masks' must be"),
        ("[mining]\nmasks = 'some'\n", "'mining.masks' must be"),
        ("[[mining.masks]]\nname = 'x'\n", "needs pattern, token"),
        ("[execution]\nstrategy = 'fast'\n", "'execution.strategy' must be one of 'auto', 'sequential', 'chunked'"),
        ("[output]\nexamples = 'all'\n", "'output.examples' must be one of"),
        ("[execution]\nthreads = 100000\n", "'execution.threads' must be an integer of at most 1024"),
        ("[output]\ntop = 0\n", "'output.top' must be an integer of at least 1"),
        ("[diff]\nsignificance = 0\n", "[diff] significance must be greater than 0"),
        ("[diff]\nrecount = 'yes'\n", "'diff.recount' must be true or false"),
        ("format = 3\n", "'format' must be a string"),
        ("multiline = 'yes'\n", "'multiline' must be true or false"),
        ("diff = 3\n", "'diff' must be a table"),
    ],
)
def test_a_wrong_type_or_value_says_what_was_expected(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ConfigError) as caught:
        read_settings(settings_file(tmp_path, text))
    assert message in str(caught.value)


def test_a_file_that_cannot_be_used_is_an_error_not_a_crash(tmp_path: Path) -> None:
    deep = "a = " + "[" * 40000 + "]" * 40000 + "\n"
    cases = {
        "huge.toml": b"# " + b"x" * (MAX_CONFIG_BYTES + 1),
        "binary.toml": bytes(range(256)) * 4,
        "latin.toml": "format = 'café'\n".encode("latin-1"),
        "broken.toml": b"[mining\ndepth = \n",
        "deep.toml": deep.encode("ascii"),
        "bom-less-utf16.toml": "format = 'app'\n".encode("utf-16"),
    }
    for name, content in cases.items():
        path = tmp_path / name
        path.write_bytes(content)
        with pytest.raises(ConfigError):
            read_settings(path)
    with pytest.raises(ConfigError, match="cannot read"):
        read_settings(tmp_path / "missing.toml")
    with pytest.raises(ConfigError, match="cannot read"):
        read_settings(tmp_path)


def test_the_search_goes_up_to_the_repository_root_and_no_further(tmp_path: Path) -> None:
    outside = settings_file(tmp_path, "")
    repository = tmp_path / "repo"
    work = repository / "services" / "api"
    work.mkdir(parents=True)
    (repository / ".git").mkdir()
    assert find_config(work) is None, "the file above the repository root is not used"
    inner = settings_file(repository, "")
    assert find_config(work) == inner
    nearest = settings_file(work, "")
    assert find_config(work) == nearest
    assert find_config(tmp_path) == outside


def test_a_named_file_beats_the_search_and_the_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = tmp_path / "here"
    here.mkdir()
    settings_file(here, "[output]\ntop = 1\n")
    monkeypatch.chdir(here)
    assert load_config().top == 1
    named = tmp_path / "named.toml"
    named.write_text("[output]\ntop = 2\n", encoding="utf-8")
    monkeypatch.setenv("LOGFOLD_CONFIG", str(named))
    assert load_config().top == 2
    explicit = tmp_path / "explicit.toml"
    explicit.write_text("[output]\ntop = 3\n", encoding="utf-8")
    assert load_config(explicit).top == 3
    monkeypatch.setenv("LOGFOLD_CONFIG", str(tmp_path / "missing.toml"))
    with pytest.raises(ConfigError, match="cannot read"):
        load_config()


def test_the_defaults_of_the_command_line_follow_the_file(tmp_path: Path) -> None:
    defaults = read_settings(settings_file(tmp_path, FULL)).command_defaults()
    assert defaults["analyze"] == defaults["match"]
    assert defaults["analyze"] == {
        "format": "app",
        "multiline": False,
        "top": 7,
        "examples": "masked",
        "report": "markdown",
        "level": "warn",
        "only_alerts": True,
        "min_count": 3,
    }
    assert defaults["diff"]["threshold_ratio"] == 3.0
    assert defaults["diff"]["recount"] is False
    assert defaults["diff"]["fail_on_new"] is True
    assert defaults["diff"]["min_count"] == 5
    assert defaults["inspect"] == {"format": "app", "multiline": False}
    assert read_settings(settings_file(tmp_path, "[mining]\ndepth = 4\n")).command_defaults()["diff"] == {}


def test_the_settings_give_the_same_result_as_the_same_arguments(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", app_lines(1500, 3))
    settings = read_settings(settings_file(tmp_path, '[mining]\nsim_th = 0.6\nmasks = "none"\n'))
    from_file = logfold.analyze(str(log), format="app", config=settings)
    from_arguments = logfold.analyze(str(log), format="app", sim_th=0.6, masks=[])
    assert [(t.id, t.count) for t in from_file.templates] == [(t.id, t.count) for t in from_arguments.templates]
    assert from_file.meta.config_hash == from_arguments.meta.config_hash


def test_an_argument_of_the_call_beats_the_settings(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", app_lines(800, 3))
    settings = read_settings(settings_file(tmp_path, 'format = "plain"\n[mining]\nsim_th = 0.9\n'))
    assert logfold.analyze(str(log), config=settings).meta.format == "plain"
    named = logfold.analyze(str(log), format="app", sim_th=0.4, config=settings)
    assert named.meta.format == "app"
    assert named.meta.config_hash == logfold.analyze(str(log), format="app").meta.config_hash


def test_the_comparison_settings_reach_diff(tmp_path: Path) -> None:
    before = write(tmp_path / "before.log", app_lines(600, 3))
    after = write(tmp_path / "after.log", app_lines(600, 3) + ["2026-10-05T00:00:00Z ERROR brand new failure z9"] * 30)
    strict = read_settings(settings_file(tmp_path, "[diff]\nmin_new_count = 100\n"))
    assert logfold.diff(str(before), str(after), format="app", config=strict).new_templates == ()
    assert logfold.diff(str(before), str(after), format="app").new_templates != ()


def test_settings_with_a_saved_state_must_match_the_state(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", app_lines(500, 3))
    settings = read_settings(settings_file(tmp_path, "[mining]\nsim_th = 0.6\n"))
    logfold.analyze(str(log), format="app", config=settings, save_state=tmp_path / "s.json")
    assert logfold.match(tmp_path / "s.json", str(log), format="app", config=settings).run.records == 500
    with pytest.raises(logfold.StateError, match="other masks or parameters"):
        logfold.match(tmp_path / "s.json", str(log), format="app")


def test_the_schema_and_the_parser_know_the_same_keys(tmp_path: Path) -> None:
    import json

    import jsonschema

    from logfold.settings import _SECTIONS, _TOP

    schema = json.loads((Path(__file__).parents[2] / "docs" / "schema" / "config.schema.json").read_text("utf-8"))
    assert set(schema["properties"]) == {*_TOP, *_SECTIONS}
    for section, spec in _SECTIONS.items():
        assert set(schema["properties"][section]["properties"]) == set(spec), section
    import tomllib

    jsonschema.Draft202012Validator(schema).validate(tomllib.loads(FULL))
    read_settings(settings_file(tmp_path, FULL))

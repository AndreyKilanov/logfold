"""``delimiters``: the characters that separate tokens, from the library, the settings file and the command line."""

from __future__ import annotations

from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from corpora import write
from logfold import ConfigError, MiningConfig, StateError

pytestmark = requires_native

STREAM = [f"conn user_id={n} session=s{n % 3}" for n in range(30)]
WITH_PUNCTUATION = " \t\n\r_="
SPLIT = "conn user id <*> session <*>"


def texts(result: logfold.AnalysisResult) -> set[str]:
    return {template.text for template in result.templates}


def test_added_delimiters_split_tokens_that_the_whitespace_does_not() -> None:
    plain = logfold.Miner(masks=[])
    plain.add_many(STREAM)
    split = logfold.Miner(masks=[], delimiters=WITH_PUNCTUATION)
    split.add_many(STREAM)
    assert texts(split.result()) == {SPLIT}
    assert len(texts(plain.result())) > 1


def test_the_argument_beats_the_configuration_and_the_default_is_whitespace() -> None:
    assert MiningConfig().delimiters == " \t\n\r"
    miner = logfold.Miner(mining=MiningConfig(delimiters=","), delimiters=WITH_PUNCTUATION, masks=[])
    miner.add_many(STREAM)
    assert texts(miner.result()) == {SPLIT}


@pytest.mark.parametrize("value", ["", "naïve"])
def test_a_value_that_is_empty_or_not_ascii_is_refused(value: str) -> None:
    with pytest.raises(ConfigError, match="delimiters"):
        logfold.Miner(delimiters=value)


def test_analyze_and_match_read_the_delimiters(tmp_path: Path) -> None:
    log = write(tmp_path / "kv.log", STREAM)
    result = logfold.analyze(str(log), format="plain", masks=[], delimiters=WITH_PUNCTUATION)
    assert texts(result) == {SPLIT}
    state = tmp_path / "model.json"
    logfold.analyze(str(log), format="plain", masks=[], delimiters=WITH_PUNCTUATION, save_state=state)
    matched = logfold.match(state, str(log), format="plain", masks=[], delimiters=WITH_PUNCTUATION)
    assert matched.run.unmatched is not None
    assert matched.run.unmatched.records == 0


def test_a_state_mined_with_other_delimiters_is_refused(tmp_path: Path) -> None:
    log = write(tmp_path / "kv.log", STREAM)
    state = tmp_path / "model.json"
    logfold.analyze(str(log), format="plain", masks=[], delimiters=WITH_PUNCTUATION, save_state=state)
    with pytest.raises(StateError):
        logfold.match(state, str(log), format="plain", masks=[])
    with pytest.raises(StateError):
        logfold.analyze(str(log), format="plain", masks=[], delimiters=" ", load_state=state)
    with pytest.raises(StateError):
        logfold.Miner(masks=[], load_state=state)


def test_the_settings_file_gives_the_delimiters_and_a_wrong_value_is_refused(tmp_path: Path) -> None:
    config = tmp_path / "logfold.toml"
    config.write_text('[mining]\ndelimiters = " \\t\\n\\r_="\nmasks = "none"\n', encoding="utf-8")
    settings = logfold.load_config(config)
    assert settings.mining.delimiters == WITH_PUNCTUATION
    miner = logfold.Miner(config=settings)
    miner.add_many(STREAM)
    assert texts(miner.result()) == {SPLIT}
    for body in ('delimiters = ""', 'delimiters = "é"', "delimiters = 5"):
        config.write_text(f"[mining]\n{body}\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="delimiters"):
            logfold.load_config(config)


def test_the_values_of_a_message_need_the_space_among_the_delimiters() -> None:
    found = logfold.extract_parameters(SPLIT, "conn user_id=7 session=z", delimiters=WITH_PUNCTUATION)
    assert found is not None
    assert [p.value for p in found] == ["7", "z"]
    with pytest.raises(ConfigError, match="space"):
        logfold.extract_parameters("a b", "a b", delimiters=",")

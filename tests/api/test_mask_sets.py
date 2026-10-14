"""Mask sets: validation, files, selection, the built-in sets and the state that remembers them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from corpora import app_lines, nginx_lines, write
from logfold import ConfigError, MaskRule, MaskSet, StateError
from logfold.config import DEFAULT_MASKS, MiningConfig, config_fingerprint
from logfold.errors import UnknownMaskSetError
from logfold.ext import (
    get_mask_set,
    load_mask_set,
    mask_fingerprint,
    mask_set_names,
    register_mask_set,
    resolve_masks,
)
from logfold.ext.mask_sets import MAX_FILE_BYTES, MAX_RULES

RULE = MaskRule("order", r"\bORD-[0-9]{6}\b", "<ORDER>", True)


def make(**changes: object) -> MaskSet:
    fields: dict[str, object] = {"name": "orders", "rules": (RULE,)}
    fields.update(changes)
    return MaskSet(**fields)  # type: ignore[arg-type]


def test_a_valid_set_keeps_its_rules_and_has_a_stable_fingerprint() -> None:
    mask_set = make(version=3, description="orders")
    assert mask_set.rules == (RULE,)
    assert mask_set.fingerprint == mask_fingerprint([RULE])
    assert mask_set.fingerprint != mask_fingerprint([MaskRule("order", r"\bORD-[0-9]{7}\b", "<ORDER>", True)])
    assert MaskSet.from_dict(mask_set.to_dict()) == mask_set


def test_a_list_of_rules_is_stored_as_a_tuple() -> None:
    assert make(rules=[RULE]).rules == (RULE,)


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "Orders"},
        {"name": ""},
        {"name": "9orders"},
        {"name": "a" * 33},
        {"version": 0},
        {"version": "1"},
        {"rules": ()},
        {"rules": (RULE, RULE)},
        {"rules": (MaskRule("Order", "x", "<ORDER>", True),)},
        {"rules": (MaskRule("o", "x", "ORDER", True),)},
        {"rules": (MaskRule("o", "x", "<order>", True),)},
        {"rules": (MaskRule("o", "x", "<*>", True),)},
        {"rules": (MaskRule("o", "x", "<" + "A" * 31 + ">", True),)},
        {"rules": (MaskRule("o", "(", "<O>", True),)},
        {"rules": (MaskRule("o", "x*", "<O>", True),)},
        {"rules": (MaskRule("o", "a" * 4097, "<O>", True),)},
        {"rules": tuple(MaskRule(f"r{i}", f"x{i}", "<R>", True) for i in range(MAX_RULES + 1))},
        {"rules": ("not a rule",)},
    ],
)
def test_an_invalid_set_is_refused(changes: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        make(**changes)


def test_the_largest_valid_set_is_accepted() -> None:
    rules = tuple(MaskRule(f"r{i}", f"x{i}y", "<R>", True) for i in range(MAX_RULES))
    assert len(make(rules=rules).rules) == MAX_RULES


def test_an_unknown_check_is_refused() -> None:
    with pytest.raises(ConfigError, match="unknown check"):
        MaskRule("card", r"\d{16}", "<CARD>", True, "crc32")


def write_set(path: Path, **changes: object) -> Path:
    data: dict[str, object] = {
        "name": "orders",
        "rules": [{"name": "order", "pattern": r"\bORD-\d+\b", "token": "<ORDER>"}],
    }
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_set_file_is_read_and_its_name_comes_from_the_name_key(tmp_path: Path) -> None:
    mask_set = load_mask_set(write_set(tmp_path / "anything.json", version=2, description="d"))
    assert (mask_set.name, mask_set.version, mask_set.description) == ("orders", 2, "d")
    assert mask_set.rules == (MaskRule("order", r"\bORD-\d+\b", "<ORDER>", True, None),)


def test_ascii_defaults_to_true_in_a_file_and_can_be_switched_off(tmp_path: Path) -> None:
    rule = {"name": "order", "pattern": r"\bORD-\d+\b", "token": "<ORDER>", "ascii": False, "check": "luhn"}
    mask_set = load_mask_set(write_set(tmp_path / "s.json", rules=[rule]))
    assert mask_set.rules[0].ascii is False
    assert mask_set.rules[0].check == "luhn"


@pytest.mark.parametrize(
    "changes",
    [
        {"extra": 1},
        {"rules": "no"},
        {"rules": [1]},
        {"rules": [{"name": "o", "pattern": "x", "token": "<O>", "other": 1}]},
        {"rules": [{"name": "o", "pattern": 5, "token": "<O>"}]},
        {"rules": [{"name": "o", "pattern": "x", "token": "<O>", "ascii": "yes"}]},
        {"rules": [{"name": "o", "pattern": "x", "token": "<O>", "check": "md5"}]},
        {"description": 5},
        {"version": "two"},
        {"rules": [{"name": "o", "pattern": "x", "token": "<O>"}] * (MAX_RULES + 1)},
    ],
)
def test_a_bad_set_file_is_a_config_error_that_names_the_file(tmp_path: Path, changes: dict[str, object]) -> None:
    path = write_set(tmp_path / "bad.json", **changes)
    with pytest.raises(ConfigError, match=r"bad\.json"):
        load_mask_set(path)


def test_a_file_that_cannot_be_used_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_mask_set(tmp_path / "missing.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_mask_set(broken)
    listing = tmp_path / "list.json"
    listing.write_text("[]", encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON object"):
        load_mask_set(listing)
    missing = tmp_path / "nothing.json"
    missing.write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigError, match="'name' is missing"):
        load_mask_set(missing)


def test_a_file_over_the_size_limit_is_refused_and_a_deep_one_does_not_crash(tmp_path: Path) -> None:
    huge = tmp_path / "huge.json"
    huge.write_text(json.dumps({"name": "huge", "description": "x" * MAX_FILE_BYTES, "rules": []}), encoding="utf-8")
    with pytest.raises(ConfigError, match="at most"):
        load_mask_set(huge)
    deep = tmp_path / "deep.json"
    deep.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_mask_set(deep)


def test_the_built_in_sets_are_registered_and_valid() -> None:
    assert {"default", "secrets", "pii"} <= set(mask_set_names())
    assert get_mask_set("default").rules == DEFAULT_MASKS
    for name in ("secrets", "pii"):
        mask_set = get_mask_set(name)
        assert mask_set.name == name
        assert mask_set.rules
        assert all(rule.ascii for rule in mask_set.rules)


def test_the_built_in_sets_are_pinned() -> None:
    """Changing a rule changes the fingerprint that saved states hold: raise the version of the set on purpose."""
    pinned = {
        ("secrets", 1): "3345d8c81c371a62",
        ("pii", 1): "7a842376b3f63543",
        ("default", 1): "df12bc959ae1bfe2",
    }
    found = {
        (name, get_mask_set(name).version): get_mask_set(name).fingerprint for name in ("secrets", "pii", "default")
    }
    assert found == pinned


def test_an_unknown_set_name_lists_the_known_ones_and_suggests_one() -> None:
    with pytest.raises(UnknownMaskSetError) as caught:
        get_mask_set("secret")
    assert "secrets" in str(caught.value)
    assert caught.value.hint is not None
    assert "secrets" in caught.value.hint


def test_a_registered_set_can_be_selected_by_name() -> None:
    register_mask_set(make(name="orders-test"))
    try:
        assert resolve_masks(["orders-test"]) == (RULE, *DEFAULT_MASKS)
    finally:
        from logfold.ext import registry

        registry._mask_sets.pop("orders-test", None)


def test_a_list_of_rules_replaces_the_defaults() -> None:
    assert resolve_masks([RULE]) == (RULE,)
    assert resolve_masks([]) == ()
    assert resolve_masks(DEFAULT_MASKS) == DEFAULT_MASKS


def test_sets_go_before_the_default_rules_in_the_order_given() -> None:
    secrets, pii = get_mask_set("secrets"), get_mask_set("pii")
    assert resolve_masks(["secrets", "pii"]) == (*secrets.rules, *pii.rules, *DEFAULT_MASKS)
    assert resolve_masks(["pii", secrets]) == (*pii.rules, *secrets.rules, *DEFAULT_MASKS)
    assert resolve_masks("pii") == (*pii.rules, *DEFAULT_MASKS)
    assert resolve_masks(make()) == (RULE, *DEFAULT_MASKS)


def test_the_default_name_changes_nothing_and_a_repeated_set_counts_once() -> None:
    assert resolve_masks(["default"]) == DEFAULT_MASKS
    assert resolve_masks(["secrets", "default", "secrets"]) == resolve_masks(["secrets"])


def test_no_default_leaves_the_default_rules_out() -> None:
    assert resolve_masks(["pii"], no_default=True) == get_mask_set("pii").rules


def test_rules_and_sets_cannot_be_mixed_and_the_total_is_limited() -> None:
    with pytest.raises(ConfigError, match="mixes"):
        resolve_masks([RULE, "secrets"])
    with pytest.raises(ConfigError, match="MaskSet or a name"):
        resolve_masks([5])  # type: ignore[list-item]
    big = [
        make(name=f"s{i}", rules=tuple(MaskRule(f"r{j}", f"x{i}y{j}", "<R>", True) for j in range(100)))
        for i in range(3)
    ]
    with pytest.raises(ConfigError, match="at most"):
        resolve_masks(big)


def test_the_fingerprint_of_the_default_masks_is_not_changed_by_the_new_check_field() -> None:
    assert config_fingerprint(MiningConfig()) == config_fingerprint(MiningConfig(masks=DEFAULT_MASKS))
    with_check = MiningConfig(masks=(MaskRule("c", "x", "<C>", True, "luhn"),))
    without = MiningConfig(masks=(MaskRule("c", "x", "<C>", True),))
    assert config_fingerprint(with_check) != config_fingerprint(without)


pytestmark_native = requires_native


@requires_native
def test_a_selected_set_masks_what_the_default_rules_leave(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", ["user bob@example.com paid with 4111 1111 1111 1111"] * 3)
    plain = logfold.analyze(str(log), format="plain", engine="native")
    assert plain.templates[0].text == "user bob@example.com paid with <NUM> <NUM> <NUM> <NUM>"
    masked = logfold.analyze(str(log), format="plain", engine="native", masks=["pii"])
    assert masked.templates[0].text == "user <EMAIL> paid with <CARD>"
    assert masked.run.records == 3


@requires_native
def test_sets_given_as_objects_and_as_a_file_work_like_names(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", ["order ORD-123456 shipped"] * 2)
    from_object = logfold.analyze(str(log), format="plain", engine="native", masks=[make()])
    from_file = logfold.analyze(
        str(log), format="plain", engine="native", masks=[load_mask_set(write_set(tmp_path / "o.json"))]
    )
    assert from_object.templates[0].text == from_file.templates[0].text == "order <ORDER> shipped"
    assert from_object.meta.config_hash != logfold.analyze(str(log), format="plain", engine="native").meta.config_hash


@requires_native
def test_the_default_masks_stay_the_default_without_a_selection(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", app_lines(200) + nginx_lines(200))
    first = logfold.analyze(str(log), format="plain", engine="native")
    again = logfold.analyze(str(log), format="plain", engine="native", masks=list(DEFAULT_MASKS))
    assert first.meta.config_hash == again.meta.config_hash
    assert [(t.text, t.count) for t in first.templates] == [(t.text, t.count) for t in again.templates]


@requires_native
def test_logs_without_secrets_are_not_changed_by_the_built_in_sets(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", app_lines(400) + nginx_lines(400))
    plain = logfold.analyze(str(log), format="plain", engine="native")
    masked = logfold.analyze(str(log), format="plain", engine="native", masks=["secrets", "pii"])
    assert [(t.text, t.count) for t in plain.templates] == [(t.text, t.count) for t in masked.templates]


@requires_native
def test_a_state_is_refused_when_the_masks_differ(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", ["login ok user bob@example.com"] * 5)
    state = tmp_path / "model.json"
    logfold.analyze(str(log), format="plain", engine="native", masks=["pii"], save_state=state)
    again = logfold.analyze(str(log), format="plain", engine="native", masks=["pii"], load_state=state)
    assert again.run.records == 5
    with pytest.raises(StateError):
        logfold.analyze(str(log), format="plain", engine="native", load_state=state)
    with pytest.raises(StateError):
        logfold.analyze(str(log), format="plain", engine="native", masks=["secrets"], load_state=state)


@requires_native
def test_the_state_header_names_the_masks_by_their_fingerprint(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", ["login ok user bob@example.com"] * 3)
    default_state, pii_state = tmp_path / "d.json", tmp_path / "p.json"
    logfold.analyze(str(log), format="plain", engine="native", save_state=default_state)
    logfold.analyze(str(log), format="plain", engine="native", masks=["pii"], save_state=pii_state)
    header = lambda path: json.loads(path.read_text(encoding="utf-8").splitlines()[0])  # noqa: E731
    assert header(default_state)["masks"] == "default"
    assert header(pii_state)["masks"] == mask_fingerprint(resolve_masks(["pii"]))


@requires_native
def test_the_miner_and_match_take_names_too(tmp_path: Path) -> None:
    miner = logfold.Miner(format="plain", masks=["pii"])
    miner.add_many(["user bob@example.com ok", "user alice@example.com ok"])
    assert [t.text for t in miner.result().templates] == ["user <EMAIL> ok"]
    log = write(tmp_path / "a.log", ["user bob@example.com ok"] * 2)
    state = tmp_path / "model.json"
    logfold.analyze(str(log), format="plain", engine="native", masks=["pii"], save_state=state)
    found = logfold.match(state, str(log), format="plain", masks=["pii"])
    assert found.run.unmatched.records == 0


@requires_native
def test_extract_parameters_names_the_rule_of_a_selected_set() -> None:
    values = logfold.extract_parameters("user <EMAIL> ok", "user bob@example.com ok", masks=["pii"])
    assert values is not None
    assert [(p.name, p.value) for p in values] == [("email", "bob@example.com")]


SET_SCHEMA = Path(__file__).parents[2] / "docs" / "schema" / "mask-set.schema.json"


def test_the_schema_and_the_loader_agree(tmp_path: Path) -> None:
    import jsonschema

    validator = jsonschema.Draft202012Validator(json.loads(SET_SCHEMA.read_text("utf-8")))
    for name in ("secrets", "pii"):
        validator.validate(get_mask_set(name).to_dict())
    good = {"name": "orders", "rules": [{"name": "order", "pattern": "ORD-[0-9]+", "token": "<ORDER>"}]}
    bad = [
        {**good, "extra": 1},
        {**good, "name": "Orders"},
        {**good, "rules": []},
        {**good, "version": 0},
        {**good, "rules": [{"name": "o", "pattern": "x", "token": "order"}]},
        {**good, "rules": [{"name": "o", "pattern": "x", "token": "<O>", "check": "crc"}]},
        {**good, "rules": [{"name": "o", "pattern": "x", "token": "<O>", "other": True}]},
        {"rules": good["rules"]},
    ]
    validator.validate(good)
    load_mask_set(write_set(tmp_path / "good.json"))
    for index, document in enumerate(bad):
        assert not validator.is_valid(document), document
        path = tmp_path / f"bad{index}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ConfigError):
            load_mask_set(path)


CATASTROPHIC = """
import logfold
from logfold import MaskRule, MaskSet

hostile = MaskSet("hostile", (MaskRule("trap", "(?:a|aa)+$", "<TRAP>", True),))
with open("trap.log", "w", encoding="utf-8") as stream:
    stream.write("job " + "a" * 60 + "b done" + chr(10))
result = logfold.analyze("trap.log", format="plain", engine="native", masks=[hostile], examples="masked")
print(result.templates[0].example)
"""
PYTHON_MASKER = """
from logfold import MaskRule
from logfold.ext.masks import ReferenceMasker

ReferenceMasker([MaskRule("trap", "(?:a|aa)+$", "<TRAP>", True)]).mask("job " + "a" * 60 + "b done")
"""


@requires_native
def test_a_pattern_that_backtracks_forever_in_python_cannot_hang_a_run(tmp_path: Path) -> None:
    import subprocess
    import sys

    with pytest.raises(subprocess.TimeoutExpired):  # the premise: Python's re does hang on this pattern
        subprocess.run([sys.executable, "-c", PYTHON_MASKER], timeout=3, capture_output=True, check=False)
    done = subprocess.run(
        [sys.executable, "-c", CATASTROPHIC], cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False
    )
    assert done.returncode == 0, done.stderr
    assert "a" * 60 in done.stdout

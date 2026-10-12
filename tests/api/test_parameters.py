"""``extract_parameters()``: the values that a message gives to the variable positions of a template."""

from __future__ import annotations

from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from corpora import app_lines, write
from logfold import ConfigError, MaskRule, MiningConfig, Parameter

pytestmark = requires_native

EXAMPLE_LIMIT = 2000  # an example is cut at 2000 bytes, so a longer message has fewer tokens than its template


def found(template: str, message: str, **options: object) -> list[tuple[int, str, str]] | None:
    result = logfold.extract_parameters(template, message, **options)  # type: ignore[arg-type]
    return None if result is None else [(p.position, p.name, p.value) for p in result]


def test_masked_values_are_named_by_their_rule_and_given_as_written() -> None:
    assert found("user <NUM> logged in from <IP>", "user 42 logged in from 10.0.0.1:8080") == [
        (1, "num", "42"),
        (5, "ip", "10.0.0.1:8080"),
    ]


def test_the_parameters_are_frozen_dataclasses() -> None:
    (parameter,) = logfold.extract_parameters("job <*>", "job nightly") or ()
    assert parameter == Parameter(position=1, name="*", value="nightly")
    with pytest.raises(AttributeError):
        parameter.value = "x"  # type: ignore[misc]


def test_a_generalized_position_gives_the_whole_token_and_a_wide_rule_one_parameter() -> None:
    assert found("<TS> job <*> done in <NUM>", "2026-10-04 12:00:01 job nightly done in 3.5") == [
        (0, "ts", "2026-10-04 12:00:01"),
        (2, "*", "nightly"),
        (5, "num", "3.5"),
    ]


def test_a_masked_value_inside_a_constant_token_is_one_parameter_and_inside_a_generalized_one_is_not_repeated() -> None:
    assert found("item id=<NUM> <*>", "item id=17 id=18") == [(1, "num", "17"), (2, "*", "id=18")]


@pytest.mark.parametrize(
    "message",
    ["user 42 logged out", "user 42 logged in now", "user", "", "user abc logged in"],
)
def test_a_message_that_does_not_fit_gives_none(message: str) -> None:
    assert found("user <NUM> logged in", message) is None


def test_a_template_without_variable_parts_gives_an_empty_tuple() -> None:
    assert logfold.extract_parameters("service started", "service started") == ()
    assert logfold.extract_parameters("", "") == ()


def test_a_template_of_a_result_can_be_given_instead_of_its_text() -> None:
    miner = logfold.Miner()
    miner.add_many(["user 1 in", "user 2 in"])
    (template,) = miner.result().templates
    assert found(template, "user 77 in") == [(1, "num", "77")]  # type: ignore[arg-type]


def test_masks_replace_the_defaults() -> None:
    order = MaskRule("order", r"ORD-\d+", "<ORDER>", True)
    assert found("paid <ORDER> by <*>", "paid ORD-9001 by card", masks=[order]) == [
        (1, "order", "ORD-9001"),
        (3, "*", "card"),
    ]
    assert found("paid <NUM>", "paid 5", masks=[]) is None
    assert found("paid <NUM>", "paid <NUM>", masks=[]) == []


def test_the_mining_configuration_and_the_settings_give_the_masks() -> None:
    none = MiningConfig(masks=())
    assert found("id 5 is <*>", "id 5 is fine", mining=none) == [(3, "*", "fine")]
    settings = logfold.Settings(mining=none)
    assert found("id 5 is <*>", "id 5 is fine", config=settings) == [(3, "*", "fine")]


def test_an_invalid_rule_is_a_config_error() -> None:
    with pytest.raises(ConfigError):
        logfold.extract_parameters("a <X>", "a b", masks=[MaskRule("bad", "(", "<X>")])


def test_non_ascii_values_and_lone_surrogates_are_kept_or_replaced() -> None:
    assert found("user <*> ok", "user Zo\u00eb\u4e2d ok") == [(1, "*", "Zo\u00eb\u4e2d")]
    assert found("user <*> ok", "user bad\udcff ok") == [(1, "*", "bad\ufffd")]


def test_a_miner_uses_its_own_masks() -> None:
    miner = logfold.Miner(masks=[MaskRule("order", r"ORD-\d+", "<ORDER>", True)])
    assert [(p.name, p.value) for p in miner.extract_parameters("paid <ORDER>", "paid ORD-7") or ()] == [
        ("order", "ORD-7")
    ]
    assert miner.extract_parameters("paid <NUM>", "paid 5") is None


def test_every_template_of_a_result_fits_its_example_with_one_parameter_per_variable_part(tmp_path: Path) -> None:
    log = write(tmp_path / "app.log", app_lines(3000, 8))
    result = logfold.analyze(str(log), format="plain", strategy="sequential")
    assert result.templates
    for template in result.templates:
        assert template.example is not None
        if len(template.example.encode()) >= EXAMPLE_LIMIT:
            continue
        parameters = logfold.extract_parameters(template, template.example)
        assert parameters is not None, template.text
        tokens = template.text.split(" ")
        variable = [token for token in tokens if token == "<*>"]
        assert sum(p.name == "*" for p in parameters) == len(variable)
        assert [p.position for p in parameters] == sorted(p.position for p in parameters)
        assert all(p.value and p.value in template.example for p in parameters)

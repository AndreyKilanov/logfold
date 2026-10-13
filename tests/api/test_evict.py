"""``on_full='evict'``: the least recently used templates make room for new ones, and the totals still add up."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

import logfold
from conftest import requires_native
from corpora import write
from logfold import ConfigError, MiningConfig, StateError

pytestmark = requires_native

SCHEMA = Path(__file__).parents[2] / "docs" / "schema" / "analysis-v1.schema.json"


def shapes(count: int) -> list[str]:
    return [f"shape{n}a shape{n}b shape{n}c" for n in range(count)]


def texts(result: logfold.AnalysisResult) -> set[str]:
    return {template.text for template in result.templates}


def test_a_miner_that_evicts_keeps_learning_and_a_miner_that_pools_does_not() -> None:
    evicting = logfold.Miner(max_templates=20, on_full="evict")
    pooling = logfold.Miner(max_templates=20)
    for miner in (evicting, pooling):
        miner.add_many(shapes(100))
    assert "shape99a shape99b shape99c" in texts(evicting.result())
    assert "shape99a shape99b shape99c" not in texts(pooling.result())
    assert "shape0a shape0b shape0c" in texts(pooling.result())
    assert "shape0a shape0b shape0c" not in texts(evicting.result())


def test_the_totals_add_up_and_the_run_says_how_many_templates_were_dropped() -> None:
    miner = logfold.Miner(max_templates=20, on_full="evict")
    miner.add_many(shapes(100))
    result = miner.result()
    assert sum(template.count for template in result.templates) == result.run.records == 100
    assert result.run.evicted == 100 - (len(result.templates) - 1)
    assert result.run.overflowed
    assert len(result.templates) <= 21
    assert any("least recently used" in warning for warning in result.warnings)


def test_a_template_that_is_used_stays() -> None:
    miner = logfold.Miner(max_templates=10, on_full="evict")
    miner.add_many(shapes(10))
    for n in range(1, 10):
        miner.add_many([f"shape{n}a shape{n}b shape{n}c"])
    miner.add_many(["fresh x y"])
    found = texts(miner.result())
    assert "shape0a shape0b shape0c" not in found
    assert {"fresh x y", "shape1a shape1b shape1c", "shape9a shape9b shape9c"} <= found


def test_new_templates_skip_the_ones_that_were_dropped_before_they_were_asked_for() -> None:
    miner = logfold.Miner(max_templates=10, on_full="evict")
    miner.add_many(shapes(30))
    fresh = miner.new_templates()
    assert fresh
    assert set(fresh) <= texts(miner.result())
    assert miner.new_templates() == []


def test_the_default_policy_and_a_limit_that_is_not_reached_give_the_same_result() -> None:
    stream = shapes(30)
    evicting = logfold.Miner(on_full="evict")
    pooling = logfold.Miner()
    for miner in (evicting, pooling):
        miner.add_many(stream)
    assert [(t.text, t.count) for t in evicting.result().templates] == [
        (t.text, t.count) for t in pooling.result().templates
    ]
    assert evicting.result().run.evicted == 0


def test_a_report_has_the_field_only_when_templates_were_dropped(tmp_path: Path) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    log = write(tmp_path / "a.log", shapes(200))
    plain = json.loads(logfold.analyze(str(log), format="plain", max_templates=30).to_json())
    dropped = json.loads(logfold.analyze(str(log), format="plain", max_templates=30, on_full="evict").to_json())
    assert "evicted" not in plain["run"]
    assert dropped["run"]["evicted"] > 0
    jsonschema.validate(plain, schema)
    jsonschema.validate(dropped, schema)
    loaded = logfold.load_analysis(_save(tmp_path / "r.json", dropped))
    assert loaded.run.evicted == dropped["run"]["evicted"]


def _save(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_analyze_mines_with_one_tree_and_refuses_the_chunked_strategy(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", shapes(2000))
    result = logfold.analyze(str(log), format="plain", max_templates=50, on_full="evict", chunk_bytes=4096)
    assert result.metrics.strategy == "sequential"
    with pytest.raises(ConfigError, match="sequential"):
        logfold.analyze(str(log), format="plain", max_templates=50, on_full="evict", strategy="chunked")


def test_a_state_is_refused_by_the_other_policy_and_continued_by_the_same_one(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", shapes(100))
    state = tmp_path / "model.json"
    logfold.analyze(str(log), format="plain", max_templates=30, on_full="evict", save_state=state)
    with pytest.raises(StateError):
        logfold.analyze(str(log), format="plain", max_templates=30, load_state=state)
    with pytest.raises(StateError):
        logfold.match(state, str(log), format="plain", max_templates=30)
    more = write(tmp_path / "b.log", shapes(130)[100:])
    resumed = logfold.analyze(str(more), format="plain", max_templates=30, on_full="evict", load_state=state)
    assert resumed.run.records == 30
    assert "shape129a shape129b shape129c" in texts(resumed)


def test_the_fingerprint_of_the_default_policy_is_the_one_it_always_had() -> None:
    assert logfold.config.config_fingerprint(MiningConfig()) == logfold.config.config_fingerprint(
        MiningConfig(on_full="pool")
    )
    assert logfold.config.config_fingerprint(MiningConfig()) != logfold.config.config_fingerprint(
        MiningConfig(on_full="evict")
    )


def test_an_unknown_policy_is_refused() -> None:
    with pytest.raises(ConfigError, match="on_full"):
        MiningConfig(on_full="forget")
    with pytest.raises(ConfigError, match="on_full"):
        logfold.Miner(on_full="forget")

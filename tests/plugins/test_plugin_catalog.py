"""The plugin catalog: strict validation, loading, fetching over HTTPS and installing."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from logfold.errors import ConfigError, SourceError
from logfold.plugins import catalog


def entry(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "haproxy",
        "kinds": ["format"],
        "package": "logfold-haproxy",
        "specifier": ">=0.2, <1",
        "description": "HAProxy HTTP logs",
        "homepage": "https://example.org/logfold-haproxy",
    }
    base.update(changes)
    return base


def document(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": 1, "plugins": list(entries)}


class FakeResponse:
    def __init__(self, body: bytes, url: str = catalog.DEFAULT_CATALOG_URL) -> None:
        self.body = body
        self.url = url

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]

    def geturl(self) -> str:
        return self.url

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None, tb: TracebackType | None) -> None:
        return None


def test_valid_catalog_is_parsed_and_the_specifier_is_normalized() -> None:
    parsed = catalog.parse_catalog(document(entry()), "test")
    plugin = parsed.entries[0]
    assert plugin.requirement == "logfold-haproxy>=0.2,<1"
    assert plugin.kinds == ("format",)
    assert parsed.find("haproxy") is plugin
    assert parsed.find("nope") is None


def test_the_bundled_catalog_is_valid() -> None:
    bundled = catalog.load_bundled()
    assert bundled.source == "bundled"
    assert isinstance(bundled.entries, tuple)


@pytest.mark.parametrize(
    "bad",
    [
        entry(name="-r evil"),
        entry(package="--index-url=https://evil.example/simple"),
        entry(package="pkg @ https://evil.example/x.whl"),
        entry(specifier=">=1; rm -rf /"),
        entry(specifier="--pre"),
        entry(kinds=[]),
        entry(kinds=["parser"]),
        entry(kinds="format"),
        entry(description="line one\nline two"),
        entry(description="\x1b[31mred"),
        entry(description="x" * 301),
        entry(homepage="http://example.org"),
        entry(name=""),
        entry(name=5),
    ],
)
def test_unsafe_entries_are_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(ConfigError, match="invalid plugin catalog"):
        catalog.parse_catalog(document(bad), "test")


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {"schema_version": 2, "plugins": []},
        {"schema_version": 1},
        {"schema_version": 1, "plugins": {}},
        {"schema_version": 1, "plugins": ["haproxy"]},
        {"schema_version": 1, "plugins": [entry() for _ in range(2)]},
        {"schema_version": 1, "plugins": [entry(name=f"p{i}", package=f"p{i}") for i in range(501)]},
    ],
)
def test_malformed_documents_are_rejected(bad: Any) -> None:
    with pytest.raises(ConfigError):
        catalog.parse_catalog(bad, "test")


def test_load_from_a_file(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(document(entry())), encoding="utf-8")
    assert catalog.load(str(path)).entries[0].name == "haproxy"


def test_load_reports_missing_and_broken_files(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="cannot read"):
        catalog.load(str(tmp_path / "missing.json"))
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        catalog.load(str(broken))
    huge = tmp_path / "huge.json"
    huge.write_text(" " * (catalog.MAX_BYTES + 10), encoding="utf-8")
    with pytest.raises(ConfigError, match="larger than"):
        catalog.load(str(huge))


def test_default_load_is_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the network must not be used")

    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    assert catalog.load().source == "bundled"


def test_online_fetch_validates_and_labels_the_source(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(document(entry())).encode()
    requested: list[Any] = []

    def urlopen(request: Any, timeout: float) -> FakeResponse:
        requested.append((request.full_url, request.get_header("User-agent"), timeout))
        return FakeResponse(body)

    monkeypatch.delenv(catalog.ENV_OFFLINE, raising=False)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    fetched = catalog.load(online=True)
    assert fetched.source == catalog.DEFAULT_CATALOG_URL
    assert fetched.entries[0].package == "logfold-haproxy"
    url, agent, timeout = requested[0]
    assert url.startswith("https://")
    assert agent.startswith("logfold/")
    assert timeout == catalog.TIMEOUT_SECONDS


@pytest.mark.parametrize("value", ["1", "yes", "true"])
def test_offline_environment_forbids_the_network(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(catalog.ENV_OFFLINE, value)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: pytest.fail("network used"))
    with pytest.raises(ConfigError, match=catalog.ENV_OFFLINE):
        catalog.load(online=True)
    with pytest.raises(ConfigError, match=catalog.ENV_OFFLINE):
        catalog.load("https://example.org/catalog.json")


def test_only_https_is_accepted() -> None:
    with pytest.raises(ConfigError, match="https"):
        catalog.load("http://example.org/catalog.json")


def test_fetch_failures_are_source_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(catalog.ENV_OFFLINE, raising=False)

    def unreachable(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError("no route")

    monkeypatch.setattr("urllib.request.urlopen", unreachable)
    with pytest.raises(SourceError, match="no route"):
        catalog.load(online=True)

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: FakeResponse(b"{}", "http://example.org/x"))
    with pytest.raises(SourceError, match="non-https"):
        catalog.load(online=True)

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: FakeResponse(b" " * (catalog.MAX_BYTES + 5)))
    with pytest.raises(ConfigError, match="larger than"):
        catalog.load(online=True)


def test_new_plugins_are_the_ones_that_are_not_installed() -> None:
    parsed = catalog.parse_catalog(
        document(entry(), entry(name="other", package="logfold-other", kinds=["reporter", "matcher"])), "test"
    )
    assert [e.name for e in catalog.new_plugins(parsed, installed=lambda package: package == "logfold-haproxy")] == [
        "other"
    ]
    assert len(catalog.new_plugins(parsed, installed=lambda _package: False)) == 2
    assert catalog.new_plugins(parsed, installed=lambda _package: True) == ()


def test_is_installed_knows_real_distributions() -> None:
    assert catalog.is_installed("pytest")
    assert not catalog.is_installed("definitely-not-a-logfold-plugin-xyz")


def test_install_runs_pip_with_the_validated_requirement(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = catalog.parse_catalog(document(entry()), "test").entries[0]
    calls: list[tuple[list[str], dict[str, Any]]] = []

    class Done:
        returncode = 0

    def runner(command: list[str], **kwargs: Any) -> Done:
        calls.append((command, kwargs))
        return Done()

    monkeypatch.setattr("importlib.util.find_spec", lambda _name: object())
    assert catalog.install(plugin, runner=runner) == 0
    command, kwargs = calls[0]
    assert command[1:] == ["-m", "pip", "install", "logfold-haproxy>=0.2,<1"]
    assert kwargs == {"check": False}


def test_install_without_pip_falls_back_to_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = catalog.parse_catalog(document(entry()), "test").entries[0]
    calls: list[list[str]] = []

    class Done:
        returncode = 0

    def runner(command: list[str], **_kwargs: Any) -> Done:
        calls.append(command)
        return Done()

    monkeypatch.setattr("importlib.util.find_spec", lambda _name: None)
    monkeypatch.setattr("shutil.which", lambda _name: "/bin/uv")
    assert catalog.install(plugin, runner=runner) == 0
    assert calls[0][:3] == ["/bin/uv", "pip", "install"]
    assert calls[0][-1] == "logfold-haproxy>=0.2,<1"
    assert "--python" in calls[0]


def test_install_without_pip_and_uv_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = catalog.parse_catalog(document(entry()), "test").entries[0]
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: None)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    with pytest.raises(ConfigError, match="neither pip nor uv") as caught:
        catalog.install(plugin, runner=lambda *_a, **_k: pytest.fail("the installer must not run"))
    assert caught.value.hint is not None
    assert "uv pip install" in caught.value.hint

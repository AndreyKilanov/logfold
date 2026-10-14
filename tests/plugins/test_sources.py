"""The built-in sources: the exact command each one builds, and which targets it refuses."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from logfold.errors import ConfigError, UnknownSourceError
from logfold.ext import registry
from logfold.ext.sources import Command, SourceOptions
from logfold.plugins.sources import DockerSource, JournalctlSource, KubectlSource

NOTHING = SourceOptions()
NASTY = [
    "",
    " ",
    "-v",
    "--all",
    "web;rm -rf /",
    "web && id",
    "web|id",
    "$(id)",
    "`id`",
    "web name",
    "web\nname",
    "web\0name",
    "../web",
    "web/../x",
    "\u0432\u0435\u0431",
    "a" * 300,
]


def test_docker_reads_the_logs_of_a_container_and_keeps_the_error_stream() -> None:
    command = DockerSource().command("web-1", SourceOptions(tail=100, since="15m"))
    assert command == Command(("docker", "logs", "--tail", "100", "--since=15m", "--", "web-1"), merge_stderr=True)
    assert DockerSource().command("web", NOTHING).argv == ("docker", "logs", "--", "web")


@pytest.mark.parametrize("target", [*NASTY, "web:1", "web@sha256"])
def test_docker_refuses_a_name_that_is_not_a_container_name(target: str) -> None:
    with pytest.raises(ConfigError, match="is not valid"):
        DockerSource().command(target, NOTHING)


def test_docker_has_no_previous_instance() -> None:
    with pytest.raises(ConfigError, match="no previous instance"):
        DockerSource().command("web", SourceOptions(previous=True))


def test_kubectl_names_the_namespace_the_pod_and_the_container_and_never_follows() -> None:
    command = KubectlSource().command("prod/web-7d9/app", SourceOptions(tail=50, since="2h", previous=True))
    assert command == Command(
        (
            "kubectl",
            "logs",
            "--namespace=prod",
            "--container=app",
            "--previous",
            "--tail=50",
            "--since=2h",
            "--",
            "web-7d9",
        )
    )
    assert KubectlSource().command("prod/web-7d9", NOTHING).argv == (
        "kubectl",
        "logs",
        "--namespace=prod",
        "--",
        "web-7d9",
    )
    assert "--follow" not in command.argv
    assert "-f" not in command.argv


@pytest.mark.parametrize(
    "target",
    [
        "web",
        "prod/",
        "/web",
        "prod/web/app/extra",
        "Prod/web",
        "prod/Web",
        "prod/web/App",
        "prod/-web",
        "-n/web",
        "prod/web$(id)",
        "prod/web;id",
        "prod/web name",
        "prod/web.",
        "pro.d/web",
        *(f"prod/{bad}" for bad in NASTY),
    ],
)
def test_kubectl_refuses_a_target_that_is_not_namespace_pod_container(target: str) -> None:
    with pytest.raises(ConfigError):
        KubectlSource().command(target, NOTHING)


def test_journalctl_reads_one_unit_in_a_stable_format_without_a_pager() -> None:
    command = JournalctlSource().command("nginx.service", SourceOptions(tail=200, since="2026-10-14T10:00:00"))
    assert command == Command(
        (
            "journalctl",
            "--no-pager",
            "--quiet",
            "--output=short-iso",
            "--unit=nginx.service",
            "--lines=200",
            "--since=2026-10-14 10:00:00",
        )
    )
    assert JournalctlSource().platforms == ("linux",)
    assert "--follow" not in command.argv


@pytest.mark.parametrize("target", ["getty@tty1.service", "dev-disk-by\\x2duuid.device", "user@1000.service", "a:b"])
def test_journalctl_accepts_the_names_that_systemd_uses(target: str) -> None:
    assert JournalctlSource().command(target, NOTHING).argv[-1] == f"--unit={target}"


@pytest.mark.parametrize("target", [*NASTY, "-u", "--vacuum-size=1", "nginx service"])
def test_journalctl_refuses_a_name_that_is_not_a_unit(target: str) -> None:
    with pytest.raises(ConfigError, match="is not valid"):
        JournalctlSource().command(target, NOTHING)


@pytest.mark.parametrize("since", ["-1h", "1h; id", "$(id)", "a" * 65, "", "15m\n", "--all"])
def test_a_time_that_is_not_a_time_is_refused_before_it_becomes_an_argument(since: str) -> None:
    with pytest.raises(ConfigError, match="since must be"):
        SourceOptions(since=since)


@pytest.mark.parametrize(
    "since", ["15m", "2h", "2026-10-14T10:00:00", "2026-10-14 10:00:00", "2026-10-14T10:00:00+02:00"]
)
def test_a_duration_or_a_time_is_accepted(since: str) -> None:
    assert SourceOptions(since=since).since == since


def test_tail_must_be_positive() -> None:
    with pytest.raises(ConfigError, match="tail must be at least 1"):
        SourceOptions(tail=0)


@pytest.mark.parametrize(
    "argv", [(), ("",), ("docker", ""), ("docker", "a\0b"), ("/usr/bin/docker",), ("C:\\docker.exe",)]
)
def test_a_command_must_be_a_program_name_and_clean_arguments(argv: tuple[str, ...]) -> None:
    with pytest.raises(ConfigError):
        Command(argv)


def test_the_built_in_sources_are_registered_and_listed_as_a_kind() -> None:
    assert {"docker", "kubectl", "journalctl"} <= set(registry.source_names())
    rows = {(kind, name, origin) for kind, name, origin in registry.plugin_sources() if kind == "source"}
    assert ("source", "docker", "built-in") in rows


def test_an_unknown_source_suggests_the_closest_name() -> None:
    with pytest.raises(UnknownSourceError) as caught:
        registry.get_source("dockr")
    assert caught.value.hint == "did you mean 'docker'?"


def test_a_plugin_file_can_add_a_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "stern_source.py").write_text(
        textwrap.dedent(
            """
            from logfold.ext import Command


            class Stern:
                name = "stern"
                description = "pods by name"
                platforms = ()

                def command(self, target, options):
                    return Command(("stern", "--no-follow", "--", target))


            SOURCES = [Stern()]
            """
        )
    )
    try:
        registry.add_plugin_directory(tmp_path)
        assert registry.get_source("stern").command("web", NOTHING).argv == ("stern", "--no-follow", "--", "web")
        assert ("source", "stern", str(tmp_path / "stern_source.py")) in registry.plugin_sources()
    finally:
        registry._sources.pop("stern", None)
        registry._origins.pop(("source", "stern"), None)
        registry._explicit_dirs.clear()


@pytest.mark.parametrize(("since", "argument"), [("15m", "--since=-15m"), ("2h", "--since=-2h"), ("1w", "--since=-1w")])
def test_journalctl_reads_a_span_as_that_long_ago(since: str, argument: str) -> None:
    assert argument in JournalctlSource().command("nginx", SourceOptions(since=since)).argv


@pytest.mark.parametrize("since", ["2026-10-14 10:00:00", "2026-10-14T10:00:00"])
def test_journalctl_gets_a_time_with_a_space_between_the_date_and_the_time(since: str) -> None:
    argv = JournalctlSource().command("nginx", SourceOptions(since=since)).argv
    assert "--since=2026-10-14 10:00:00" in argv

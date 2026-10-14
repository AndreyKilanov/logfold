"""Built-in sources: ``docker``, ``kubectl`` and ``journalctl``.

Each one runs the user's own program in read-only mode and never follows the log.
"""

from __future__ import annotations

import re

from logfold.errors import ConfigError
from logfold.ext.sources import Command, SourceOptions

_DOCKER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_DNS_LABEL = re.compile(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?")
_DNS_NAME = re.compile(r"[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?")
_SPAN = re.compile(r"[0-9]{1,6}[smhdw]")
_ISO = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9])")
_UNIT = re.compile(r"[A-Za-z0-9_:.@\\][A-Za-z0-9_:.@\\-]{0,255}")


def _check(pattern: re.Pattern[str], value: str, what: str, example: str) -> str:
    if not pattern.fullmatch(value):
        raise ConfigError(f"{what} {value!r} is not valid", hint=f"for example {example}")
    return value


def _journal_time(since: str) -> str:
    """Write a time as journalctl reads it: a span ``15m`` is ``-15m``; the date and the time are split by a space."""
    if _SPAN.fullmatch(since):
        return f"-{since}"
    return _ISO.sub(lambda found: f"{found.group(1)} {found.group(2)}", since)


def _no_previous(options: SourceOptions, program: str) -> None:
    if options.previous:
        raise ConfigError(f"{program} has no previous instance to read", hint="--source-previous is for kubectl")


class DockerSource:
    """``docker:NAME`` — the output of ``docker logs`` for a container name or id (both its streams)."""

    name = "docker"
    description = "the log of a container, from 'docker logs'"
    platforms: tuple[str, ...] = ()

    def command(self, target: str, options: SourceOptions) -> Command:
        """Return ``docker logs`` for the container ``target``.

        Args:
            target: Container name or id.
            options: What to read.

        Returns:
            The command; the error stream of the container is part of the log.

        Raises:
            ConfigError: If the name is not valid or ``previous`` is set.
        """
        _no_previous(options, "docker")
        argv = ["docker", "logs"]
        if options.tail is not None:
            argv += ["--tail", str(options.tail)]
        if options.since is not None:
            argv.append(f"--since={options.since}")
        argv += ["--", _check(_DOCKER_NAME, target, "container", "docker:web")]
        return Command(tuple(argv), merge_stderr=True)


class KubectlSource:
    """``kubectl:NAMESPACE/POD[/CONTAINER]`` — the output of ``kubectl logs`` in the current cluster context."""

    name = "kubectl"
    description = "the log of a pod, from 'kubectl logs'"
    platforms: tuple[str, ...] = ()

    def command(self, target: str, options: SourceOptions) -> Command:
        """Return ``kubectl logs`` for the pod (and container) in ``target``.

        Args:
            target: ``NAMESPACE/POD`` or ``NAMESPACE/POD/CONTAINER``; the namespace is never taken from the context.
            options: What to read.

        Returns:
            The command.

        Raises:
            ConfigError: If a name is not valid.
        """
        parts = target.split("/")
        if len(parts) not in (2, 3):
            raise ConfigError(
                f"kubectl target {target!r} is not NAMESPACE/POD[/CONTAINER]", hint="kubectl:prod/web-7d9"
            )
        namespace = _check(_DNS_LABEL, parts[0], "namespace", "prod")
        pod = _check(_DNS_NAME, parts[1], "pod", "web-7d9")
        argv = ["kubectl", "logs", f"--namespace={namespace}"]
        if len(parts) == 3:
            argv.append(f"--container={_check(_DNS_LABEL, parts[2], 'container', 'app')}")
        if options.previous:
            argv.append("--previous")
        if options.tail is not None:
            argv.append(f"--tail={options.tail}")
        if options.since is not None:
            argv.append(f"--since={options.since}")
        return Command((*argv, "--", pod))


class JournalctlSource:
    """``journalctl:UNIT`` — the journal of a systemd unit, one record per line with an ISO time."""

    name = "journalctl"
    description = "the journal of a systemd unit, from 'journalctl'"
    platforms: tuple[str, ...] = ("linux",)

    def command(self, target: str, options: SourceOptions) -> Command:
        """Return ``journalctl`` for the unit ``target``.

        Args:
            target: Unit name, such as ``nginx.service``.
            options: What to read; a ``since`` such as ``15m`` means that long ago.

        Returns:
            The command.

        Raises:
            ConfigError: If the name is not valid or ``previous`` is set.
        """
        _no_previous(options, "journalctl")
        argv = ["journalctl", "--no-pager", "--quiet", "--output=short-iso"]
        argv.append(f"--unit={_check(_UNIT, target, 'unit', 'journalctl:nginx.service')}")
        if options.tail is not None:
            argv.append(f"--lines={options.tail}")
        if options.since is not None:
            argv.append(f"--since={_journal_time(options.since)}")
        return Command(tuple(argv))


def builtin_sources() -> tuple[DockerSource, KubectlSource, JournalctlSource]:
    """Return the sources that ship with logfold."""
    return DockerSource(), KubectlSource(), JournalctlSource()

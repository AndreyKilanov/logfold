"""Built-in log formats, expressed as declarative specifications."""

from __future__ import annotations

from logfold.ext.formats import FormatSpec, JsonFormat, PlainFormat, RegexFormat
from logfold.ext.registry import register_format

_ISO = r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
_LEVELS = r"TRACE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERROR|ERR|FATAL|CRITICAL|CRIT"

NGINX_ACCESS = RegexFormat(
    name="nginx",
    pattern=r'^\S+ \S+ \S+ \[(?P<ts>[^\]]+)\] (?P<msg>"[^"]*" \d{3})',
    message_group="msg",
    time_group="ts",
    ts_format="%d/%b/%Y:%H:%M:%S %z",
)

APACHE_ACCESS = RegexFormat(
    name="apache",
    pattern=NGINX_ACCESS.pattern,
    message_group="msg",
    time_group="ts",
    ts_format=NGINX_ACCESS.ts_format,
)

NGINX_ERROR = RegexFormat(
    name="nginx-error",
    pattern=r"^(?P<ts>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) \[(?P<lvl>\w+)\] (?P<msg>.*)$",
    message_group="msg",
    time_group="ts",
    level_group="lvl",
    ts_format="%Y/%m/%d %H:%M:%S",
)

SYSLOG = RegexFormat(
    name="syslog",
    pattern=r"^(?P<ts>[A-Z][a-z]{2} +\d{1,2} \d{2}:\d{2}:\d{2}) \S+ (?P<msg>.*)$",
    message_group="msg",
    time_group="ts",
    ts_format="%b %e %H:%M:%S",
)

KUBERNETES = RegexFormat(
    name="k8s",
    pattern=r"^(?P<ts>\d{4}-\d{2}-\d{2}T[\d:.]+Z) (?:stdout|stderr) [FP] (?P<msg>.*)$",
    message_group="msg",
    time_group="ts",
)

APP = RegexFormat(
    name="app",
    pattern=(rf"^(?P<ts>{_ISO})[ \t]+(?:\[[^\]]*\][ \t]+)?\[?(?P<lvl>{_LEVELS})\]?[ \t:-]+(?P<msg>.*)$"),
    message_group="msg",
    time_group="ts",
    level_group="lvl",
)

JOURNALD = JsonFormat(
    name="journald",
    message_keys=("MESSAGE",),
    time_keys=("__REALTIME_TIMESTAMP",),
    level_keys=("PRIORITY",),
)

BUILTIN_FORMATS: dict[str, FormatSpec] = {
    "plain": PlainFormat(),
    "jsonl": JsonFormat(),
    "journald": JOURNALD,
    "nginx": NGINX_ACCESS,
    "apache": APACHE_ACCESS,
    "nginx-error": NGINX_ERROR,
    "syslog": SYSLOG,
    "k8s": KUBERNETES,
    "app": APP,
}

DETECTION_ORDER: tuple[str, ...] = ("journald", "jsonl", "k8s", "nginx", "nginx-error", "app", "syslog")


def register_builtin_formats() -> None:
    """Register every built-in format in the global registry."""
    for name, spec in BUILTIN_FORMATS.items():
        register_format(name, spec)

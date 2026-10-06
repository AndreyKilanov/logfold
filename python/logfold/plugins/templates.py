"""Starting points for plugins that users write in their own plugin folder (``logfold plugins new``)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from string import Template

from logfold.errors import ConfigError, SourceError
from logfold.ext import registry

__all__ = ["KINDS", "module_stem", "render_template", "write_template"]

KINDS = ("format", "reporter", "matcher")

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,48}$")

_FORMAT = Template(
    '''"""Format plugin "$name": edit the pattern, then run  logfold analyze FILE --format $name

A format is data: the pattern is searched in the first line of every record and its named groups pick the message, the
timestamp and the level. This template reads lines such as

    2026-10-04T10:00:01Z WARN slow query took 412 ms

Other specifications are available in logfold.ext: JsonFormat (one JSON object per line) and PlainFormat.
"""

from logfold.ext import RegexFormat

FORMATS = [
    RegexFormat(
        name="$name",
        pattern=r"^(?P<ts>\\S+) (?P<lvl>[A-Za-z]+) (?P<msg>.*)$$",
        message_group="msg",
        time_group="ts",
        level_group="lvl",
    ),
]
'''
)

_REPORTER = Template(
    '''"""Reporter plugin "$name": edit render(), then call  result.render("$name")  from Python.

render() receives an AnalysisResult or a DiffResult (see the API reference) and returns text. Log content is
untrusted: escape it for the format you produce.
"""


class $cls:
    name = "$name"
    kinds = ("analysis", "diff")

    def render(self, result, **options):
        if hasattr(result, "new_templates"):
            lines = [f"{len(result.new_templates)} new, {len(result.disappeared)} disappeared"]
            lines += [f"+ {entry.after_count:>8,}  {entry.text}" for entry in result.new_templates[:20]]
        else:
            lines = [f"{template.count:>8,}  {template.text}" for template in result.top(20)]
        return "\\n".join(lines) + "\\n"


REPORTERS = [$cls]
'''
)

_MATCHER = Template(
    '''"""Matcher plugin "$name": edit match(), then run  logfold diff BEFORE AFTER --matcher $name

logfold matches identical templates of the two runs itself. match() sees the rest, the template texts that exist in
one run only, and returns pairs (i, j): before_only[i] and after_only[j] are the same event. Every index may be used
at most once. This template pairs templates that start with the same word.
"""


class $cls:
    name = "$name"

    def match(self, before_only, after_only):
        pairs = []
        used = set()
        for j, text in enumerate(after_only):
            for i, other in enumerate(before_only):
                if i not in used and other.split()[:1] == text.split()[:1]:
                    pairs.append((i, j))
                    used.add(i)
                    break
        return pairs


MATCHERS = [$cls]
'''
)

_TEMPLATES = {"format": _FORMAT, "reporter": _REPORTER, "matcher": _MATCHER}


def module_stem(name: str) -> str:
    """Return the file name (without ``.py``) for a plugin called ``name``.

    Args:
        name: Plugin name.

    Returns:
        The name with dashes replaced by underscores.
    """
    return name.replace("-", "_")


def render_template(kind: str, name: str) -> str:
    """Return the source of a working plugin module.

    Args:
        kind: ``format``, ``reporter`` or ``matcher``.
        name: Plugin name: letters, digits, ``-`` and ``_``, starting with a letter.

    Returns:
        Python source to save in the plugin folder.

    Raises:
        ConfigError: If the kind or the name is not valid.
    """
    if kind not in _TEMPLATES:
        raise ConfigError(f"unknown plugin kind {kind!r}; use one of: {', '.join(KINDS)}")
    if not _NAME.match(name):
        raise ConfigError(f"invalid plugin name {name!r}: use letters, digits, '-' and '_', starting with a letter")
    class_name = "".join(part.capitalize() for part in re.split(r"[-_]", name) if part) + kind.capitalize()
    return _TEMPLATES[kind].substitute(name=name, cls=class_name)


def write_template(kind: str, name: str, folder: str | os.PathLike[str] | None = None, force: bool = False) -> Path:
    """Write a working plugin template, ready to edit.

    Args:
        kind: ``format``, ``reporter`` or ``matcher``.
        name: Plugin name: letters, digits, ``-`` and ``_``.
        folder: Where to write; the user plugin folder (see :func:`logfold.ext.default_plugin_dir`) by default. The
            folder is created if needed.
        force: Overwrite an existing file.

    Returns:
        The path of the new file.

    Raises:
        ConfigError: If the kind or name is not valid, or the file exists and ``force`` is not set.
        SourceError: If the file cannot be written.
    """
    source = render_template(kind, name)
    target_dir = Path(folder) if folder is not None else registry.default_plugin_dir()
    target = target_dir / f"{module_stem(name)}.py"
    if target.exists() and not force:
        raise ConfigError(
            f"{target} already exists", hint="pass force=True to overwrite it (--force on the command line)"
        )
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    except OSError as error:
        raise SourceError(f"cannot write the plugin template {target}: {error}") from error
    return target

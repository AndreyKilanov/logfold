"""Keep the logs that the real programs wrote, for the detection matrix (``autodetect.py``).

The runners of ``formats.py`` write each log into a temporary folder and delete it. When the environment variable
``LOGFOLD_KEEP_LOGS`` names a folder, every runner also copies its log there as ``<family>__<label>.log`` and writes the
format that is meant for the file (``log4j:<pattern>`` for a Java log) next to it as ``<family>__<label>.format``.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

ENV = "LOGFOLD_KEEP_LOGS"
SEPARATOR = "__"


def keep(log: Path, family: str, label: str, spec: str | None = None) -> None:
    """Copy ``log`` to the keep folder, if one is set, with the format meant for it (``spec``, else ``family``)."""
    folder = os.environ.get(ENV)
    if not folder:
        return
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    stem = f"{family}{SEPARATOR}{re.sub(r'[^A-Za-z0-9._-]+', '-', label).strip('-')}"
    shutil.copy(log, target / f"{stem}.log")
    (target / f"{stem}.format").write_text(spec or family, encoding="utf-8")

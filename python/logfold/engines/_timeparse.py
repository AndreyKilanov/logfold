"""Timestamp and level parsing of the reference engine.

Mirrors ``crates/logfold-io/src/timestamp.rs`` and ``crates/logfold-core/src/level.rs`` exactly; see
``docs/ALGORITHM.md`` §1.3 and §1.4. Timestamps are integer microseconds since the Unix epoch (UTC).
"""

from __future__ import annotations

import math

_MICROS = 1_000_000
_I64_MAX = (1 << 63) - 1
_I64_MIN = -(1 << 63)
_ASCII_WS = " \t\n\x0c\r"
_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

LEVEL_NAMES = ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL")
_LEVELS = {
    "TRACE": 0,
    "DEBUG": 1,
    "INFO": 2,
    "NOTICE": 2,
    "WARN": 3,
    "WARNING": 3,
    "ERROR": 4,
    "ERR": 4,
    "FATAL": 5,
    "CRITICAL": 5,
    "CRIT": 5,
    "EMERG": 5,
    "ALERT": 5,
    "PANIC": 5,
    "0": 5,
    "1": 5,
    "2": 5,
    "3": 4,
    "4": 3,
    "5": 2,
    "6": 2,
    "7": 1,
}

Parsed = tuple[int, bool]


def parse_level(text: str) -> int | None:
    """Return the severity rank of a level text, or ``None`` when unknown.

    Args:
        text: Level text such as ``warning``.

    Returns:
        A rank in ``0..5`` or ``None``.
    """
    text = text.strip(_ASCII_WS)
    if not text or len(text.encode("utf-8", "replace")) > 8:
        return None
    return _LEVELS.get(text.upper()) if text.isascii() else None


def _is_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or year % 400 == 0


def _days_in_month(year: int, month: int) -> int:
    if month in (1, 3, 5, 7, 8, 10, 12):
        return 31
    if month in (4, 6, 9, 11):
        return 30
    return 29 if _is_leap(year) else 28


def _days_from_civil(year: int, month: int, day: int) -> int:
    y = year - (1 if month <= 2 else 0)
    era = y // 400
    yoe = y - era * 400
    mp = (month + 9) % 12
    doy = (153 * mp + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146_097 + doe - 719_468


def _fit(value: int) -> int | None:
    return value if _I64_MIN <= value <= _I64_MAX else None


class _Cursor:
    __slots__ = ("pos", "text")

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def eat(self, char: str) -> bool:
        if self.peek() == char:
            self.pos += 1
            return True
        return False

    def done(self) -> bool:
        return self.pos == len(self.text)

    def digits(self, minimum: int, maximum: int) -> int | None:
        value = 0
        count = 0
        while count < maximum:
            char = self.peek()
            if char and "0" <= char <= "9":
                value = value * 10 + (ord(char) - 48)
                self.pos += 1
                count += 1
            else:
                break
        return value if count >= minimum else None

    def fraction(self) -> int | None:
        start = self.pos
        while self.pos - start < 9 and self.peek() and "0" <= self.peek() <= "9":
            self.pos += 1
        if self.pos == start:
            return None
        digits = self.text[start : self.pos][:6]
        return int(digits.ljust(6, "0"))

    def zone(self) -> int | None:
        if self.eat("Z"):
            return 0
        char = self.peek()
        if char == "+":
            sign = 1
        elif char == "-":
            sign = -1
        else:
            return None
        self.pos += 1
        hours = self.digits(2, 2)
        if hours is None:
            return None
        had_colon = self.eat(":")
        minutes = self.digits(2, 2)
        if minutes is None:
            if had_colon:
                return None
            minutes = 0
        if hours > 23 or minutes > 59:
            return None
        return sign * (hours * 3600 + minutes * 60)


class _Fields:
    __slots__ = ("day", "day_of_year", "hour", "micros", "minute", "month", "offset", "second", "year")

    def __init__(self) -> None:
        self.year: int | None = None
        self.month: int | None = None
        self.day: int | None = None
        self.day_of_year: int | None = None
        self.hour = 0
        self.minute = 0
        self.second = 0
        self.micros = 0
        self.offset: int | None = None

    def finish(self) -> Parsed | None:
        year = 1970 if self.year is None else self.year
        if self.hour > 23 or self.minute > 59 or self.second > 59:
            return None
        if self.day_of_year is not None:
            limit = 366 if _is_leap(year) else 365
            if self.day_of_year < 1 or self.day_of_year > limit:
                return None
            days = _days_from_civil(year, 1, 1) + self.day_of_year - 1
        else:
            month = 1 if self.month is None else self.month
            day = 1 if self.day is None else self.day
            if not 1 <= month <= 12 or day < 1 or day > _days_in_month(year, month):
                return None
            days = _days_from_civil(year, month, day)
        seconds = days * 86_400 + self.hour * 3600 + self.minute * 60 + self.second
        micros = _fit(seconds * _MICROS + self.micros)
        if micros is None:
            return None
        offset = 0 if self.offset is None else self.offset
        return micros - offset * _MICROS, self.offset is not None


def parse_iso(text: str) -> Parsed | None:
    """Parse ``YYYY-MM-DD[(T| )HH:MM[:SS[.f]]][zone]``.

    Args:
        text: Timestamp text.

    Returns:
        ``(microseconds, tz_aware)`` or ``None`` when the text is not a valid timestamp.
    """
    cur = _Cursor(text.strip(_ASCII_WS))
    fields = _Fields()
    fields.year = cur.digits(4, 4)
    if fields.year is None or not cur.eat("-"):
        return None
    fields.month = cur.digits(2, 2)
    if fields.month is None or not cur.eat("-"):
        return None
    fields.day = cur.digits(2, 2)
    if fields.day is None:
        return None
    if not cur.done():
        if not (cur.eat("T") or cur.eat(" ")):
            return None
        hour = cur.digits(2, 2)
        if hour is None or not cur.eat(":"):
            return None
        fields.hour = hour
        minute = cur.digits(2, 2)
        if minute is None:
            return None
        fields.minute = minute
        if cur.eat(":"):
            second = cur.digits(2, 2)
            if second is None:
                return None
            fields.second = second
            if cur.eat(".") or cur.eat(","):
                micros = cur.fraction()
                if micros is None:
                    return None
                fields.micros = micros
        if not cur.done():
            fields.offset = cur.zone()
            if fields.offset is None:
                return None
    return fields.finish() if cur.done() else None


class TsFormat:
    """A compiled ``strptime``-style format (``%Y %y %m %d %e %H %M %S %f %z %b %B %j %T %%``)."""

    def __init__(self, fmt: str) -> None:
        """Compile ``fmt``.

        Args:
            fmt: Format string.

        Raises:
            ValueError: If the format uses an unsupported directive.
        """
        items: list[tuple[str, str]] = []
        index = 0
        while index < len(fmt):
            char = fmt[index]
            index += 1
            if char == " ":
                if not items or items[-1][0] != "spaces":
                    items.append(("spaces", ""))
            elif char != "%":
                items.append(("lit", char))
            else:
                if index >= len(fmt):
                    raise ValueError("format ends with a lone '%'")
                directive = fmt[index]
                index += 1
                if directive == "T":
                    items.extend([("H", ""), ("lit", ":"), ("M", ""), ("lit", ":"), ("S", "")])
                elif directive == "%":
                    items.append(("lit", "%"))
                elif directive in "YymdeHMSfzbBj":
                    items.append((directive, ""))
                else:
                    raise ValueError(f"unsupported directive '%{directive}'")
        self._items = items

    def parse(self, text: str) -> Parsed | None:
        """Parse ``text``.

        Args:
            text: Timestamp text.

        Returns:
            ``(microseconds, tz_aware)`` or ``None``.
        """
        cur = _Cursor(text.strip(_ASCII_WS))
        fields = _Fields()
        for kind, arg in self._items:
            if not self._apply(cur, fields, kind, arg):
                return None
        return fields.finish() if cur.done() else None

    @staticmethod
    def _apply(cur: _Cursor, fields: _Fields, kind: str, arg: str) -> bool:
        if kind == "lit":
            return cur.eat(arg)
        if kind == "spaces":
            if not cur.eat(" "):
                return False
            while cur.eat(" "):
                pass
            return True
        if kind in {"b", "B"}:
            return _month_name(cur, fields, abbreviated=kind == "b")
        if kind == "z":
            fields.offset = cur.zone()
            return fields.offset is not None
        if kind == "f":
            micros = cur.fraction()
            if micros is None:
                return False
            fields.micros = micros
            return True
        if kind == "e":
            while cur.eat(" "):
                pass
        spec = {"Y": (4, 4), "y": (2, 2), "m": (1, 2), "d": (1, 2), "e": (1, 2), "H": (1, 2), "M": (1, 2)}
        low, high = spec.get(kind, (1, 3) if kind == "j" else (1, 2))
        value = cur.digits(low, high)
        if value is None:
            return False
        if kind == "Y":
            fields.year = value
        elif kind == "y":
            fields.year = 2000 + value if value < 69 else 1900 + value
        elif kind == "m":
            fields.month = value
        elif kind in ("d", "e"):
            fields.day = value
        elif kind == "H":
            fields.hour = value
        elif kind == "M":
            fields.minute = value
        elif kind == "S":
            fields.second = value
        else:
            fields.day_of_year = value
        return True


def _month_name(cur: _Cursor, fields: _Fields, *, abbreviated: bool) -> bool:
    rest = cur.text[cur.pos :]
    for index, name in enumerate(_MONTHS):
        candidate = name[:3] if abbreviated else name
        if rest[: len(candidate)].lower() == candidate and rest[: len(candidate)].isascii():
            cur.pos += len(candidate)
            fields.month = index + 1
            return True
    return False


def epoch_int_to_micros(value: int) -> int | None:
    """Convert an integer epoch value (seconds, ms, µs or ns) to microseconds.

    Args:
        value: Epoch value.

    Returns:
        Microseconds, or ``None`` on overflow.
    """
    magnitude = abs(value)
    if magnitude < 100_000_000_000:
        return _fit(value * _MICROS)
    if magnitude < 100_000_000_000_000:
        return _fit(value * 1000)
    if magnitude < 100_000_000_000_000_000:
        return _fit(value)
    return _fit(value // 1000)


def epoch_float_to_micros(value: float) -> int | None:
    """Convert a floating-point epoch value to microseconds.

    Args:
        value: Epoch value.

    Returns:
        Microseconds, or ``None`` when not finite or too large.
    """
    if not math.isfinite(value):
        return None
    magnitude = abs(value)
    if magnitude < 1e11:
        scaled = value * 1e6
    elif magnitude < 1e14:
        scaled = value * 1e3
    elif magnitude < 1e17:
        scaled = value
    else:
        scaled = value / 1e3
    rounded = math.floor(scaled + 0.5)
    return int(rounded) if abs(rounded) < 9.0e18 else None

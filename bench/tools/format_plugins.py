"""Throughput of the built-in format plugins against ``plain``.

For every format a log of the given size is generated (seeded, realistic lines with ids, addresses and durations), then
``logfold analyze`` runs on it as a separate process with the format and with ``-f plain`` (every line is a message, no
format parsing). The runner of ``run.py`` records wall time and peak working set. The pure-Python engine runs only on
the smallest size. Results go to ``bench/results/format-plugins.json``; the discussion is in
``bench/docs/FORMAT_PLUGINS.md``. Usage::

    python bench/tools/format_plugins.py --sizes 10 100 1000 --repeat 3
"""

from __future__ import annotations

import argparse
import json
import random
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path

from run import ROOT, Sample, measure, summarize
from run import logfold as logfold_command

import logfold

START = datetime(2026, 10, 6, 12, 0, 0)
APPS = ("shop", "auth", "billing", "search", "mail")
PATHS = (
    "/index.html",
    "/api/v1/items/{id}",
    "/api/v1/users/{id}/orders",
    "/static/app.{id}.js",
    "/login",
    "/cart/{id}",
    "/health",
)
MESSAGES = (
    "user {id} logged in from {ip}",
    "order {id} placed, total {n}.{c:02d}",
    "cache warmed {n} keys in {n} ms",
    "payment {id} failed: card declined",
    "retry {n} of 5 for job {id}",
    "request to {ip} timed out after {n} ms",
    "session {id} expired",
    "slow query on table orders took {n} ms",
    "connection pool at {n} percent",
    "email to user {id} queued",
)
STATEMENTS = (
    "SELECT * FROM orders WHERE user_id = {id} AND status = 'paid'",
    "UPDATE stock SET qty = qty - {n} WHERE sku = 'A{id}'",
    "INSERT INTO events (id, kind) VALUES ({id}, 'view')",
)


def ip(rng: random.Random) -> str:
    return f"10.{rng.randrange(256)}.{rng.randrange(256)}.{rng.randrange(1, 255)}"


def message(rng: random.Random) -> str:
    return rng.choice(MESSAGES).format(
        id=rng.randrange(10**6), ip=ip(rng), n=rng.randrange(1, 5000), c=rng.randrange(100)
    )


def clock(rng: random.Random) -> Iterator[datetime]:
    now = START
    while True:
        now += timedelta(milliseconds=rng.randrange(1, 40))
        yield now


def haproxy(rng: random.Random) -> Iterator[str]:
    for now in clock(rng):
        path = rng.choice(PATHS).format(id=rng.randrange(10**5))
        status = rng.choices((200, 200, 200, 301, 404, 500, 503), k=1)[0]
        state = "----" if status < 500 else "sH--"
        yield (
            f"{now:%b} {now.day:2d} {now:%H:%M:%S} lb1 haproxy[{rng.randrange(1000, 9999)}]: {ip(rng)}:{rng.randrange(1024, 65535)} "
            f"[{now:%d/%b/%Y:%H:%M:%S}.{now.microsecond // 1000:03d}] fe_http be_{rng.choice(APPS)}/srv{rng.randrange(1, 5)} "
            f"0/0/{rng.randrange(5)}/{rng.randrange(300)}/{rng.randrange(300)} {status} {rng.randrange(100, 90000)} - - {state} "
            f'{rng.randrange(1, 90)}/{rng.randrange(1, 90)}/0/0/0 0/0 "GET {path} HTTP/1.1"'
        )


def postgresql(rng: random.Random) -> Iterator[str]:
    for now in clock(rng):
        stamp = f"{now:%Y-%m-%d %H:%M:%S}.{now.microsecond // 1000:03d} UTC [{rng.randrange(1000, 9999)}]"
        kind = rng.randrange(10)
        statement = rng.choice(STATEMENTS).format(id=rng.randrange(10**6), n=rng.randrange(1, 50))
        if kind < 4:
            yield f"{stamp} app@shop LOG:  duration: {rng.random() * 90:.3f} ms  statement: {statement}"
        elif kind < 6:
            yield f"{stamp} LOG:  connection received: host={ip(rng)} port={rng.randrange(1024, 65535)}"
        elif kind < 7:
            yield f'{stamp} app@shop ERROR:  duplicate key value violates unique constraint "events_pkey"'
            yield f"{stamp} app@shop DETAIL:  Key (id)=({rng.randrange(10**6)}) already exists."
            yield f"{stamp} app@shop STATEMENT:  INSERT INTO events (id, kind)"
            yield f"\tVALUES ({rng.randrange(10**6)}, 'view')"
        elif kind < 8:
            yield f"{stamp} WARNING:  there is already a transaction in progress"
        else:
            yield f"{stamp} LOG:  checkpoint starting: time"


def postgresql_csv(rng: random.Random) -> Iterator[str]:
    for now in clock(rng):
        stamp = f"{now:%Y-%m-%d %H:%M:%S}.{now.microsecond // 1000:03d} UTC"
        pid = rng.randrange(1000, 9999)
        head = f'"app","shop",{pid},"{ip(rng)}:{rng.randrange(1024, 65535)}",65a1b2c3.{pid:x},{rng.randrange(1, 99)},"SELECT"'
        times = f"{stamp[:19]} UTC,{rng.randrange(1, 9)}/{rng.randrange(1, 99)},0"
        kind = rng.randrange(10)
        statement = rng.choice(STATEMENTS).format(id=rng.randrange(10**6), n=rng.randrange(1, 50))
        if kind < 6:
            yield f'{stamp},{head},{times},LOG,00000,"duration: {rng.random() * 90:.3f} ms  statement: {statement}",,,,,,,,,"psql","client backend"'
        elif kind < 8:
            yield f'{stamp},{head},{times},ERROR,23505,"duplicate key value violates unique constraint ""events_pkey""","Key (id)=({rng.randrange(10**6)}) already exists.",,,,,"INSERT INTO events (id, kind)'
            yield f"""VALUES ({rng.randrange(10**6)}, 'view')",,,"psql","client backend\""""
        else:
            yield f'{stamp},{head},{times},WARNING,01000,"there is already a transaction in progress",,,,,,,,,"psql","client backend"'


def docker_json(rng: random.Random) -> Iterator[str]:
    for now in clock(rng):
        stream = "stderr" if rng.randrange(20) == 0 else "stdout"
        stamp = f"{now:%Y-%m-%dT%H:%M:%S}.{now.microsecond:06d}{rng.randrange(1000):03d}Z"
        yield json.dumps({"log": message(rng) + "\n", "stream": stream, "time": stamp})


def github_actions(rng: random.Random) -> Iterator[str]:
    for now in clock(rng):
        stamp = f"{now:%Y-%m-%dT%H:%M:%S}.{now.microsecond:06d}0Z"
        kind = rng.randrange(20)
        if kind == 0:
            yield f"{stamp} ##[group]Run step {rng.randrange(40)}"
        elif kind == 1:
            yield f"{stamp} ##[endgroup]"
        elif kind == 2:
            yield f"{stamp} ##[warning]Node {rng.randrange(12, 20)} actions are deprecated"
        elif kind == 3:
            yield f"{stamp} ##[error]Process completed with exit code {rng.randrange(1, 3)}."
        elif kind < 10:
            yield f"{stamp} tests/test_{rng.choice(APPS)}_{rng.randrange(400)}.py::test_case_{rng.randrange(900)} PASSED [{rng.randrange(100)}%]"
        else:
            yield f"{stamp} Downloading package-{rng.randrange(900)}-{rng.randrange(20)}.{rng.randrange(20)}.whl ({rng.randrange(5000)} kB)"


def log4j(rng: random.Random) -> Iterator[str]:
    for now in clock(rng):
        level = rng.choices(("INFO ", "WARN ", "ERROR", "DEBUG"), weights=(70, 15, 5, 10))[0]
        thread = rng.choice(
            (
                "main",
                f"http-nio-8080-exec-{rng.randrange(1, 20)}",
                f"pool-{rng.randrange(1, 5)}-thread-{rng.randrange(1, 9)}",
            )
        )
        stamp = f"{now:%Y-%m-%d %H:%M:%S},{now.microsecond // 1000:03d}"
        yield f"{stamp} {level} [{thread}] com.shop.{rng.choice(APPS).title()}Service - {message(rng)}"
        if level == "ERROR" and rng.randrange(2):
            yield "java.lang.IllegalStateException: boom"
            yield f"\tat com.shop.OrderService.place(OrderService.java:{rng.randrange(10, 400)})"
            yield f"\tat com.shop.Web.handle(Web.java:{rng.randrange(10, 400)})"


GENERATORS: dict[str, Callable[[random.Random], Iterator[str]]] = {
    "haproxy": haproxy,
    "postgresql": postgresql,
    "postgresql-csv": postgresql_csv,
    "docker-json": docker_json,
    "github-actions": github_actions,
    "log4j": log4j,
}


def generate(name: str, size_mb: int, path: Path) -> None:
    """Write about ``size_mb`` megabytes of the log of format ``name``."""
    target = size_mb << 20
    written = 0
    with path.open("w", encoding="utf-8", newline="\n") as out:
        for line in GENERATORS[name](random.Random(7)):
            out.write(line + "\n")
            written += len(line) + 1
            if written >= target:
                break


def command(path: Path, fmt: str, engine: str) -> list[str]:
    return logfold_command("analyze", str(path), "-f", fmt, "--top", "1", "-q", "--engine", engine)


def parsed(path: Path, name: str) -> dict[str, int]:
    """Records, unparsed lines and templates of one in-process run (the format must read the whole log)."""
    result = logfold.analyze(path, format=name, engine="native", examples="none")
    return {
        "lines": result.run.lines,
        "records": result.run.records,
        "unparsed": result.run.unparsed,
        "untimed": result.run.untimed,
        "templates": len(result.templates),
    }


def row(name: str, size_mb: int, fmt: str, engine: str, samples: list[Sample]) -> dict[str, object]:
    summary = summarize(samples)
    median = summary.get("wall_median_s")
    mb_s = round(size_mb / float(median), 1) if isinstance(median, float) else None
    return {"format": name, "mode": fmt, "engine": engine, "size_mb": size_mb, "mb_per_s": mb_s, **summary}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formats", nargs="*", default=list(GENERATORS))
    parser.add_argument("--sizes", nargs="*", type=int, default=[10, 100, 1000])
    parser.add_argument("--python-size", type=int, default=10, help="size of the pure-Python engine run (0: skip)")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--data", type=Path, default=ROOT / "bench" / "data" / "formats")
    parser.add_argument("--out", type=Path, default=ROOT / "bench" / "results" / "format-plugins.json")
    args = parser.parse_args()
    args.data.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    checks: dict[str, dict[str, int]] = {}
    for name in args.formats:
        for size in sorted({*args.sizes, args.python_size} - {0}):
            path = args.data / f"{name}_{size}mb.log"
            generate(name, size, path)
            repeat = 1 if size >= 1000 else args.repeat
            if size == min(args.sizes):
                checks[name] = parsed(path, name)
                print(name, checks[name], flush=True)
            engines = ["native"] if size in args.sizes else []
            if size == args.python_size:
                engines.append("python")
            for engine in engines:
                for fmt in (name, "plain"):
                    samples = [measure(command(path, fmt, engine), args.timeout) for _ in range(repeat)]
                    rows.append(row(name, size, fmt, engine, samples))
                    print(name, size, fmt, engine, rows[-1].get("mb_per_s"), rows[-1].get("peak_mb_max"), flush=True)
            path.unlink()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"checks": checks, "runs": rows}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

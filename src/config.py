"""Settings for the fleet view, from one TOML file.

The code holds no host names and no user paths: every machine, folder and
price comes from the config. Copy examples/config.example.toml to
~/.config/playbook-herdr-fleet-view/config.toml and change it there.

A path may start with ~ (your home). A relative path is read from the folder
of the config file, so a config and its data can travel together (the demo
does that).
"""
from __future__ import annotations

import re
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from spend import PRICE_KEYS

DEFAULT_PATH = Path("~/.config/playbook-herdr-fleet-view/config.toml")
FLEET = {"herdr": "herdr", "snapshot_file": "", "interval": 10, "top_programs": 3}
SPEND = {"logs": ["~/.claude/projects"], "day_start": "00:00", "interval": 60,
         "big_context": 200_000, "rebuild_share": 0.30}


class ConfigError(Exception):
    pass


def resolve(value: str, base: Path) -> str:
    p = Path(value).expanduser()
    return str(p if p.is_absolute() else (base / p).resolve())


def positive(section: dict[str, Any], key: str, where: str) -> None:
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{where}: '{key}' must be a number above 0")


def load(path: Path) -> dict[str, Any]:
    """Read and check the config. Every problem names its key."""
    path = path.expanduser()
    if not path.is_file():
        raise ConfigError(f"no config at {path}: copy examples/config.example.toml "
                          "there and change it, or pass --config")
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name}: {e}") from None
    base = path.parent

    fleet = {**FLEET, **raw.get("fleet", {})}
    positive(fleet, "interval", "[fleet]")
    positive(fleet, "top_programs", "[fleet]")
    if fleet["snapshot_file"]:
        fleet["snapshot_file"] = resolve(fleet["snapshot_file"], base)

    machines = raw.get("machines", [{"name": "local"}])
    names = set()
    for m in machines:
        name = m.get("name")
        if not isinstance(name, str) or not name:
            raise ConfigError("[[machines]]: each machine needs a name")
        if name in names:
            raise ConfigError(f"[[machines]]: the name '{name}' is used twice")
        names.add(name)
        if m.get("ssh") and m.get("file"):
            raise ConfigError(f"[[machines]] {name}: give 'ssh' or 'file', not both")
        if m.get("file"):
            m["file"] = resolve(m["file"], base)

    spend = {**SPEND, **raw.get("spend", {})}
    if isinstance(spend["logs"], str):
        spend["logs"] = [spend["logs"]]
    spend["logs"] = [resolve(p, base) for p in spend["logs"]]
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(spend["day_start"])):
        raise ConfigError("[spend]: 'day_start' must be a time like \"00:00\"")
    for key in ("interval", "big_context", "rebuild_share"):
        positive(spend, key, "[spend]")

    prices = raw.get("prices")
    if not isinstance(prices, dict) or not prices:
        raise ConfigError("[prices]: give at least one model, for example [prices.sonnet]")
    for model, price in prices.items():
        missing = [k for k in PRICE_KEYS if not isinstance(price.get(k), (int, float))]
        if missing:
            raise ConfigError(f"[prices.{model}]: needs a number for {', '.join(missing)}")

    clock = raw.get("clock", "")
    if clock:
        try:
            clock = datetime.fromisoformat(clock)
        except ValueError:
            raise ConfigError("'clock' must be a time like 2026-01-15T17:30:00+00:00") from None
        if clock.tzinfo is None:
            raise ConfigError("'clock' needs a time zone, for example +00:00")
    return {"fleet": fleet, "machines": machines, "spend": spend, "prices": prices,
            "clock": clock or None}

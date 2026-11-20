"""Birthdays plugin for FiestaBoard.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.plugins.base import PluginBase, PluginResult, TriggerResult

try:  # Published enum; fall back to its documented value on older cores.
    from src.triggers import TriggerPriority

    _NOTABLE = int(TriggerPriority.NOTABLE)
except Exception:  # pragma: no cover - depends on host version
    _NOTABLE = 50

logger = logging.getLogger(__name__)

DEFAULT_TZ = "America/Chicago"
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
CONFETTI = ["{63}", "{64}", "{65}", "{66}", "{67}", "{68}"]  # red→violet tiles
CONFETTI_TILES = 22  # widest single board; Note uses the first 15

# MM-DD, MM/DD, YYYY-MM-DD, YYYY/MM/DD
_DATE_RE = re.compile(r"^\s*(?:(\d{4})[-/])?(\d{1,2})[-/](\d{1,2})\s*$")


@dataclass(frozen=True)
class Birthday:
    name: str
    month: int
    day: int
    year: int | None = None

    def occurrence(self, year: int) -> date:
        """This birthday in ``year``. Feb 29 is celebrated on Feb 28 in non-leap years."""
        try:
            return date(year, self.month, self.day)
        except ValueError:
            return date(year, 2, 28)

    def next_on_or_after(self, today: date) -> date:
        occ = self.occurrence(today.year)
        return occ if occ >= today else self.occurrence(today.year + 1)

    def age_on(self, when: date) -> int | None:
        return when.year - self.year if self.year else None


def parse_date(raw: Any) -> tuple[int, int, int | None]:
    """Parse MM-DD or YYYY-MM-DD (slashes allowed). Raises ValueError."""
    m = _DATE_RE.match(str(raw or ""))
    if not m:
        raise ValueError(f"'{raw}' is not MM-DD or YYYY-MM-DD")
    year = int(m.group(1)) if m.group(1) else None
    month, day = int(m.group(2)), int(m.group(3))
    # Validate against a leap year so 02-29 is accepted.
    date(year if year and year > 0 else 2000, month, day)
    if year is not None and (year < 1900 or year > 9999):
        raise ValueError(f"'{raw}' has an implausible year")
    return month, day, year


def ordinal(n: int) -> str:
    """1 → 1ST, 22 → 22ND, 13 → 13TH, 111 → 111TH."""
    if 11 <= n % 100 <= 13:
        return f"{n}TH"
    return f"{n}" + {1: "ST", 2: "ND", 3: "RD"}.get(n % 10, "TH")


def random_confetti(tiles: int, rng: random.Random | None = None) -> str:
    """Random color tiles, never the same color twice in a row."""
    rng = rng or random
    out: list[str] = []
    for _ in range(tiles):
        out.append(rng.choice([c for c in CONFETTI if not out or c != out[-1]]))
    return "".join(out)


def possessive(name: str) -> str:
    return f"{name}'S"


def join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " & " + names[-1]


def wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap; words longer than the board are hard-cut."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        word = word[:width]
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


class BirthdaysPlugin(PluginBase):
    """Simple birthday list plugin."""

    @property
    def plugin_id(self) -> str:
        return "birthdays"

    # ------------------------------------------------------------------ config

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors = list(self._validate_refresh_seconds(config))

        tz = config.get("timezone") or DEFAULT_TZ
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            errors.append(f"Invalid timezone: {tz}")

        entries = config.get("birthdays") or []
        if not isinstance(entries, list):
            return errors + ["Birthdays must be a list"]
        for i, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                errors.append(f"Row {i}: expected a name and a date")
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                errors.append(f"Row {i}: name is required")
            try:
                parse_date(entry.get("date"))
            except ValueError as e:
                errors.append(f"Row {i} ({name or 'unnamed'}): {e}")
        return errors

    def _birthdays(self) -> list[Birthday]:
        """Parsed, valid entries. Bad rows are skipped (and logged), not fatal."""
        result: list[Birthday] = []
        for entry in self.config.get("birthdays") or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip().upper()
            if not name:
                continue
            try:
                month, day, year = parse_date(entry.get("date"))
            except ValueError as e:
                logger.warning("birthdays: skipping %s: %s", name, e)
                continue
            result.append(Birthday(name=name, month=month, day=day, year=year))
        return result

    def _now(self) -> datetime:
        tz_name = self.config.get("timezone") or DEFAULT_TZ
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo(DEFAULT_TZ)
        return datetime.now(tz)

    # -------------------------------------------------------------------- data

    def compute(self, today: date) -> dict[str, Any]:
        """Build template variables for ``today``. Pure — easy to test."""
        people = self._birthdays()
        lookahead = int(self.config.get("lookahead_days") or 30)

        todays = [b for b in people if b.occurrence(today.year) == today]
        names = [b.name for b in todays]

        upcoming = []
        for b in people:
            # Next occurrence strictly after today.
            nxt = b.next_on_or_after(today + timedelta(days=1))
            days = (nxt - today).days
            upcoming.append((days, b.name, b, nxt))
        upcoming.sort(key=lambda t: (t[0], t[1]))

        first_age = todays[0].age_on(today) if todays else None
        data: dict[str, Any] = {
            "is_birthday": "true" if todays else "false",
            "names": join_names(names),
            "message": f"IT'S {possessive(join_names(names))} BIRTHDAY!" if names else "",
            "count": str(len(todays)),
            "age": str(first_age) if first_age is not None else "",
            "ordinal": ordinal(first_age) if first_age is not None and first_age > 0 else "",
            "confetti": random_confetti(CONFETTI_TILES),
            "today": [
                {"name": b.name, "age": str(b.age_on(today)) if b.year else ""} for b in todays
            ],
            "upcoming": [
                {
                    "name": name,
                    "date": f"{MONTHS[nxt.month - 1]} {nxt.day}",
                    "days": str(days),
                    "age": str(b.age_on(nxt)) if b.year else "",
                }
                for days, name, b, nxt in upcoming
                if days <= lookahead
            ],
            "next_name": "",
            "next_date": "",
            "next_days": "",
            "next_formatted": "",
        }

        if upcoming:
            days, name, _b, nxt = upcoming[0]
            data["next_name"] = name
            data["next_date"] = f"{MONTHS[nxt.month - 1]} {nxt.day}"
            data["next_days"] = str(days)
            data["next_formatted"] = f"{name} TOMORROW" if days == 1 else f"{name} IN {days} DAYS"

        return data

    def fetch_data(self) -> PluginResult:
        try:
            if not self._birthdays():
                return PluginResult(available=False, error="No birthdays configured")
            data = self.compute(self._now().date())
            return PluginResult(available=True, data=data, formatted_lines=self._format_display(data))
        except Exception as e:  # pragma: no cover - defensive
            logger.exception("Error computing birthdays")
            return PluginResult(available=False, error=str(e))

    # ----------------------------------------------------------------- display

    def _format_display(self, data: dict[str, Any]) -> list[str]:
        board = self.board
        width = board.width if board else 22
        height = board.height if board else 6

        if data.get("is_birthday") == "true":
            body = wrap(data["message"], width)
            age = data.get("age")
            if age and data.get("count") == "1" and len(body) + 1 <= height - 2:
                body.append(f"{age} TODAY")
            # Confetti top (and bottom when there's room), message centred between.
            top = [random_confetti(width)] if height >= len(body) + 1 else []
            bottom = [random_confetti(width)] if height >= len(body) + len(top) + 1 and height > 3 else []
            free = height - len(top) - len(bottom) - len(body)
            pad_top = max(free // 2, 0)
            middle = [""] * pad_top + [line.center(width) for line in body]
            middle += [""] * (height - len(top) - len(bottom) - len(middle))
            lines = top + middle + bottom
        else:
            if height <= 3:
                lines = [
                    "NEXT BIRTHDAY".center(width)[:width],
                    data.get("next_name", "")[:width].center(width),
                    self._when(data, width).center(width),
                ]
            else:
                lines = [
                    "NEXT BIRTHDAY".center(width)[:width],
                    "",
                    data.get("next_name", "")[:width].center(width),
                    data.get("next_date", "").center(width),
                    self._when(data, width).center(width),
                    "",
                ]
        lines = (lines + [""] * height)[:height]
        return lines

    @staticmethod
    def _when(data: dict[str, Any], width: int) -> str:
        days = data.get("next_days", "")
        if days == "1":
            return "TOMORROW"
        text = f"IN {days} DAYS"
        if width < 15:  # tiny boards: drop the date line, keep the countdown
            return f"{days}D"
        return text

    def get_formatted_display(self) -> list[str] | None:
        result = self.fetch_data()
        if not result.available or not result.data:
            return None
        return self._format_display(result.data)

    # ---------------------------------------------------------------- triggers

    def check_triggers(self) -> list[TriggerResult]:
        """Announce today's birthday(s) once a day for a fixed window."""
        if not self.config.get("announce"):
            return []
        now = self._now()
        data = self.compute(now.date())
        if data["is_birthday"] != "true":
            return []

        start_hour = int(self.config.get("announce_hour", 8))
        minutes = int(self.config.get("announce_minutes", 30))
        start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        end = start + timedelta(minutes=minutes)
        if not (start <= now < end):
            return []

        return [
            TriggerResult(
                triggered=True,
                # One id per day: re-returning it each tick just refreshes it,
                # and a manual page change suppresses it for the rest of the window.
                trigger_id=f"birthdays_{now.date().isoformat()}",
                priority=_NOTABLE,
                duration_seconds=max(int((end - now).total_seconds()), 30),
                data=data,
                formatted_lines=self._format_display(data),
                message=data["message"],
            )
        ]


Plugin = BirthdaysPlugin

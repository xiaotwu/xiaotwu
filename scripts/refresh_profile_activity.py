"""Render the public GitHub contribution calendar and update the recent links."""

import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

ACCOUNT = "xiaotwu"
PROFILE_REPO = f"{ACCOUNT}/{ACCOUNT}"
PACIFIC = ZoneInfo("America/Los_Angeles")
ROOT = Path(__file__).resolve().parents[1]
START_MARKER = "<!-- recent-commits:start -->"
END_MARKER = "<!-- recent-commits:end -->"
THEMES = {
    "light": (
        "#f1f8f4", "#405951",
        ("#dcebe4", "#acddcb", "#72bba3", "#388a73", "#165848"),
    ),
    "dark": (
        "#1a2522", "#a8bdb4",
        ("#2d4038", "#26594d", "#357f6c", "#53ac92", "#82dbc1"),
    ),
}


def download(url, accept, token=None):
    headers = {"User-Agent": "xiaotwu-profile-activity", "Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=25) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("GitHub response exceeded the expected size.")
    return body


class ContributionCalendar(HTMLParser):
    """Read the day and intensity from GitHub's public calendar cells."""

    def __init__(self):
        super().__init__()
        self.levels = {}

    def handle_starttag(self, tag, attributes):
        if tag != "td":
            return
        attributes = dict(attributes)
        if "data-date" not in attributes or "data-level" not in attributes:
            return
        day = date.fromisoformat(attributes["data-date"])
        level = int(attributes["data-level"])
        if day in self.levels or not 0 <= level <= 4:
            raise ValueError("GitHub returned an unexpected contribution cell.")
        self.levels[day] = level


def public_calendar(today):
    # Fetch anonymously so the graph follows what visitors can see on the profile.
    url = f"https://github.com/users/{ACCOUNT}/contributions"
    parser = ContributionCalendar()
    parser.feed(download(url, "text/html").decode())
    parser.close()
    start = today - timedelta(days=364)
    days = [start + timedelta(days=offset) for offset in range(365)]
    if not all(day in parser.levels for day in days):
        raise ValueError("GitHub's public contribution calendar is incomplete.")
    return {day: parser.levels[day] for day in days}


def complete_commit_search(query):
    url = f"https://api.github.com/search/commits?{query}"
    # The runner's repository token can get incomplete results from global search.
    tokens = (None, os.environ.get("GH_TOKEN"), None)
    for attempt, token in enumerate(tokens, 1):
        try:
            data = json.loads(download(url, "application/vnd.github+json", token))
            if data["incomplete_results"]:
                raise RuntimeError("GitHub returned an incomplete commit search.")
            return data
        except (URLError, TimeoutError, RuntimeError) as error:
            if attempt == len(tokens):
                raise
            print(f"Commit search attempt {attempt} failed ({error}); retrying.")
            time.sleep(2 * attempt)


def recent_commits(now):
    end = now.astimezone(PACIFIC).date()
    start = end - timedelta(days=13)
    # The API filters by UTC date. Cover both boundary days, then filter locally.
    query = urlencode({
        "q": (
            f"author:{ACCOUNT} is:public -repo:{PROFILE_REPO} "
            f"committer-date:{start - timedelta(days=1)}..{end + timedelta(days=1)}"
        ),
        "sort": "committer-date",
        "order": "desc",
        "per_page": 30,
    })
    data = complete_commit_search(query)

    rows = []
    seen = set()
    for item in data["items"]:
        repository = item["repository"]
        name = repository["full_name"]
        committed = datetime.fromisoformat(item["commit"]["committer"]["date"])
        day = committed.astimezone(PACIFIC).date()
        if repository["private"] or name.casefold() == PROFILE_REPO or not start <= day <= end:
            continue
        sha = item["sha"]
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", name, re.ASCII) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("GitHub returned an unexpected commit reference.")
        if (name, sha) in seen:
            continue
        seen.add((name, sha))
        subject = item["commit"]["message"].partition("\n")[0].strip() or f"Commit {sha[:7]}"
        if len(subject) > 120:
            subject = subject[:119].rstrip() + "…"
        subject = re.sub(r"([\\`*_\[\]<>#|~&])", r"\\\1", subject)
        rows.append(
            f"- [{subject}](https://github.com/{name}/commit/{sha}) "
            f"· `{name.split('/', 1)[1]}` · {day:%b} {day.day}"
        )
        if len(rows) == 3:
            return "\n".join(rows)
    if data["total_count"] > len(data["items"]):
        raise ValueError("Could not verify the latest public commits from the first search page.")
    return "\n".join(rows) or "_No public commits in the last 14 days._"


def render_calendar(days, theme):
    background, foreground, colors = theme
    scale = 2
    cell, step = 11, 14
    left, top = 46, 32
    first_day = min(days)
    sunday = first_day - timedelta(days=(first_day.weekday() + 1) % 7)
    last_column = (max(days) - sunday).days // 7
    width = left + last_column * step + cell + 17
    legend_y = top + 6 * step + cell + 21
    height = legend_y + 18
    image = Image.new("RGBA", (width * scale, height * scale))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=11 * scale)
    draw.rounded_rectangle(
        (0, 0, width * scale - 1, height * scale - 1),
        radius=6 * scale, fill=background,
    )

    def label(x, y, text):
        draw.text((x * scale, y * scale), text, anchor="lm", fill=foreground, font=font)

    def square(x, y, color):
        draw.rounded_rectangle(
            (x * scale, y * scale, (x + cell) * scale - 1, (y + cell) * scale - 1),
            radius=2 * scale, fill=color,
        )

    next_month_x = left
    for day, level in days.items():
        column, row = divmod((day - sunday).days, 7)
        x = left + column * step
        square(x, top + row * step, colors[level])
        if (day == first_day or day.day == 1) and next_month_x <= x <= width - 30:
            label(x, 17, day.strftime("%b"))
            next_month_x = x + 34

    for row, day in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        label(15, top + row * step + cell / 2, day)
    label(15, legend_y, "Past year")
    legend_x = width - 115
    label(legend_x - 28, legend_y, "Less")
    for level, color in enumerate(colors):
        square(legend_x + level * step, legend_y - cell / 2, color)
    label(legend_x + 5 * step, legend_y, "More")

    result = BytesIO()
    image.save(result, format="PNG", optimize=True)
    return result.getvalue()


def main():
    path = ROOT / "README.md"
    readme = path.read_text(encoding="utf-8")
    if readme.count(START_MARKER) != 1 or readme.count(END_MARKER) != 1:
        raise ValueError("The README needs one recent commits marker pair.")
    before, after_start = readme.split(START_MARKER)
    _, after = after_start.split(END_MARKER)

    now = datetime.now(timezone.utc)
    days = public_calendar(now.date())
    commits = recent_commits(now)
    # Prepare both snapshots before touching the existing README or image assets.
    charts = {theme: render_calendar(days, palette) for theme, palette in THEMES.items()}
    for theme, image in charts.items():
        (ROOT / "assets" / f"contributions-{theme}.png").write_bytes(image)
    path.write_text(f"{before}{START_MARKER}\n\n{commits}\n\n{END_MARKER}{after}", encoding="utf-8")
    print(f"Refreshed {len(days)} contribution days and {commits.count('https://github.com/')} commit links.")


if __name__ == "__main__":
    main()

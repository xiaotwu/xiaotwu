"""Render the public GitHub contribution calendar and Minesweeper animation."""

import argparse
import json
import os
import subprocess
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from PIL import Image, ImageDraw, ImageFont

ACCOUNT = "xiaotwu"
ROOT = Path(__file__).resolve().parents[1]
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


def download(url, accept):
    headers = {"User-Agent": "xiaotwu-profile-activity", "Accept": accept}
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


def render_minesweeper(days, arcade_module):
    renderer = ROOT / "scripts" / "render_minesweeper.mjs"
    arcade_module = arcade_module.resolve()
    result = subprocess.run(
        [
            "node", "--permission", f"--allow-fs-read={renderer}",
            f"--allow-fs-read={arcade_module}", str(renderer), str(arcade_module),
        ],
        input=json.dumps({day.isoformat(): level for day, level in days.items()}),
        text=True, stdout=subprocess.PIPE, check=True, timeout=45,
        env={"PATH": os.environ["PATH"], "TZ": "UTC"},
    )
    rendered = json.loads(result.stdout)
    svg_ns = "{http://www.w3.org/2000/svg}"
    for theme in THEMES:
        image = rendered[theme]
        if len(image.encode("utf-8")) > 2_000_000:
            raise ValueError(f"Minesweeper {theme} SVG is too large.")
        svg = ElementTree.fromstring(image)
        if svg.tag != f"{svg_ns}svg" or svg.find(f".//{svg_ns}animateTransform") is None:
            raise ValueError(f"Minesweeper {theme} SVG is missing its animation.")
    return rendered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arcade-module", type=Path, help="Path to the pinned arcade renderer.")
    args = parser.parse_args()

    days = public_calendar(datetime.now(timezone.utc).date())
    # Prepare all snapshots before replacing the existing image assets.
    charts = {theme: render_calendar(days, palette) for theme, palette in THEMES.items()}
    arcade = render_minesweeper(days, args.arcade_module) if args.arcade_module else {}
    for theme, image in charts.items():
        (ROOT / "assets" / f"contributions-{theme}.png").write_bytes(image)
    for theme, image in arcade.items():
        (ROOT / "assets" / f"minesweeper-{theme}.svg").write_text(image + "\n", encoding="utf-8")
    print(f"Refreshed {len(days)} contribution days.")
    if arcade:
        print(f"Rendered {len(arcade)} Minesweeper themes.")


if __name__ == "__main__":
    main()

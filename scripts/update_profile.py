#!/usr/bin/env python3
"""Fetch public GitHub metrics and render a restrained profile dashboard SVG."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
PORTRAIT_PATH = ROOT / "assets" / "portrait.txt"
OUTPUT_DIR = ROOT / "generated"
GRAPHQL_URL = "https://api.github.com/graphql"

THEMES = {
    "dark": {
        "bg": "#111210",
        "panel": "#151613",
        "text": "#E7E3DA",
        "muted": "#9B978E",
        "faint": "#3B3A35",
        "accent": "#B4AA96",
        "plot": "#C7BCA7",
        "grid": "#2D2E2A",
    },
    "light": {
        "bg": "#EAE5DB",
        "panel": "#E5DFD4",
        "text": "#292A27",
        "muted": "#77736B",
        "faint": "#C6BFB3",
        "accent": "#8D806D",
        "plot": "#756A59",
        "grid": "#D5CEC2",
    },
}

QUERY = r"""
query ProfileDashboard($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    login
    name
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC, orderBy: {field: STARGAZERS, direction: DESC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        url
        stargazerCount
        isFork
      }
    }
    pullRequests(first: 1) { totalCount }
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc


def graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "github-profile-dashboard",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub GraphQL HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub GraphQL connection failed: {exc}") from exc

    if body.get("errors"):
        raise RuntimeError(f"GitHub GraphQL error: {body['errors']}")
    return body["data"]


def mock_data(username: str) -> dict[str, Any]:
    today = dt.date.today()
    days: list[dict[str, Any]] = []
    for i in range(365):
        day = today - dt.timedelta(days=364 - i)
        value = max(0, round(3.2 + 2.2 * math.sin(i / 18) + 1.3 * math.sin(i / 5)))
        if day.weekday() >= 5:
            value = max(0, value - 2)
        days.append({"date": day.isoformat(), "count": value})
    return {
        "username": username,
        "followers": 128,
        "public_repos": 18,
        "stars": 247,
        "pull_requests_365d": 42,
        "contributions_365d": sum(d["count"] for d in days),
        "current_streak": 17,
        "days": days,
        "top_repos": [
            {"name": "research-infrastructure", "stars": 91},
            {"name": "low-latency-lab", "stars": 64},
            {"name": "signal-discovery", "stars": 38},
        ],
        "updated_at": dt.datetime.now(dt.timezone.utc),
    }


def calculate_current_streak(days: list[dict[str, Any]]) -> int:
    if not days:
        return 0
    by_date = {dt.date.fromisoformat(d["date"]): int(d["count"]) for d in days}
    cursor = dt.date.today()
    # GitHub's current UTC day may not yet have activity. Start yesterday in that case.
    if by_date.get(cursor, 0) == 0:
        cursor -= dt.timedelta(days=1)
    streak = 0
    while by_date.get(cursor, 0) > 0:
        streak += 1
        cursor -= dt.timedelta(days=1)
    return streak


def fetch_metrics(username: str, token: str) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(days=364)
    data = graphql(
        token,
        QUERY,
        {
            "login": username,
            "from": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "to": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
    )
    user = data.get("user")
    if not user:
        raise RuntimeError(f"GitHub user not found: {username}")

    repos = [r for r in user["repositories"]["nodes"] if not r["isFork"]]
    calendar = user["contributionsCollection"]["contributionCalendar"]
    days = [
        {"date": d["date"], "count": d["contributionCount"]}
        for week in calendar["weeks"]
        for d in week["contributionDays"]
    ]
    days = sorted(days, key=lambda item: item["date"])[-365:]
    return {
        "username": user["login"],
        "followers": user["followers"]["totalCount"],
        "public_repos": user["repositories"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "pull_requests_365d": user["contributionsCollection"]["totalPullRequestContributions"],
        "contributions_365d": calendar["totalContributions"],
        "current_streak": calculate_current_streak(days),
        "days": days,
        "top_repos": [
            {"name": r["name"], "stars": r["stargazerCount"]}
            for r in sorted(repos, key=lambda r: r["stargazerCount"], reverse=True)[:3]
        ],
        "updated_at": now,
    }


def monthly_counts(days: list[dict[str, Any]]) -> list[tuple[str, int]]:
    buckets: dict[str, int] = {}
    for day in days:
        key = day["date"][:7]
        buckets[key] = buckets.get(key, 0) + int(day["count"])
    items = sorted(buckets.items())[-12:]
    return [(dt.datetime.strptime(k, "%Y-%m").strftime("%b"), v) for k, v in items]


def svg_text(x: int, y: int, text: str, *, size: int = 16, fill: str, weight: int = 400,
             anchor: str = "start", family: str = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
             letter_spacing: float = 0, preserve_spaces: bool = False) -> str:
    escaped = html.escape(str(text))
    preserve = ""
    if preserve_spaces:
        # SVG normally collapses and removes leading spaces in text nodes.
        # Preserve them explicitly so ASCII art keeps its original shape.
        escaped = escaped.replace(" ", "&#160;")
        preserve = ' xml:space="preserve" style="white-space:pre"'

    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" font-weight="{weight}" '
        f'text-anchor="{anchor}" font-family="{family}" letter-spacing="{letter_spacing}"{preserve}>'
        f'{escaped}</text>'
    )


def render(config: dict[str, Any], metrics: dict[str, Any], portrait: str, theme_name: str) -> str:
    c = THEMES[theme_name]
    width, height = 1100, 760
    display_name = config.get("display_name") or metrics["username"]
    handle = config.get("handle") or f'{metrics["username"]}@github'
    headline = config.get("headline", "SOFTWARE · DATA · SYSTEMS")
    location = config.get("location", "")
    status = config.get("status", "")

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{html.escape(display_name)} GitHub profile dashboard</title>',
        '<desc id="desc">ASCII portrait, profile information, GitHub metrics, contribution trend, and top repositories.</desc>',
        '<style>text{dominant-baseline:alphabetic}.fade{animation:fade 700ms ease-out both}.d1{animation-delay:80ms}.d2{animation-delay:160ms}.d3{animation-delay:240ms}@keyframes fade{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}</style>',
        f'<rect width="100%" height="100%" rx="22" fill="{c["bg"]}"/>',
        f'<rect x="24" y="24" width="1052" height="712" rx="18" fill="{c["panel"]}" stroke="{c["faint"]}"/>',
        f'<line x1="60" y1="112" x2="1040" y2="112" stroke="{c["faint"]}"/>',
        svg_text(60, 72, handle.upper(), size=14, fill=c["accent"], weight=600, letter_spacing=2),
        svg_text(1040, 72, "PROFILE / LIVE PUBLIC METRICS", size=12, fill=c["muted"], anchor="end", letter_spacing=1.5),
    ]

    # Portrait
    portrait_lines = portrait.rstrip("\n").splitlines()
    portrait_y = 154
    for idx, line in enumerate(portrait_lines[:24]):
        parts.append(svg_text(68, portrait_y + idx * 18, line.expandtabs(4), size=13, fill=c["muted"], preserve_spaces=True))

    # Identity
    parts += [
        '<g class="fade d1">',
        svg_text(500, 174, display_name.upper(), size=36, fill=c["text"], weight=700, letter_spacing=1),
        svg_text(500, 208, headline, size=14, fill=c["accent"], weight=600, letter_spacing=1.8),
        f'<line x1="500" y1="232" x2="1026" y2="232" stroke="{c["faint"]}"/>',
        svg_text(500, 264, "LOCATION", size=11, fill=c["muted"], letter_spacing=1.4),
        svg_text(650, 264, location or "—", size=14, fill=c["text"]),
        svg_text(500, 294, "STATUS", size=11, fill=c["muted"], letter_spacing=1.4),
        svg_text(650, 294, status or "—", size=14, fill=c["text"]),
        '</g>',
    ]

    metric_defs = [
        ("CONTRIBUTIONS / 365D", metrics["contributions_365d"]),
        ("PUBLIC REPOSITORIES", metrics["public_repos"]),
        ("STARS EARNED", metrics["stars"]),
        ("PULL REQUESTS / 365D", metrics["pull_requests_365d"]),
        ("FOLLOWERS", metrics["followers"]),
        ("CURRENT STREAK", f'{metrics["current_streak"]}D'),
    ]
    x_positions = [500, 680, 860]
    y_positions = [354, 444]
    parts.append('<g class="fade d2">')
    for i, (label, value) in enumerate(metric_defs):
        col, row = i % 3, i // 3
        x, y = x_positions[col], y_positions[row]
        parts.append(svg_text(x, y, f"{value:,}" if isinstance(value, int) else value, size=28, fill=c["text"], weight=650))
        parts.append(svg_text(x, y + 24, label, size=10, fill=c["muted"], letter_spacing=1.1))
    parts.append('</g>')

    # Contribution line plot
    plot_x, plot_y, plot_w, plot_h = 60, 544, 650, 132
    months = monthly_counts(metrics["days"])
    max_v = max((v for _, v in months), default=1)
    for j in range(4):
        gy = plot_y + j * (plot_h / 3)
        parts.append(f'<line x1="{plot_x}" y1="{gy:.1f}" x2="{plot_x + plot_w}" y2="{gy:.1f}" stroke="{c["grid"]}"/>')
    points = []
    for i, (_, value) in enumerate(months):
        x = plot_x + (i * plot_w / max(1, len(months) - 1))
        y = plot_y + plot_h - (value / max_v) * (plot_h - 10)
        points.append(f"{x:.1f},{y:.1f}")
    if points:
        parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{c["plot"]}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>')
    parts.append(svg_text(plot_x, 516, "CONTRIBUTION ACTIVITY · TRAILING 12 MONTHS", size=11, fill=c["muted"], letter_spacing=1.4))
    for i, (month, _) in enumerate(months):
        x = plot_x + (i * plot_w / max(1, len(months) - 1))
        parts.append(svg_text(round(x), 700, month.upper(), size=9, fill=c["muted"], anchor="middle"))

    # Top repositories
    right_x = 760
    parts.append(svg_text(right_x, 516, "TOP REPOSITORIES · STARS", size=11, fill=c["muted"], letter_spacing=1.4))
    repos = metrics["top_repos"] or [{"name": "No starred repositories yet", "stars": 0}]
    max_stars = max((r["stars"] for r in repos), default=1) or 1
    for i, repo in enumerate(repos[:3]):
        y = 558 + i * 58
        name = repo["name"][:27]
        parts.append(svg_text(right_x, y, name, size=13, fill=c["text"], weight=550))
        parts.append(svg_text(1028, y, str(repo["stars"]), size=12, fill=c["accent"], anchor="end", weight=600))
        bar_w = 245 * repo["stars"] / max_stars
        parts.append(f'<rect x="{right_x}" y="{y + 13}" width="245" height="4" rx="2" fill="{c["grid"]}"/>')
        parts.append(f'<rect x="{right_x}" y="{y + 13}" width="{bar_w:.1f}" height="4" rx="2" fill="{c["accent"]}"/>')

    updated = metrics["updated_at"].strftime("%Y-%m-%d %H:%M UTC")
    parts.append(svg_text(1038, 720, f"UPDATED {updated}", size=9, fill=c["muted"], anchor="end", letter_spacing=1))
    parts.append('</svg>')
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="Render with deterministic sample metrics")
    args = parser.parse_args()

    config = load_json(CONFIG_PATH)
    username = config.get("github_username", "AUTO")
    if not username or username.upper() == "AUTO":
        username = os.environ.get("GITHUB_REPOSITORY_OWNER", "YOUR_USERNAME")

    token = os.environ.get("GITHUB_TOKEN", "")
    if args.mock or not token:
        if not args.mock:
            print("GITHUB_TOKEN not found; rendering sample metrics. Use --mock to silence this notice.", file=sys.stderr)
        metrics = mock_data(username)
    else:
        metrics = fetch_metrics(username, token)

    portrait = PORTRAIT_PATH.read_text(encoding="utf-8")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for theme_name in ("dark", "light"):
        output = OUTPUT_DIR / f"profile-{theme_name}.svg"
        output.write_text(render(config, metrics, portrait, theme_name), encoding="utf-8")
        print(f"Wrote {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

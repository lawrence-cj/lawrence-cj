#!/usr/bin/env python3

import argparse
import json
import math
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path


def github_json(path: str):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "lawrence-cj-readme-stats",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def get_repositories(username: str):
    repositories = []
    page = 1
    while True:
        login = urllib.parse.quote(username, safe="")
        batch = github_json(
            f"/users/{login}/repos?type=owner&sort=full_name&per_page=100&page={page}"
        )
        repositories.extend(batch)
        if len(batch) < 100:
            return repositories
        page += 1


def get_repository(full_name: str):
    owner, name = full_name.split("/", 1)
    owner = urllib.parse.quote(owner, safe="")
    name = urllib.parse.quote(name, safe="")
    return github_json(f"/repos/{owner}/{name}")


def exponential_cdf(value: float) -> float:
    return 1 - 2 ** (-value)


def log_normal_cdf(value: float) -> float:
    return value / (1 + value)


def calculate_rank(commits, pull_requests, issues, reviews, stars, followers):
    score = (
        2 * exponential_cdf(commits / 1000)
        + 3 * exponential_cdf(pull_requests / 50)
        + exponential_cdf(issues / 25)
        + exponential_cdf(reviews / 2)
        + 4 * log_normal_cdf(stars / 50)
        + log_normal_cdf(followers / 10)
    ) / 12
    percentile = (1 - score) * 100
    thresholds = [1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100]
    levels = ["S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]
    level = next(level for threshold, level in zip(thresholds, levels) if percentile <= threshold)
    return level, percentile


def extract_integer(svg: str, pattern: str, label: str) -> int:
    match = re.search(pattern, svg)
    if not match:
        raise RuntimeError(f"Could not find {label} in stats SVG")
    return int(match.group(1))


def replace_once(svg: str, pattern: str, replacement, label: str) -> str:
    updated, count = re.subn(pattern, replacement, svg, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"Could not replace {label} in stats SVG")
    return updated


def format_short(number: int) -> str:
    if abs(number) < 1000:
        return str(number)
    value = round(number / 1000, 1)
    return f"{value:g}k"


def patch_svg(path: Path, stars: int, level: str, percentile: float):
    svg = path.read_text(encoding="utf-8")
    percentile_text = f"{percentile:.1f}%"
    dash_offset = 2 * math.pi * 40 * percentile / 100

    svg = replace_once(
        svg,
        r"(Total Stars Earned:\s*)[\d,.k]+",
        lambda match: f"{match.group(1)}{stars}",
        "accessible star total",
    )
    svg = replace_once(
        svg,
        r'(<title id="titleId">.*?, Rank:\s*)[^<]+',
        lambda match: f"{match.group(1)}{level}",
        "accessible rank",
    )
    svg = replace_once(
        svg,
        r'(data-testid="stars"\s*>\s*)[^<]+',
        lambda match: f"{match.group(1)}{format_short(stars)}",
        "visible star total",
    )
    svg = replace_once(
        svg,
        r'(data-testid="percentile-rank-value"[^>]*>\s*)[^<]+',
        lambda match: f"{match.group(1)}{percentile_text}",
        "visible percentile",
    )
    svg = replace_once(
        svg,
        r"(\bto\s*\{\s*stroke-dashoffset:\s*)[0-9.]+",
        lambda match: f"{match.group(1)}{dash_offset}",
        "rank circle",
    )
    path.write_text(svg, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--extra-repo", action="append", default=[])
    parser.add_argument("--svg", action="append", required=True)
    args = parser.parse_args()

    repositories = get_repositories(args.username)
    seen = {repo["full_name"].lower() for repo in repositories}
    owned_stars = sum(repo["stargazers_count"] for repo in repositories)
    extra_stars = 0
    for full_name in args.extra_repo:
        if full_name.lower() in seen:
            continue
        extra_stars += get_repository(full_name)["stargazers_count"]
        seen.add(full_name.lower())
    total_stars = owned_stars + extra_stars

    first_svg = Path(args.svg[0]).read_text(encoding="utf-8")
    commits = extract_integer(first_svg, r"Total Commits\s*:\s*(\d+)", "commits")
    pull_requests = extract_integer(first_svg, r"Total PRs:\s*(\d+)", "pull requests")
    reviews = extract_integer(first_svg, r"Total PRs Reviewed:\s*(\d+)", "reviews")
    issues = extract_integer(first_svg, r"Total Issues:\s*(\d+)", "issues")
    user = github_json(f"/users/{urllib.parse.quote(args.username, safe='')}")
    level, percentile = calculate_rank(
        commits,
        pull_requests,
        issues,
        reviews,
        total_stars,
        user["followers"],
    )

    for svg_path in args.svg:
        patch_svg(Path(svg_path), total_stars, level, percentile)

    print(
        f"Stars: {total_stars} ({owned_stars} owned + {extra_stars} core projects); "
        f"rank: {level}, top {percentile:.1f}%"
    )


if __name__ == "__main__":
    main()

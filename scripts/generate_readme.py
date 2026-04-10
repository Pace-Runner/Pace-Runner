import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

README_PATH = "README.md"
START_MARKER = "<!-- AUTO-GENERATED-REPOS:START -->"
END_MARKER = "<!-- AUTO-GENERATED-REPOS:END -->"


def get_username() -> str:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()
    env_username = os.environ.get("GITHUB_USERNAME") or os.environ.get("GITHUB_REPOSITORY_OWNER")
    if env_username:
        return env_username.strip()
    raise RuntimeError(
        "GitHub username not found. Set GITHUB_USERNAME or pass username as first script argument."
    )


def github_get_json(url: str, token: str | None = None) -> list[dict]:
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_repositories(username: str) -> list[dict]:
    token = os.environ.get("GITHUB_TOKEN")
    repos: list[dict] = []

    page = 1
    while True:
        query = urllib.parse.urlencode(
            {
                "per_page": 100,
                "page": page,
                "sort": "pushed",
                "direction": "desc",
                "type": "owner",
            }
        )
        url = f"https://api.github.com/users/{username}/repos?{query}"

        try:
            page_items = github_get_json(url, token=token)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise RuntimeError(f"GitHub user '{username}' was not found.") from exc
            raise RuntimeError(f"GitHub API error while fetching repos: HTTP {exc.code}") from exc

        if not page_items:
            break

        repos.extend(page_items)
        page += 1

    return repos


def relative_days_since(iso_string: str | None) -> int:
    if not iso_string:
        return 9999
    dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return (now - dt).days


def status_badge(repo: dict) -> str:
    if repo.get("archived"):
        return "Archived"
    if repo.get("fork"):
        return "Fork"
    if relative_days_since(repo.get("pushed_at")) <= 90:
        return "Active"
    return "Maintained"


def classify_theme(repo: dict) -> str:
    name = (repo.get("name") or "").lower()
    description = (repo.get("description") or "").lower()
    language = (repo.get("language") or "").lower()
    haystack = f"{name} {description}"

    cybersecurity_keywords = [
        "security",
        "cyber",
        "iam",
        "s3",
        "cloudtrail",
        "cloudwatch",
        "scanner",
        "threat",
        "monitoring",
        "vulnerability",
    ]
    algorithms_keywords = [
        "algorithm",
        "bfs",
        "graph",
        "sudoku",
        "solver",
        "backtracking",
        "maze",
        "heuristic",
        "coloring",
    ]
    finance_keywords = [
        "finance",
        "trading",
        "valuation",
        "sp500",
        "nas100",
        "market",
        "stock",
        "quant",
    ]
    software_keywords = [
        "app",
        "api",
        "portfolio",
        "android",
        "website",
        "web",
        "project",
    ]

    if any(keyword in haystack for keyword in cybersecurity_keywords):
        return "Cyber Security"
    if any(keyword in haystack for keyword in algorithms_keywords):
        return "Algorithms"
    if any(keyword in haystack for keyword in finance_keywords):
        return "Software Finance"
    if any(keyword in haystack for keyword in software_keywords):
        return "Software"

    if language in {"c++", "java", "python", "javascript"}:
        return "Software"
    return "Other"


def format_repo_table(repos: list[dict]) -> str:
    lines = [
        "| # | Repository | Description | Status | Last Push |",
        "|---:|---|---|---|---|",
    ]

    for index, repo in enumerate(repos, start=1):
        description = (repo.get("description") or "No description yet.").replace("|", "\\|")
        name = repo["name"]
        html_url = repo["html_url"]
        status = status_badge(repo)
        pushed = (repo.get("pushed_at") or "").split("T")[0] or "-"
        lines.append(
            f"| {index} | [{name}]({html_url}) | {description} | {status} | {pushed} |"
        )

    if len(repos) == 0:
        lines.append("| - | No repositories found | - | - | - |")

    return "\n".join(lines)


def format_theme_groups(repos: list[dict]) -> str:
    groups: dict[str, list[dict]] = {
        "Cyber Security": [],
        "Algorithms": [],
        "Software Finance": [],
        "Software": [],
        "Other": [],
    }

    for repo in repos:
        groups[classify_theme(repo)].append(repo)

    ordered_sections = [
        "Cyber Security",
        "Algorithms",
        "Software Finance",
        "Software",
        "Other",
    ]

    lines: list[str] = []
    for section in ordered_sections:
        items = sorted(groups[section], key=lambda r: r["name"].lower())
        if not items:
            continue

        lines.append(f"### {section} ({len(items)})")
        for repo in items:
            desc = repo.get("description") or "No description yet."
            lines.append(f"- [{repo['name']}]({repo['html_url']}) - {desc}")
        lines.append("")

    return "\n".join(lines).strip()


def format_newest_additions(repos: list[dict], max_items: int = 10) -> str:
    sorted_by_created = sorted(
        repos,
        key=lambda r: r.get("created_at") or "",
        reverse=True,
    )
    lines = []
    for repo in sorted_by_created[:max_items]:
        created = (repo.get("created_at") or "").split("T")[0] or "-"
        lines.append(f"- {created}: [{repo['name']}]({repo['html_url']})")
    return "\n".join(lines) if lines else "- No repositories found"


def build_generated_block(username: str, repos: list[dict]) -> str:
    non_fork_repos = [r for r in repos if not r.get("fork")]
    total_repos = len(non_fork_repos)
    active_count = len([r for r in non_fork_repos if status_badge(r) == "Active"])
    archived_count = len([r for r in non_fork_repos if r.get("archived")])

    ordered_repos = sorted(
        non_fork_repos,
        key=lambda r: (r.get("pushed_at") or ""),
        reverse=True,
    )

    generated_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""{START_MARKER}
## Repository Dashboard (Auto-Updated)

<p align=\"left\"> 
  <img src=\"https://img.shields.io/badge/Total%20Repos-{total_repos}-0b7285?style=for-the-badge\" alt=\"total repos\" />
  <img src=\"https://img.shields.io/badge/Active%20(90d)-{active_count}-2b8a3e?style=for-the-badge\" alt=\"active repos\" />
  <img src=\"https://img.shields.io/badge/Archived-{archived_count}-495057?style=for-the-badge\" alt=\"archived repos\" />
</p>

_Last generated: {generated_on}_

### Ordered Repository List

{format_repo_table(ordered_repos)}

### Categorized By Project Theme

{format_theme_groups(ordered_repos)}

### Newest Repositories Added

{format_newest_additions(non_fork_repos)}

{END_MARKER}"""


def replace_generated_block(content: str, replacement_block: str) -> str:
    if START_MARKER in content and END_MARKER in content:
        prefix = content.split(START_MARKER)[0]
        suffix = content.split(END_MARKER)[1]
        return prefix.rstrip() + "\n\n" + replacement_block + "\n" + suffix.lstrip()

    return content.rstrip() + "\n\n" + replacement_block + "\n"


def main() -> int:
    username = get_username()
    repos = fetch_repositories(username)

    if not os.path.exists(README_PATH):
        raise RuntimeError("README.md not found in current directory.")

    with open(README_PATH, "r", encoding="utf-8") as readme_file:
        content = readme_file.read()

    generated_block = build_generated_block(username, repos)
    updated_content = replace_generated_block(content, generated_block)

    with open(README_PATH, "w", encoding="utf-8", newline="\n") as readme_file:
        readme_file.write(updated_content)

    print(f"README updated for user '{username}' with {len(repos)} repositories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

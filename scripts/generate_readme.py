import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

README_PATH = "README.md"
STATE_PATH = ".github/repo-state.json"
HISTORY_PATH = ".github/repo-history.json"
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


def normalize_language(language: str | None) -> str:
    return language if language else "Other"


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


def ensure_parent_dir(file_path: str) -> None:
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def load_json_file(file_path: str, default_value):
    if not os.path.exists(file_path):
        return default_value
    with open(file_path, "r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def save_json_file(file_path: str, data) -> None:
    ensure_parent_dir(file_path)
    with open(file_path, "w", encoding="utf-8", newline="\n") as file_obj:
        json.dump(data, file_obj, indent=2)
        file_obj.write("\n")


def build_repo_state(repos: list[dict]) -> dict[str, dict]:
    state = {}
    for repo in repos:
        if repo.get("fork"):
            continue
        state[repo["name"]] = {
            "url": repo.get("html_url"),
            "created_at": repo.get("created_at"),
            "pushed_at": repo.get("pushed_at"),
            "archived": bool(repo.get("archived")),
            "language": normalize_language(repo.get("language")),
        }
    return state


def build_update_history(current_state: dict[str, dict]) -> list[dict]:
    previous_state = load_json_file(STATE_PATH, {})
    previous_history = load_json_file(HISTORY_PATH, [])
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    new_events: list[dict] = []

    for repo_name, current in sorted(current_state.items(), key=lambda item: item[0].lower()):
        old = previous_state.get(repo_name)
        if old is None:
            new_events.append(
                {
                    "date": now_date,
                    "type": "added",
                    "repo": repo_name,
                    "url": current.get("url"),
                }
            )
            continue

        if current.get("pushed_at") and current.get("pushed_at") != old.get("pushed_at"):
            new_events.append(
                {
                    "date": now_date,
                    "type": "updated",
                    "repo": repo_name,
                    "url": current.get("url"),
                }
            )

        if current.get("archived") != old.get("archived"):
            new_events.append(
                {
                    "date": now_date,
                    "type": "archived" if current.get("archived") else "unarchived",
                    "repo": repo_name,
                    "url": current.get("url"),
                }
            )

    dedupe_keys = set()
    merged_history: list[dict] = []

    for event in (new_events + previous_history):
        key = (event.get("date"), event.get("type"), event.get("repo"))
        if key in dedupe_keys:
            continue
        dedupe_keys.add(key)
        merged_history.append(event)

    merged_history = merged_history[:200]

    save_json_file(STATE_PATH, current_state)
    save_json_file(HISTORY_PATH, merged_history)

    return merged_history


def format_repo_table(repos: list[dict]) -> str:
    lines = [
        "| # | Repository | Description | Category | Last Push |",
        "|---:|---|---|---|---|",
    ]

    for index, repo in enumerate(repos, start=1):
        description = (repo.get("description") or "No description yet.").replace("|", "\\|")
        name = repo["name"]
        html_url = repo["html_url"]
        category = status_badge(repo)
        pushed = (repo.get("pushed_at") or "").split("T")[0] or "-"
        lines.append(
            f"| {index} | [{name}]({html_url}) | {description} | {category} | {pushed} |"
        )

    if len(repos) == 0:
        lines.append("| - | No repositories found | - | - | - |")

    return "\n".join(lines)


def format_language_groups(repos: list[dict]) -> str:
    groups: dict[str, list[dict]] = defaultdict(list)
    for repo in repos:
        groups[normalize_language(repo.get("language"))].append(repo)

    sorted_groups = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0].lower()))

    lines: list[str] = []
    for language, items in sorted_groups:
        lines.append(f"### {language} ({len(items)})")
        for repo in sorted(items, key=lambda r: r["name"].lower()):
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


def format_history_feed(history: list[dict], max_items: int = 20) -> str:
    if not history:
        return "- No tracked updates yet."

    type_map = {
        "added": "Added",
        "updated": "Updated",
        "archived": "Archived",
        "unarchived": "Unarchived",
    }

    lines: list[str] = []
    for event in history[:max_items]:
        label = type_map.get(event.get("type"), "Updated")
        date = event.get("date", "-")
        repo = event.get("repo", "unknown-repo")
        url = event.get("url") or "#"
        lines.append(f"- {date}: {label} [{repo}]({url})")
    return "\n".join(lines)


def build_generated_block(username: str, repos: list[dict], history: list[dict]) -> str:
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

### Categorized By Primary Language

{format_language_groups(ordered_repos)}

### Newest Repositories Added

{format_newest_additions(non_fork_repos)}

### Update Feed (Tracked History)

{format_history_feed(history)}

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
    current_state = build_repo_state(repos)
    history = build_update_history(current_state)

    if not os.path.exists(README_PATH):
        raise RuntimeError("README.md not found in current directory.")

    with open(README_PATH, "r", encoding="utf-8") as readme_file:
        content = readme_file.read()

    generated_block = build_generated_block(username, repos, history)
    updated_content = replace_generated_block(content, generated_block)

    with open(README_PATH, "w", encoding="utf-8", newline="\n") as readme_file:
        readme_file.write(updated_content)

    print(f"README updated for user '{username}' with {len(repos)} repositories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

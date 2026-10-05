"""Publish generated scraper wrappers to the durable scraper-builds branch."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BRANCH = "scraper-builds"


def api(method: str, path: str, payload: dict | None = None) -> dict:
    token = os.environ["GH_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    request = Request(f"https://api.github.com/repos/{repo}/{path}",
                     data=json.dumps(payload).encode() if payload is not None else None,
                     method=method, headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json", "Content-Type": "application/json",
                     "X-GitHub-Api-Version": "2022-11-28"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def read_file(path: str) -> tuple[str | None, str | None]:
    try:
        obj = api("GET", f"contents/{path}?ref={BRANCH}")
    except HTTPError as exc:
        if exc.code == 404:
            return None, None
        raise
    return base64.b64decode(obj["content"]).decode(), obj["sha"]


def publish(root: Path) -> int:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        print("No generated scraper files to publish")
        return 0
    try:
        api("GET", f"git/ref/heads/{BRANCH}")
    except HTTPError as exc:
        if exc.code != 404:
            raise
        api("POST", "git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": os.environ["GITHUB_SHA"]})
    for path in files:
        relative = path.relative_to(root.parent.parent).as_posix()
        _, sha = read_file(relative)
        payload = {"message": f"Build scraper profile {path.stem}", "branch": BRANCH,
                   "content": base64.b64encode(path.read_bytes()).decode()}
        if sha:
            payload["sha"] = sha
        api("PUT", f"contents/{relative}", payload)
    print(f"Published {len(files)} generated scraper files to {BRANCH}")
    return len(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    publish(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

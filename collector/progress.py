"""Durable public queue cursor stored on a dedicated GitHub branch."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from collector.manual_run import load_queue, queue_digest

BRANCH = "collector-progress"
FILE = "progress.json"


def next_index(state: dict | None, queue: list[str]) -> int:
    if state is None:
        return 0
    if state.get("schema_version") != 1 or state.get("queue_sha256") != queue_digest(queue):
        raise ValueError("public queue changed; cursor migration requires review")
    index = state.get("next_start_index")
    if type(index) is not int or not 0 <= index <= len(queue):
        raise ValueError("invalid saved cursor")
    return index


def request(method: str, path: str, payload: dict | None = None) -> dict:
    token = os.environ["GH_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    url = f"https://api.github.com/repos/{repo}/{path}"
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=body, method=method, headers={"Authorization": f"Bearer {token}",
                  "Accept": "application/vnd.github+json", "Content-Type": "application/json",
                  "X-GitHub-Api-Version": "2022-11-28"})
    with urlopen(req, timeout=20) as response:
        return json.load(response)


def read_remote() -> tuple[dict | None, str | None]:
    try:
        obj = request("GET", f"contents/{FILE}?ref={BRANCH}")
    except HTTPError as exc:
        if exc.code == 404:
            return None, None
        raise
    raw = base64.b64decode(obj["content"])
    return json.loads(raw), obj["sha"]


def prepare(queue_path: Path, output: Path) -> None:
    queue = load_queue(queue_path)
    state, _ = read_remote()
    index = next_index(state, queue)
    output.write_text(str(index) + "\n", encoding="ascii")
    print(f"Public queue position: {index}/{len(queue)}")


def publish(queue_path: Path, result_path: Path) -> None:
    queue = load_queue(queue_path)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    state, content_sha = read_remote()
    index = next_index(state, queue)
    if (result.get("schema_version") != 1 or result.get("queue_sha256") != queue_digest(queue)
            or result.get("start_index") != index or result.get("next_start_index") != index + result.get("processed", -1)
            or result.get("processed") != len(result.get("results", []))
            or [item.get("domain") for item in result["results"]]
               != queue[index:result["next_start_index"]]
            or result.get("processed", 0) < 1):
        raise ValueError("run result does not advance the current queue")
    if state is None:
        try:
            request("POST", "git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": os.environ["GITHUB_SHA"]})
        except HTTPError as exc:
            if exc.code != 422:
                raise
            raise ValueError("progress branch appeared concurrently; retry after review") from exc
    new_state = {"schema_version": 1, "queue_sha256": queue_digest(queue),
                 "next_start_index": result["next_start_index"], "queue_size": len(queue),
                 "last_run_id": os.environ["GITHUB_RUN_ID"], "last_release_sha": os.environ["GITHUB_SHA"]}
    payload = {"message": f"Advance public collector cursor to {new_state['next_start_index']}",
               "branch": BRANCH, "content": base64.b64encode((json.dumps(new_state, indent=2) + "\n").encode()).decode()}
    if content_sha is not None:
        payload["sha"] = content_sha
    request("PUT", f"contents/{FILE}", payload)
    print(f"Saved public queue position: {new_state['next_start_index']}/{len(queue)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "publish"))
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.queue, args.file)
    else:
        publish(args.queue, args.file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

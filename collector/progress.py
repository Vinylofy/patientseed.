"""Durable public queue cursor stored on a dedicated GitHub branch."""
from __future__ import annotations

import argparse
import base64
import json
import os
import zlib
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from collector.manual_run import load_queue, queue_digest

BRANCH = "collector-progress"
FILE = "progress.json"


def unpack_state(data: dict) -> dict:
    if data.get("history_encoding") == "zlib+base64":
        packed = base64.b64decode(data["history_z"], validate=True)
        if len(packed) > 2_000_000:
            raise ValueError("progress payload too large")
        inflater = zlib.decompressobj()
        raw = inflater.decompress(packed, 10_000_001)
        if len(raw) > 10_000_000 or not inflater.eof or inflater.unused_data:
            raise ValueError("invalid or oversized progress history")
        history = json.loads(raw)
        if not isinstance(history, list) or len(history) > 100_000:
            raise ValueError("invalid progress history")
        return {key: value for key, value in data.items() if key not in ("history_encoding", "history_z")} | {"history": history}
    return data


def pack_state(data: dict) -> dict:
    history = data["history"]
    packed = zlib.compress(json.dumps(history, ensure_ascii=False, separators=(",", ":")).encode(), level=9)
    return {key: value for key, value in data.items() if key != "history"} | {
        "history_encoding": "zlib+base64", "history_z": base64.b64encode(packed).decode()}


def next_index(state: dict | None, queue: list[dict]) -> int:
    if state is None:
        return 0
    prior_size = state.get("queue_size")
    if (state.get("schema_version") != 1 or type(prior_size) is not int
            or not 0 < prior_size <= len(queue)
            or state.get("queue_sha256") != queue_digest(queue[:prior_size])):
        raise ValueError("processed queue prefix changed; cursor migration requires review")
    index = state.get("next_start_index")
    if type(index) is not int or not 0 <= index <= prior_size:
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
    return unpack_state(json.loads(raw)), obj["sha"]


def prepare(queue_path: Path, output: Path) -> None:
    queue = load_queue(queue_path)
    state, _ = read_remote()
    index = next_index(state, queue)
    if index == len(queue):
        raise ValueError("all queued shop rows have a source status; review exception queue before another run")
    output.write_text(str(index) + "\n", encoding="ascii")
    print(f"Public queue position: {index}/{len(queue)}")


def publish(queue_path: Path, result_path: Path) -> None:
    queue = load_queue(queue_path)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    state, content_sha = read_remote()
    index = next_index(state, queue)
    if state is not None and len(state.get("history", [])) != index:
        raise ValueError("saved history does not match the cursor")
    if (result.get("schema_version") != 1 or result.get("queue_sha256") != queue_digest(queue)
            or result.get("complete") is not True
            or result.get("start_index") != index or result.get("next_start_index") != index + result.get("processed", -1)
            or result.get("processed") != len(result.get("results", []))
            or [(item.get("row"), item.get("domain")) for item in result["results"]]
               != [(item["row"], item["domain"]) for item in queue[index:result["next_start_index"]]]
            or result.get("processed", 0) < 1):
        raise ValueError("run result does not advance the current queue")
    if state is None:
        try:
            request("POST", "git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": os.environ["GITHUB_SHA"]})
        except HTTPError as exc:
            if exc.code != 422:
                raise
            raise ValueError("progress branch appeared concurrently; retry after review") from exc
    history = list(state.get("history", [])) if state else []
    batch_number = (state.get("batch_number", 0) if state else 0) + 1
    history.extend({"batch": batch_number, "run_id": os.environ["GITHUB_RUN_ID"],
                    **{key: item[key] for key in ("row", "domain", "status", "gate", "platform", "adapter_class",
                                                "adapter_status", "source_url",
                                                "reason", "products_seen", "accepted", "excluded",
                                                "listing_gtin_valid", "detail_checked", "detail_gtin_valid",
                                                "detail_status", "detail_reason") if key in item}}
                   for item in result["results"])
    new_state = {"schema_version": 1, "queue_sha256": queue_digest(queue),
                 "next_start_index": result["next_start_index"], "queue_size": len(queue),
                 "last_run_id": os.environ["GITHUB_RUN_ID"], "last_release_sha": os.environ["GITHUB_SHA"],
                 "batch_number": batch_number, "history": history}
    payload = {"message": f"Advance public collector cursor to {new_state['next_start_index']}",
               "branch": BRANCH, "content": base64.b64encode((json.dumps(pack_state(new_state), separators=(",", ":")) + "\n").encode()).decode()}
    if content_sha is not None:
        payload["sha"] = content_sha
    request("PUT", f"contents/{FILE}", payload)
    print(f"Saved public queue position: {new_state['next_start_index']}/{len(queue)}")


def export(queue_path: Path, output: Path) -> None:
    queue = load_queue(queue_path)
    state, _ = read_remote()
    if state is None:
        raise ValueError("no saved progress to export")
    next_index(state, queue)
    output.write_text(json.dumps(state, ensure_ascii=False) + "\n", encoding="utf-8")


def reset(queue_path: Path) -> None:
    """Explicitly restart the public queue; only called by a manual reset input."""
    queue = load_queue(queue_path)
    state, content_sha = read_remote()
    if state is None:
        try:
            request("POST", "git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": os.environ["GITHUB_SHA"]})
        except HTTPError as exc:
            if exc.code != 422:
                raise
            raise ValueError("progress branch appeared concurrently; retry reset") from exc
    new_state = {"schema_version": 1, "queue_sha256": queue_digest(queue),
                 "next_start_index": 0, "queue_size": len(queue), "batch_number": (state or {}).get("batch_number", 0),
                 "history": [], "last_run_id": os.environ.get("GITHUB_RUN_ID", "reset"),
                 "last_release_sha": os.environ.get("GITHUB_SHA", "")}
    payload = {"message": "Reset public collector cursor to first shop row", "branch": BRANCH,
               "content": base64.b64encode((json.dumps(pack_state(new_state), separators=(",", ":")) + "\n").encode()).decode()}
    if content_sha is not None:
        payload["sha"] = content_sha
    request("PUT", f"contents/{FILE}", payload)
    print(f"Reset public queue position: 0/{len(queue)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "publish", "export", "reset"))
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()
    if args.command != "reset" and args.file is None:
        parser.error("--file is required for prepare, publish and export")
    if args.command == "prepare":
        prepare(args.queue, args.file)
    elif args.command == "publish":
        publish(args.queue, args.file)
    elif args.command == "export":
        export(args.queue, args.file)
    else:
        reset(args.queue)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

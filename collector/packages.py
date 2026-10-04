from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

from collector.contracts import CollectionBlocked


def json_bytes(data: object) -> bytes:
    return (json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_bundle(destination: Path, files: dict[str, bytes]) -> None:
    # Never overwrite an existing artifact; separate code and observation packages.
    if destination.exists():
        raise CollectionBlocked("Artifact already exists")
    for name in files:
        path = PurePosixPath(name)
        if (path.is_absolute() or ".." in path.parts or "\\" in name
                or any(part.startswith(".") for part in path.parts)):
            raise CollectionBlocked("Invalid package path")
    destination.mkdir(parents=True)
    for name, raw in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def release_package(repo: Path, destination: Path, *, commit: str, repository: str,
                    allowed_files: tuple[str, ...], tests: dict, dependencies: list[str]) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise CollectionBlocked("Exact commit required")
    if type(tests.get("passed")) is not int or tests["passed"] < 1 or tests.get("failed") != 0:
        raise CollectionBlocked("Completed green tests required")
    if not allowed_files or len(allowed_files) != len(set(allowed_files)) or "manifest.json" in allowed_files:
        raise CollectionBlocked("Explicit file allowlist required")
    files = {}
    for name in allowed_files:
        path = PurePosixPath(name)
        if (path.is_absolute() or ".." in path.parts or "\\" in name
                or path.suffix not in {".py", ".json", ".csv", ".txt"}
                or any(part.startswith(".") for part in path.parts)):
            raise CollectionBlocked("Disallowed release file")
        # Read precisely the committed object. Never execute code from a branch or artifact.
        files[name] = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{name}"],
                                     check=True, capture_output=True).stdout
    manifest = {"kind": "release", "schema_version": 1, "repository": repository, "commit": commit,
                "files": {name: checksum(raw) for name, raw in files.items()},
                "tests": tests, "dependencies": dependencies}
    raw = json_bytes(manifest)
    write_bundle(destination, {**files, "manifest.json": raw})
    return checksum(raw)


def data_package(destination: Path, *, metadata: dict, listings: list[dict]) -> str:
    required = {"shop_id", "repository", "release_commit", "release_manifest_sha256", "run_id",
                "runner_class", "runner_market", "target_market", "observed_country", "currency",
                "started_at", "finished_at", "source_urls", "pagination"}
    if set(metadata) != required:
        raise CollectionBlocked("Complete data provenance required")
    if metadata["runner_class"] == "github-hosted" and metadata["runner_market"] != "unknown":
        raise CollectionBlocked("GitHub location must be recorded as unknown")
    if not listings or any(row.get("condition") != "new" or row.get("product_type") != "vinyl" for row in listings):
        raise CollectionBlocked("Confirmed new vinyl only")
    raw_listings = json_bytes({"listings": listings})
    manifest = {**metadata, "schema_version": 1, "kind": "data",
                "counts": {"accepted": len(listings)}, "files": {"listings.json": checksum(raw_listings)}}
    raw_manifest = json_bytes(manifest)
    write_bundle(destination, {"manifest.json": raw_manifest, "listings.json": raw_listings})
    return checksum(raw_manifest)

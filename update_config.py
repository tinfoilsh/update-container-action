"""Rewrite tinfoil-config.yml image lines for the container release action.

Reads IMAGE_REFS and VERSION from the environment and pins each image line in
tinfoil-config.yml to the supplied digest. This is the "update config" step of
the action; the "create tag" step lives entirely in action.yml.

Idempotent: applying the same digests twice produces an identical file, so the
caller uses `git diff` to decide whether a pull request is needed — this script
keeps no tag/PR awareness of its own.

Pure functions live above main() and are unit-tested in tests/.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE = Path("tinfoil-config.yml")
DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


@dataclass(frozen=True)
class Pair:
    image: str
    digest: str


class ActionError(Exception):
    """Raised when the action cannot proceed and the user needs to fix something.

    main() catches this and emits a ::error:: line, then exits.
    """


def parse_list(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def parse_refs(refs_raw: str) -> list[Pair]:
    refs = parse_list(refs_raw)
    if not refs:
        raise ActionError("No image references provided")
    pairs = []
    for ref in refs:
        if "@" not in ref:
            raise ActionError(f"Invalid image reference (missing '@'): {ref}")
        image, digest = ref.split("@", 1)
        if not image:
            raise ActionError(f"Invalid image reference (empty image): {ref}")
        if not DIGEST_RE.match(digest):
            raise ActionError(
                f"Invalid digest format in {ref}: {digest}. "
                f"Expected sha256:<64 hex characters>"
            )
        pairs.append(Pair(image, digest))
    return pairs


def update_image_line(config: str, pair: Pair, version: str) -> str:
    pattern = re.compile(
        rf'image:\s*"{re.escape(pair.image)}[:@][^"]*".*$',
        re.MULTILINE,
    )
    replacement = f'image: "{pair.image}@{pair.digest}" # {version}'
    new_config, n = pattern.subn(replacement, config)
    if n == 0:
        raise ActionError(f"Could not find image line for {pair.image} in config")
    return new_config


def apply_updates(config: str, pairs: list[Pair], version: str) -> str:
    for p in pairs:
        config = update_image_line(config, p, version)
    return config


def env(name: str) -> str:
    val = os.environ.get(name)
    if val is None:
        raise ActionError(f"Required environment variable not set: {name}")
    return val


def main() -> None:
    try:
        pairs = parse_refs(env("IMAGE_REFS"))
        version = env("VERSION").strip()

        if not CONFIG_FILE.exists():
            raise ActionError(f"{CONFIG_FILE} not found")

        config = CONFIG_FILE.read_text()
        updated = apply_updates(config, pairs, version)
        if updated == config:
            print(f"{CONFIG_FILE} already has the requested digest(s)")
            return
        CONFIG_FILE.write_text(updated)
        print(f"Updated {len(pairs)} image/digest pair(s) in {CONFIG_FILE}")
    except ActionError as e:
        print(f"::error::{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

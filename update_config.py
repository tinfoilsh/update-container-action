"""Plan and apply tinfoil-config.yml updates for the container release action.

Reads IMAGES, DIGESTS, VERSION from the environment, mutates tinfoil-config.yml
when needed, and emits needs_config_update / needs_tag to $GITHUB_OUTPUT.

Pure functions live above main() and are unit-tested in tests/.
"""

from __future__ import annotations

import os
import re
import subprocess
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


def parse_pairs(images_raw: str, digests_raw: str) -> list[Pair]:
    images = parse_list(images_raw)
    digests = parse_list(digests_raw)
    if not images:
        raise ActionError("No images provided")
    if not digests:
        raise ActionError("No digests provided")
    if len(images) != len(digests):
        raise ActionError(
            f"Mismatch: got {len(images)} image(s) but {len(digests)} digest(s)"
        )
    for d in digests:
        if not DIGEST_RE.match(d):
            raise ActionError(
                f"Invalid digest format: {d}. Expected sha256:<64 hex characters>"
            )
    return [Pair(i, d) for i, d in zip(images, digests)]


def already_pinned(config: str, pairs: list[Pair]) -> bool:
    return all(f'image: "{p.image}@{p.digest}"' in config for p in pairs)


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


def remote_tag_config(version: str) -> str | None:
    """Return tinfoil-config.yml at the remote tag.

    Returns None if the tag doesn't exist. Raises ActionError if the tag exists
    but the config file can't be read at it.
    """
    ref = f"refs/tags/{version}"
    ls = subprocess.run(
        ["git", "ls-remote", "--tags", "origin", ref],
        capture_output=True,
        text=True,
        check=True,
    )
    if not ls.stdout.strip():
        return None
    subprocess.run(["git", "fetch", "origin", f"{ref}:{ref}"], check=True)
    show = subprocess.run(
        ["git", "show", f"{version}:{CONFIG_FILE}"],
        capture_output=True,
        text=True,
    )
    if show.returncode != 0:
        raise ActionError(
            f"Tag {version} exists but {CONFIG_FILE} could not be read at it: "
            f"{show.stderr.strip() or 'git show failed'}"
        )
    return show.stdout


def env(name: str) -> str:
    val = os.environ.get(name)
    if val is None:
        raise ActionError(f"Required environment variable not set: {name}")
    return val


def set_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        raise ActionError("GITHUB_OUTPUT is not set; this script must run inside a GitHub Action")
    with open(out, "a") as f:
        f.write(f"{name}={value}\n")


def main() -> None:
    try:
        pairs = parse_pairs(env("IMAGES"), env("DIGESTS"))
        version = env("VERSION").strip()

        if not CONFIG_FILE.exists():
            raise ActionError(f"{CONFIG_FILE} not found")

        # Check if the requested tag already exists
        tag_config = remote_tag_config(version)
        if tag_config is not None:
            # If tag exists, check if the hashes are already pinned correctly
            if already_pinned(tag_config, pairs):
                print(f"::notice::Tag {version} already exists with correct digest(s) — nothing to do")
                set_output("needs_config_update", "false")
                set_output("needs_tag", "false")
                return
            # If the tag exists but the hashes are not already pinned correctly,
            # then the state is inconsistent. The user should bump up to the next
            # version and rerun the action.
            raise ActionError(f"Tag {version} already exists but has different digest(s). Rerun this workflow with the next version number.")

        # If the tag does not already exist but the config file already has the
        # correct hashes (e.g. the hashes did not change), then we don't need to
        # commit changes or open a new PR.
        current = CONFIG_FILE.read_text()
        if already_pinned(current, pairs):
            print(f"::notice::{CONFIG_FILE} already has correct digest(s) — skipping to tag push")
            set_output("needs_config_update", "false")
            set_output("needs_tag", "true")
            return

        updated = apply_updates(current, pairs, version)
        CONFIG_FILE.write_text(updated)
        print(f"Updated {len(pairs)} image/digest pair(s) in {CONFIG_FILE}")
        set_output("needs_config_update", "true")
        set_output("needs_tag", "true")
    except ActionError as e:
        print(f"::error::{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

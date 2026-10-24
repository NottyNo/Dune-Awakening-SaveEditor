"""Small, dependency-free GitHub Releases update checker."""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dune_save_editor import __version__

RELEASES_API_URL = (
    "https://api.github.com/repos/NottyNo/Dune-Awakening-SaveEditor/releases?per_page=20"
)
RELEASES_PAGE_URL = "https://github.com/NottyNo/Dune-Awakening-SaveEditor/releases"
_MAX_RESPONSE_BYTES = 1_000_000
_VERSION_PATTERN = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:[-_.]?(?P<label>alpha|a|beta|b|rc)[-_.]?(?P<number>\d+))?$",
    re.IGNORECASE,
)
_PRERELEASE_ORDER = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "rc": 2}


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    """The user-facing fields from one published GitHub release."""

    tag_name: str
    name: str
    prerelease: bool


def parse_release_version(value: str) -> tuple[int, int, int, int, int] | None:
    """Normalize the project's PEP 440 and GitHub tag version styles."""

    match = _VERSION_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    label = match.group("label")
    stage = 3 if label is None else _PRERELEASE_ORDER[label.casefold()]
    prerelease_number = 0 if label is None else int(match.group("number"))
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        stage,
        prerelease_number,
    )


def is_newer_release(candidate_tag: str, current_version: str) -> bool:
    """Return true only when both versions are recognized and the candidate is newer."""

    candidate = parse_release_version(candidate_tag)
    current = parse_release_version(current_version)
    return candidate is not None and current is not None and candidate > current


def newest_published_release(payload: object) -> ReleaseInfo | None:
    """Select the first published, non-draft release from GitHub's newest-first response."""

    if not isinstance(payload, list):
        return None
    for entry in payload:
        if not isinstance(entry, dict) or entry.get("draft") or not entry.get("published_at"):
            continue
        tag_name = entry.get("tag_name")
        if not isinstance(tag_name, str) or not tag_name.strip():
            continue
        name = entry.get("name")
        return ReleaseInfo(
            tag_name=tag_name.strip(),
            name=name.strip() if isinstance(name, str) else "",
            prerelease=bool(entry.get("prerelease")),
        )
    return None


def check_for_update(
    current_version: str,
    *,
    timeout: float = 5.0,
    opener: Callable[..., Any] | None = None,
) -> ReleaseInfo | None:
    """Return a newer published release, or ``None`` on no update or any network error."""

    request = urllib.request.Request(
        RELEASES_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"Dune-Awakening-SaveEditor/{__version__}",
        },
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            return None
        release = newest_published_release(json.loads(raw.decode("utf-8")))
    except (OSError, UnicodeError, ValueError):
        return None
    if release and is_newer_release(release.tag_name, current_version):
        return release
    return None

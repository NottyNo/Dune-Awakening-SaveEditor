from __future__ import annotations

import json

from dune_save_editor import app as app_module
from dune_save_editor.update_check import (
    RELEASES_PAGE_URL,
    ReleaseInfo,
    check_for_update,
    is_newer_release,
    newest_published_release,
    parse_release_version,
)


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.data = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.data


def test_version_parser_equates_package_and_release_tag_styles() -> None:
    assert parse_release_version("1.0.0a1") == parse_release_version("v1.0.0-alpha.1")


def test_release_comparison_orders_prereleases_and_final_versions() -> None:
    assert is_newer_release("v1.0.0-alpha.2", "1.0.0a1")
    assert is_newer_release("v1.0.0-beta.1", "1.0.0a1")
    assert is_newer_release("v1.0.0", "1.0.0a1")
    assert not is_newer_release("v1.0.0-alpha.1", "1.0.0a1")
    assert not is_newer_release("not-a-version", "1.0.0a1")


def test_release_selection_skips_drafts_and_incomplete_entries() -> None:
    release = newest_published_release(
        [
            {
                "draft": True,
                "published_at": "2026-10-24T10:00:00Z",
                "tag_name": "v9.0.0",
            },
            {"draft": False, "published_at": None, "tag_name": "v8.0.0"},
            {
                "draft": False,
                "published_at": "2026-10-23T10:00:00Z",
                "tag_name": "v1.1.0-alpha.1",
                "name": "Alpha v1.1",
                "prerelease": True,
            },
        ]
    )

    assert release is not None
    assert release.tag_name == "v1.1.0-alpha.1"
    assert release.name == "Alpha v1.1"
    assert release.prerelease


def test_check_for_update_uses_published_releases_without_network() -> None:
    payload = [
        {
            "draft": False,
            "published_at": "2026-10-24T10:00:00Z",
            "tag_name": "v1.0.0-beta.1",
            "name": "Beta v1.0",
            "prerelease": True,
        }
    ]

    def opener(_request: object, *, timeout: float) -> FakeResponse:
        assert timeout == 0.1
        return FakeResponse(payload)

    release = check_for_update("1.0.0a1", timeout=0.1, opener=opener)

    assert release is not None
    assert release.tag_name == "v1.0.0-beta.1"


def test_check_for_update_fails_silently() -> None:
    def opener(_request: object, *, timeout: float) -> FakeResponse:
        raise OSError("offline")

    assert check_for_update("1.0.0a1", opener=opener) is None


def test_accepting_update_prompt_opens_releases_page(monkeypatch) -> None:
    opened: list[tuple[str, int]] = []
    monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        app_module.webbrowser,
        "open",
        lambda url, new: opened.append((url, new)),
    )
    editor = object.__new__(app_module.SaveEditorApp)
    editor.root = object()

    editor._prompt_for_update(ReleaseInfo("v1.1.0", "Version 1.1", False))

    assert opened == [(RELEASES_PAGE_URL, 2)]


def test_declining_update_prompt_continues_without_opening_browser(monkeypatch) -> None:
    monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *_args, **_kwargs: False)
    opened: list[str] = []
    monkeypatch.setattr(app_module.webbrowser, "open", lambda url, new: opened.append(url))
    editor = object.__new__(app_module.SaveEditorApp)
    editor.root = object()

    editor._prompt_for_update(ReleaseInfo("v1.1.0", "Version 1.1", False))

    assert opened == []

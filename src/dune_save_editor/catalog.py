from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CatalogItem:
    template_id: str
    display_name: str
    description: str
    max_stack_size: int
    max_durability: float
    item_size: float
    tags: tuple[str, ...]
    enabled: bool
    deprecated: bool

    @property
    def category(self) -> str:
        for tag in self.tags:
            if tag.startswith("Items."):
                parts = tag.split(".")
                if len(parts) > 1:
                    return parts[1].replace("_", " ")
        return "Other"

    @property
    def search_text(self) -> str:
        return " ".join((self.template_id, self.display_name, *self.tags)).casefold()


def _localized_text(value: Any, fallback: str = "") -> str:
    if not isinstance(value, dict):
        return fallback
    return str(value.get("LocalizedString") or value.get("SourceString") or fallback)


def catalog_from_fmodel(source: Path) -> list[CatalogItem]:
    """Build a compact item catalog from an FModel CDT_BaseItems export."""
    with source.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if isinstance(payload, list) and len(payload) == 1:
        payload = payload[0]
    if not isinstance(payload, dict):
        raise ValueError("Expected one FModel data table object")
    rows = payload.get("Rows")
    if not isinstance(rows, dict):
        raise ValueError("Expected an FModel data table with a Rows object")

    items: list[CatalogItem] = []
    for template_id, raw_row in rows.items():
        row = raw_row if isinstance(raw_row, dict) else {}
        static = row.get("StaticData") if isinstance(row.get("StaticData"), dict) else {}
        stack = (
            row.get("StackAndDurability") if isinstance(row.get("StackAndDurability"), dict) else {}
        )
        tags = tuple(str(tag) for tag in static.get("ItemTags", []) if isinstance(tag, str))
        items.append(
            CatalogItem(
                template_id=str(template_id),
                display_name=_localized_text(static.get("Name"), str(template_id)),
                description=_localized_text(static.get("ShortDesc")),
                max_stack_size=max(1, int(stack.get("MaxStackSize") or 1)),
                max_durability=float(stack.get("MaxDurability") or 0.0),
                item_size=max(0.0, float(static.get("ItemSize") or 0.0)),
                tags=tags,
                enabled=bool(static.get("bIsEnabled", True)),
                deprecated=bool(row.get("bIsDeprecated", False)),
            )
        )
    return sorted(
        items, key=lambda item: (item.display_name.casefold(), item.template_id.casefold())
    )


def write_catalog(items: list[CatalogItem], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": 1,
        "items": [{**asdict(item), "tags": list(item.tags)} for item in items],
    }
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def default_catalog_path() -> Path:
    return Path(__file__).with_name("data") / "item_catalog.json"


def load_catalog(path: Path | None = None) -> list[CatalogItem]:
    source = path or default_catalog_path()
    with source.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("format_version") != 1 or not isinstance(payload.get("items"), list):
        raise ValueError(f"Unsupported item catalog format: {source}")
    return [
        CatalogItem(
            template_id=str(row["template_id"]),
            display_name=str(row["display_name"]),
            description=str(row.get("description", "")),
            max_stack_size=max(1, int(row.get("max_stack_size", 1))),
            max_durability=float(row.get("max_durability", 0.0)),
            item_size=max(0.0, float(row.get("item_size", 0.0))),
            tags=tuple(str(tag) for tag in row.get("tags", [])),
            enabled=bool(row.get("enabled", True)),
            deprecated=bool(row.get("deprecated", False)),
        )
        for row in payload["items"]
    ]


def default_item_stats(item: CatalogItem) -> str:
    durability: dict[str, float] = {}
    if item.max_durability > 0:
        durability = {
            "DecayedMaxDurability": item.max_durability,
            "CurrentDurability": item.max_durability,
        }
    return json.dumps(
        {"FItemStackAndDurabilityStats": [[], durability]},
        separators=(",", ":"),
    )

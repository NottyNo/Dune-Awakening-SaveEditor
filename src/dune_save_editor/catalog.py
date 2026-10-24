from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

LocalizationMap = dict[tuple[str, str], str]
NON_INVENTORY_CATEGORIES = frozenset({"abilities", "gadgets", "vehicle abilities"})


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
    category_name: str = ""
    quality_levels: tuple[int, ...] = ()
    source_name: str = ""
    status: str = "current"

    @property
    def category(self) -> str:
        if self.category_name:
            return self.category_name
        for tag in self.tags:
            if tag.startswith("Items."):
                parts = tag.split(".")
                if len(parts) > 1:
                    return parts[1].replace("_", " ")
        return "Other"

    @property
    def search_text(self) -> str:
        return " ".join(
            (self.template_id, self.display_name, self.source_name, self.category, *self.tags)
        ).casefold()


def is_inventory_catalog_item(item: CatalogItem) -> bool:
    """Exclude skill and vehicle abilities that cannot exist as inventory items."""

    return item.category.casefold() not in NON_INVENTORY_CATEGORIES and not any(
        tag.casefold().startswith("items.abilities") for tag in item.tags
    )


def _localized_text(
    value: Any,
    fallback: str = "",
    localizations: LocalizationMap | None = None,
) -> str:
    if not isinstance(value, dict):
        return fallback
    table_id = str(value.get("TableId") or "")
    key = str(value.get("Key") or "")
    if localizations is not None and table_id and key:
        table_name = table_id.rsplit("/", 1)[-1].split(".", 1)[0].casefold()
        localized = localizations.get((table_name, key))
        if localized is None:
            localized = localizations.get((table_name, key.strip()))
        if localized:
            return localized
    return str(value.get("LocalizedString") or value.get("SourceString") or fallback)


def _is_placeholder_name(value: str) -> bool:
    normalized = value.strip().upper()
    return normalized.startswith(("PH_", "XX_", "XX ", "[DEPRECATED]")) or (
        " " not in normalized
        and normalized.endswith(("_NAME", "_ITEMNAME", "_SHORTDESC", "_LONGDESC"))
    )


def _is_localization_token(value: str) -> bool:
    normalized = value.strip()
    return bool(
        " " not in normalized
        and "/" not in normalized
        and normalized.upper() == normalized
        and normalized.endswith(("_NAME", "_ITEMNAME", "_SHORTDESC", "_LONGDESC"))
    )


def _clean_source_name(value: str) -> str:
    """Remove development markers without inventing different item semantics."""
    cleaned = value.strip()
    prefixes = ("[DEPRECATED]", "XX_NOTUSED_", "PH_", "XX_", "NA_")
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if cleaned.upper().startswith(prefix):
                cleaned = cleaned[len(prefix) :].strip(" _-")
                changed = True
                break
    cleaned = re.sub(r"(?:[ _-]+(?:ITEM)?NAME)$", "", cleaned, flags=re.IGNORECASE).strip()
    return " ".join(cleaned.split())


def _uses_obsolete_vehicle_rank_name(template_id: str, source_name: str, status: str) -> bool:
    if status not in {"deprecated", "removed"}:
        return False
    combined = f"{template_id} {source_name}".casefold()
    if not any(vehicle in combined for vehicle in ("sandbike", "buggy", "ornithopter")):
        return False
    rank_name = re.match(
        r"^(?:scrap|journeyman|artisan|house|adept|regis)\b",
        source_name.strip(),
        flags=re.IGNORECASE,
    )
    numbered_high_tier = bool(re.search(r"\b(?:mk\s*)?[789]\b", source_name, re.IGNORECASE))
    return bool(rank_name or numbered_high_tier)


def _display_name(template_id: str, source_name: str, status: str) -> str:
    """Return a readable label while retaining provenance in source_name and status."""
    if _uses_obsolete_vehicle_rank_name(template_id, source_name, status):
        return _humanize_identifier(template_id.removeprefix("D_"))

    cleaned = _clean_source_name(source_name)
    if (
        not cleaned
        or cleaned.casefold() == template_id.casefold()
        or _is_localization_token(cleaned)
        or (cleaned.startswith("D_") and " " not in cleaned)
    ):
        return _humanize_identifier(template_id.removeprefix("D_"))
    return cleaned


def _load_localizations(items_directory: Path) -> LocalizationMap:
    localization_dir = items_directory.parent.parent / "Localization"
    localizations: LocalizationMap = {}
    if not localization_dir.is_dir():
        return localizations

    for source in sorted(localization_dir.glob("ST_Localization_*.json")):
        try:
            payload = _load_fmodel_object(source)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        string_table = payload.get("StringTable")
        entries = string_table.get("KeysToEntries") if isinstance(string_table, dict) else None
        if not isinstance(entries, dict):
            continue
        table_name = source.stem.casefold()
        for key, value in entries.items():
            if isinstance(key, str) and isinstance(value, str) and value:
                localizations[(table_name, key)] = value
                localizations.setdefault((table_name, key.strip()), value)
    return localizations


def _load_fmodel_object(source: Path) -> dict[str, Any]:
    with source.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if isinstance(payload, list) and len(payload) == 1:
        payload = payload[0]
    if not isinstance(payload, dict):
        raise ValueError(f"Expected one FModel object in {source}")
    return payload


def _table_rows(payload: dict[str, Any]) -> dict[str, Any] | None:
    rows = payload.get("Rows")
    return rows if isinstance(rows, dict) else None


def _item_from_base_row(
    template_id: str,
    raw_row: Any,
    category_name: str = "",
    localizations: LocalizationMap | None = None,
) -> CatalogItem:
    row = raw_row if isinstance(raw_row, dict) else {}
    static = row.get("StaticData") if isinstance(row.get("StaticData"), dict) else {}
    stack = row.get("StackAndDurability")
    stack = stack if isinstance(stack, dict) else {}
    tags = tuple(str(tag) for tag in static.get("ItemTags", []) if isinstance(tag, str))
    source_name = _localized_text(static.get("Name"), str(template_id), localizations)
    deprecated = bool(row.get("bIsDeprecated", False))
    status = (
        "deprecated"
        if deprecated
        else "placeholder"
        if _is_placeholder_name(source_name)
        else "unlocalized"
        if source_name == str(template_id)
        else "current"
    )
    return CatalogItem(
        template_id=str(template_id),
        display_name=_display_name(str(template_id), source_name, status),
        description=_localized_text(static.get("ShortDesc"), localizations=localizations),
        max_stack_size=max(1, int(stack.get("MaxStackSize") or 1)),
        max_durability=float(stack.get("MaxDurability") or 0.0),
        item_size=max(0.0, float(static.get("ItemSize") or 0.0)),
        tags=tags,
        enabled=bool(static.get("bIsEnabled", True)),
        deprecated=deprecated,
        category_name=category_name,
        source_name=source_name,
        status=status,
    )


def _catalog_from_base_table(source: Path) -> list[CatalogItem]:
    payload = _load_fmodel_object(source)
    rows = _table_rows(payload)
    if rows is None:
        raise ValueError("Expected an FModel data table with a Rows object")
    return [_item_from_base_row(template_id, raw_row) for template_id, raw_row in rows.items()]


def _row_struct(payload: dict[str, Any]) -> str:
    properties = payload.get("Properties")
    if not isinstance(properties, dict):
        return ""
    row_struct = properties.get("RowStruct")
    if not isinstance(row_struct, dict):
        return ""
    return str(row_struct.get("ObjectName") or "")


def _is_item_row_struct(row_struct: str) -> bool:
    class_name = row_struct.removeprefix("Class'").removesuffix("'")
    return class_name == "BaseItemTableRow" or class_name.endswith("ItemTableRow")


def _humanize_identifier(value: str) -> str:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value.replace("_", " "))
    return " ".join(value.split())


def _category_from_table(source: Path) -> str:
    stem = source.stem
    for prefix in (
        "DT_BaseItems_",
        "DT_ItemTable_",
        "DT_ItemTable",
        "DT_Items_Wearables_",
        "DT_Items_",
        "DT_",
        "CDT_",
    ):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
            break
    substitutions = {
        "ArmorItemTable": "Armor",
        "BuildingBlueprintItemTable": "Building Blueprints",
        "ClothingHydrationItemTable": "Clothing",
        "ContractItems": "Contracts",
        "ContractRewardItems": "Contract Rewards",
        "FuelContainerItemTable": "Fuel Containers",
        "MeleeWeaponItemTable": "Weapons",
        "ReferenceItemTable": "Reference Items",
    }
    return substitutions.get(stem, _humanize_identifier(stem)) or "Other"


def _walk_template_ids(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in {"templateid", "template_id"}:
                if isinstance(child, dict):
                    name = child.get("Name")
                    if isinstance(name, str) and name and name != "None":
                        yield name
                elif isinstance(child, str) and child and child != "None":
                    yield child
            yield from _walk_template_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_template_ids(child)


def _curve_quality_levels(source: Path) -> set[int]:
    try:
        payload = _load_fmodel_object(source)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return set()
    properties = payload.get("Properties")
    if not isinstance(properties, dict):
        return set()
    curve = properties.get("FloatCurve")
    if not isinstance(curve, dict) or not isinstance(curve.get("Keys"), list):
        return set()
    levels: set[int] = set()
    for key in curve["Keys"]:
        if not isinstance(key, dict) or not isinstance(key.get("Time"), int | float):
            continue
        time = float(key["Time"])
        if 1 <= time <= 5 and time.is_integer():
            levels.add(int(time))
    return levels


def _quality_rules(source: Path) -> dict[str, tuple[int, ...]]:
    quality_dir = source / "Quality"
    rules_path = quality_dir / "DA_StatChangesPerQuality.json"
    try:
        payload = _load_fmodel_object(rules_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return {}
    properties = payload.get("Properties")
    entries = properties.get("StatChangesPerItemTag") if isinstance(properties, dict) else None
    if not isinstance(entries, list):
        return {}

    quality_rules: dict[str, set[int]] = {}
    curve_cache: dict[str, set[int]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = entry.get("Key")
        tag_dictionary = key.get("TagDictionary") if isinstance(key, dict) else None
        tags = {
            str(tag["TagName"])
            for tag in tag_dictionary or []
            if isinstance(tag, dict) and isinstance(tag.get("TagName"), str)
        }
        value = entry.get("Value")
        changes = value.get("StatChangePercentagePerQuality") if isinstance(value, dict) else None
        levels: set[int] = set()
        for change in changes or []:
            if not isinstance(change, dict):
                continue
            curve_ref = change.get("StatChangePercentagesPerQualityCurve")
            object_name = curve_ref.get("ObjectName") if isinstance(curve_ref, dict) else None
            if not isinstance(object_name, str):
                continue
            match = re.search(r"'([^']+)'", object_name)
            if not match:
                continue
            curve_name = match.group(1)
            if curve_name not in curve_cache:
                curve_cache[curve_name] = _curve_quality_levels(quality_dir / f"{curve_name}.json")
            levels.update(curve_cache[curve_name])
        for tag in tags:
            quality_rules.setdefault(tag, set()).update(levels)
    return {tag: tuple(sorted(levels)) for tag, levels in quality_rules.items() if levels}


def _quality_levels_for_tags(
    item_tags: tuple[str, ...],
    quality_rules: dict[str, tuple[int, ...]],
) -> tuple[int, ...]:
    levels: set[int] = set()
    for rule_tag, rule_levels in quality_rules.items():
        if any(tag == rule_tag or tag.startswith(f"{rule_tag}.") for tag in item_tags):
            levels.update(rule_levels)
    return tuple(sorted(levels))


def _directory_catalog(source: Path) -> list[CatalogItem]:
    base_path = source / "CDT_BaseItems.json"
    if not base_path.is_file():
        raise ValueError(f"No CDT_BaseItems.json found under {source}")

    base_payload = _load_fmodel_object(base_path)
    base_rows = _table_rows(base_payload)
    if base_rows is None:
        raise ValueError("Expected CDT_BaseItems.json to contain a Rows object")

    json_documents: list[tuple[Path, dict[str, Any]]] = []
    for json_path in sorted(source.rglob("*.json")):
        try:
            json_documents.append((json_path, _load_fmodel_object(json_path)))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue

    base_categories: dict[str, set[str]] = {}
    discovered: dict[str, tuple[str, set[str]]] = {}
    removed_ids: dict[str, str] = {}
    quality_rules = _quality_rules(source)
    localizations = _load_localizations(source)

    def discover(template_id: str, category: str) -> None:
        template_id = template_id.strip()
        if not template_id or template_id == "None":
            return
        key = template_id.casefold()
        if key not in discovered:
            discovered[key] = (template_id, set())
        if category:
            discovered[key][1].add(category)

    for json_path, payload in json_documents:
        rows = _table_rows(payload)
        row_struct = _row_struct(payload)
        category = _category_from_table(json_path)
        if (
            rows is not None
            and row_struct == "Class'BaseItemTableRow'"
            and json_path.parent.name == "BaseItems"
        ):
            for template_id in rows:
                base_categories.setdefault(template_id.casefold(), set()).add(category)
        if rows is not None and _is_item_row_struct(row_struct):
            for template_id in rows:
                discover(str(template_id), category)
        for template_id in _walk_template_ids(payload):
            discover(template_id, "Referenced Items")

        if json_path.name == "DA_ItemsAndRecipesToRemove.json":
            properties = payload.get("Properties")
            if isinstance(properties, dict):
                removed = properties.get("m_ItemsToRemove")
                if isinstance(removed, list):
                    for template_id in removed:
                        if isinstance(template_id, str) and template_id:
                            removed_ids[template_id.casefold()] = template_id
                            discover(template_id, "Removed Items")

    base_items: dict[str, CatalogItem] = {}
    for template_id, raw_row in base_rows.items():
        key = str(template_id).casefold()
        categories = sorted(base_categories.get(key, ()), key=str.casefold)
        category = categories[0] if categories else ""
        item = _item_from_base_row(str(template_id), raw_row, category, localizations)
        base_items[key] = replace(
            item,
            quality_levels=(
                _quality_levels_for_tags(item.tags, quality_rules)
                if item.status in {"current", "unlocalized"}
                else ()
            ),
        )

    merged = dict(base_items)
    for key, (template_id, categories) in discovered.items():
        if key in merged:
            item = merged[key]
            if key in removed_ids:
                merged[key] = replace(
                    item,
                    deprecated=True,
                    quality_levels=(),
                    status="removed",
                    display_name=_display_name(item.template_id, item.source_name, "removed"),
                )
            continue

        paired = base_items.get(f"d_{key}")
        category = paired.category if paired else sorted(categories, key=str.casefold)[0]
        if paired:
            status = "removed" if key in removed_ids else paired.status
            item = replace(
                paired,
                template_id=template_id,
                display_name=_display_name(template_id, paired.source_name, status),
                deprecated=paired.deprecated or status == "removed",
                category_name=category,
                quality_levels=(
                    paired.quality_levels if status in {"current", "unlocalized"} else ()
                ),
                status=status,
            )
        else:
            status = "removed" if key in removed_ids else "unlocalized"
            item = CatalogItem(
                template_id=template_id,
                display_name=_humanize_identifier(template_id.removeprefix("D_")),
                description="",
                max_stack_size=1,
                max_durability=0.0,
                item_size=0.0,
                tags=(),
                enabled=key not in removed_ids,
                deprecated=key in removed_ids,
                category_name=category,
                source_name=template_id,
                status=status,
            )
        merged[key] = item

    return sorted(
        merged.values(),
        key=lambda item: (item.category.casefold(), item.display_name.casefold(), item.template_id),
    )


def catalog_from_fmodel(source: Path) -> list[CatalogItem]:
    """Build a deduplicated catalog from an Items export directory or base table."""
    if source.is_dir():
        return [item for item in _directory_catalog(source) if is_inventory_catalog_item(item)]
    items = sorted(
        _catalog_from_base_table(source),
        key=lambda item: (item.display_name.casefold(), item.template_id.casefold()),
    )
    return [item for item in items if is_inventory_catalog_item(item)]


def write_catalog(items: list[CatalogItem], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": 4,
        "items": [
            {
                **asdict(item),
                "tags": list(item.tags),
                "quality_levels": list(item.quality_levels),
            }
            for item in items
            if is_inventory_catalog_item(item)
        ],
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
    if payload.get("format_version") not in {1, 2, 3, 4} or not isinstance(
        payload.get("items"), list
    ):
        raise ValueError(f"Unsupported item catalog format: {source}")
    items = [
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
            category_name=str(row.get("category_name", "")),
            quality_levels=tuple(int(level) for level in row.get("quality_levels", [])),
            source_name=str(row.get("source_name", row["display_name"])),
            status=str(
                row.get(
                    "status",
                    "deprecated" if bool(row.get("deprecated", False)) else "current",
                )
            ),
        )
        for row in payload["items"]
    ]
    return [item for item in items if is_inventory_catalog_item(item)]


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

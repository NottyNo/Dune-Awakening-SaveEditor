from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
import struct
import tempfile
import time
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dune_save_editor.stats import CHARACTER_STATS, SPECIALIZATION_TRACKS

SQLITE_HEADER = b"SQLite format 3\x00"
WRAPPER_TAG = 1
MAX_PACKED_SIZE = 256 * 1024 * 1024
MAX_DATABASE_SIZE = 1024 * 1024 * 1024


class SaveError(RuntimeError):
    """Base exception for save loading and editing failures."""


class SaveFormatError(SaveError):
    """The selected file is not a supported Dune save."""


class SaveChangedError(SaveError):
    """The source file changed after it was loaded."""


class InventoryError(SaveError):
    """An inventory edit violates a validated constraint."""


class StatError(SaveError):
    """A character-stat edit is unavailable or invalid."""


@dataclass(frozen=True, slots=True)
class Player:
    row_id: int
    character_name: str


@dataclass(frozen=True, slots=True)
class Inventory:
    inventory_id: int
    inventory_type: int
    max_item_count: int | None
    max_item_volume: float | None
    owner_kind: str
    owner_id: int | None = None


@dataclass(frozen=True, slots=True)
class InventoryItem:
    item_id: int
    position_index: int
    template_id: str
    stack_size: int
    quality_level: int
    stats: str

    def _durability_value(self, key: str) -> float | None:
        try:
            payload = json.loads(self.stats)
            values = payload.get("FItemStackAndDurabilityStats", [])
            details = values[1] if isinstance(values, list) and len(values) > 1 else {}
            value = details.get(key) if isinstance(details, dict) else None
            return float(value) if value is not None else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    @property
    def durability(self) -> float | None:
        return self._durability_value("CurrentDurability")

    @property
    def stored_max_durability(self) -> float | None:
        return self._durability_value("DecayedMaxDurability")


@dataclass(frozen=True, slots=True)
class Specialization:
    track_type: int
    name: str
    xp_amount: int
    level: float


@dataclass(frozen=True, slots=True)
class FactionReputation:
    faction_id: int
    name: str
    reputation_amount: int


def unpack_save(packed: bytes) -> tuple[int, bytes]:
    if not 8 < len(packed) <= MAX_PACKED_SIZE:
        raise SaveFormatError("File size is outside the supported range")
    tag, expected_size = struct.unpack("<II", packed[:8])
    if tag != WRAPPER_TAG:
        raise SaveFormatError(f"Unsupported save wrapper tag: {tag}")
    if not 0 < expected_size <= MAX_DATABASE_SIZE:
        raise SaveFormatError("Declared database size is outside the supported range")

    stream = zlib.decompressobj()
    raw = stream.decompress(packed[8:], expected_size + 1)
    raw += stream.flush()
    if len(raw) != expected_size:
        raise SaveFormatError("Decompressed size does not match the save header")
    if not stream.eof or stream.unused_data or stream.unconsumed_tail:
        raise SaveFormatError("The save contains an incomplete or trailing zlib stream")
    if not raw.startswith(SQLITE_HEADER):
        raise SaveFormatError("The decompressed payload is not a SQLite database")
    return tag, raw


def pack_save(raw: bytes, tag: int = WRAPPER_TAG) -> bytes:
    if not raw.startswith(SQLITE_HEADER):
        raise SaveFormatError("Refusing to pack a non-SQLite payload")
    return struct.pack("<II", tag, len(raw)) + zlib.compress(raw, level=9)


class DuneSave:
    def __init__(
        self,
        path: Path,
        connection: sqlite3.Connection,
        tag: int,
        source_digest: bytes,
    ) -> None:
        self.path = path
        self._db = connection
        self._tag = tag
        self._source_digest = source_digest
        self.dirty = False

    @classmethod
    def open(cls, path: Path | str) -> DuneSave:
        source = Path(path).resolve()
        packed = source.read_bytes()
        tag, raw = unpack_save(packed)
        db = sqlite3.connect(":memory:")
        try:
            db.deserialize(raw)
            db.execute("PRAGMA foreign_keys=ON")
            cls._validate_database(db)
        except Exception:
            db.close()
            raise
        return cls(source, db, tag, hashlib.sha256(packed).digest())

    @staticmethod
    def _validate_database(db: sqlite3.Connection) -> None:
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise SaveFormatError("SQLite quick_check failed")
        required = {
            "actors": {"id", "properties", "gas_attributes"},
            "items": {"id", "inventory_id", "stack_size", "position_index", "template_id", "stats"},
            "inventories": {"id", "actor_id", "inventory_type", "max_item_count"},
            "items_id_sequencer": {"next_id"},
            "player_state": {"id", "character_name", "player_controller_id", "player_pawn_id"},
            "specialization_tracks": {"player_id", "track_type", "xp_amount", "level"},
            "player_faction_reputation": {"actor_id", "faction_id", "reputation_amount"},
            "factions": {"id", "name"},
        }
        for table, columns in required.items():
            present = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
            if not columns <= present:
                missing = ", ".join(sorted(columns - present))
                raise SaveFormatError(f"Unsupported schema: {table} is missing {missing}")

    def close(self) -> None:
        self._db.close()

    def players(self) -> list[Player]:
        rows = self._db.execute(
            "SELECT id, character_name FROM player_state ORDER BY last_login_time DESC, id"
        ).fetchall()
        return [Player(int(row[0]), str(row[1])) for row in rows]

    def _player_actor_ids(self, player_row_id: int) -> dict[str, int]:
        row = self._db.execute(
            "SELECT player_pawn_id, player_controller_id FROM player_state WHERE id = ?",
            (player_row_id,),
        ).fetchone()
        if not row or row[0] is None or row[1] is None:
            raise StatError("The selected player does not have both persisted actors")
        return {"pawn": int(row[0]), "controller": int(row[1])}

    def _actor_documents(self, actor_id: int) -> dict[str, dict[str, Any]]:
        row = self._db.execute(
            "SELECT json(properties), json(gas_attributes) FROM actors WHERE id = ?",
            (actor_id,),
        ).fetchone()
        if not row:
            raise StatError(f"Player actor {actor_id} is missing")
        documents: dict[str, dict[str, Any]] = {}
        for name, raw in zip(("properties", "gas_attributes"), row, strict=True):
            try:
                parsed = json.loads(raw) if raw else {}
            except (TypeError, json.JSONDecodeError) as exc:
                raise StatError(f"Actor {actor_id} has invalid {name} JSON") from exc
            if not isinstance(parsed, dict):
                raise StatError(f"Actor {actor_id} has unsupported {name} data")
            documents[name] = parsed
        return documents

    @staticmethod
    def _path_value(document: dict[str, Any], path: tuple[str, ...]) -> Any:
        current: Any = document
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current

    @staticmethod
    def _set_path(document: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
        current: Any = document
        for key in path[:-1]:
            if not isinstance(current, dict) or key not in current:
                raise StatError(f"This save does not contain {' / '.join(path)}")
            current = current[key]
        if not isinstance(current, dict) or path[-1] not in current:
            raise StatError(f"This save does not contain {' / '.join(path)}")
        current[path[-1]] = value

    def character_stats(self, player_row_id: int) -> dict[str, int | float | bool | None]:
        actor_ids = self._player_actor_ids(player_row_id)
        actors = {role: self._actor_documents(actor_id) for role, actor_id in actor_ids.items()}
        return {
            definition.key: self._path_value(
                actors[definition.actor][definition.document], definition.path
            )
            for definition in CHARACTER_STATS
        }

    @staticmethod
    def _validated_stat_value(definition: Any, value: Any) -> int | float | bool:
        if definition.kind == "boolean":
            if not isinstance(value, bool):
                raise StatError(f"{definition.label} must be true or false")
            return value
        if isinstance(value, bool):
            raise StatError(f"{definition.label} must be numeric")
        try:
            converted = int(value) if definition.kind == "integer" else float(value)
        except (TypeError, ValueError) as exc:
            raise StatError(f"{definition.label} must be numeric") from exc
        if definition.kind == "integer" and float(value) != converted:
            raise StatError(f"{definition.label} must be a whole number")
        if not math.isfinite(float(converted)):
            raise StatError(f"{definition.label} must be a finite number")
        if definition.minimum is not None and converted < definition.minimum:
            raise StatError(f"{definition.label} cannot be below {definition.minimum:g}")
        if definition.maximum is not None and converted > definition.maximum:
            raise StatError(f"{definition.label} cannot exceed {definition.maximum:g}")
        return converted

    def update_character_stats(self, player_row_id: int, updates: dict[str, Any]) -> None:
        definitions = {definition.key: definition for definition in CHARACTER_STATS}
        unknown = updates.keys() - definitions.keys()
        if unknown:
            raise StatError(f"Unknown character stat: {sorted(unknown)[0]}")
        actor_ids = self._player_actor_ids(player_row_id)
        actors = {role: self._actor_documents(actor_id) for role, actor_id in actor_ids.items()}
        for key, raw_value in updates.items():
            definition = definitions[key]
            value = self._validated_stat_value(definition, raw_value)
            document = actors[definition.actor][definition.document]
            self._set_path(document, definition.path, value)
            for path in definition.mirrored_paths:
                self._set_path(document, path, value)
        with self._db:
            for role, documents in actors.items():
                self._db.execute(
                    """
                    UPDATE actors
                    SET properties = jsonb(?), gas_attributes = jsonb(?)
                    WHERE id = ?
                    """,
                    (
                        json.dumps(documents["properties"], separators=(",", ":")),
                        json.dumps(documents["gas_attributes"], separators=(",", ":")),
                        actor_ids[role],
                    ),
                )
        self.dirty = True

    def specializations(self, player_row_id: int) -> list[Specialization]:
        pawn_id = self._player_actor_ids(player_row_id)["pawn"]
        rows = {
            int(row[0]): (int(row[1]), float(row[2]))
            for row in self._db.execute(
                """
                SELECT track_type, xp_amount, level
                FROM specialization_tracks WHERE player_id = ?
                """,
                (pawn_id,),
            )
        }
        return [
            Specialization(track_type, name, *rows.get(track_type, (0, 0.0)))
            for track_type, name in SPECIALIZATION_TRACKS
        ]

    def update_specializations(
        self, player_row_id: int, updates: dict[int, tuple[int, float]]
    ) -> None:
        valid_tracks = {track_type for track_type, _name in SPECIALIZATION_TRACKS}
        if not updates.keys() <= valid_tracks:
            raise StatError("Unknown specialization track")
        pawn_id = self._player_actor_ids(player_row_id)["pawn"]
        values: list[tuple[int, int, int, float]] = []
        for track_type, (xp_amount, level) in updates.items():
            if isinstance(xp_amount, bool) or isinstance(level, bool):
                raise StatError("Specialization XP and level must be numeric")
            if int(xp_amount) != xp_amount or not math.isfinite(float(level)):
                raise StatError("Specialization XP must be whole and level must be finite")
            if xp_amount < 0 or xp_amount > 2_147_483_647:
                raise StatError("Specialization XP must be between 0 and 2,147,483,647")
            if level < 0 or level > 1_000:
                raise StatError("Specialization level must be between 0 and 1,000")
            values.append((pawn_id, track_type, int(xp_amount), float(level)))
        with self._db:
            self._db.executemany(
                """
                INSERT INTO specialization_tracks (player_id, track_type, xp_amount, level)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id, track_type) DO UPDATE SET
                    xp_amount = excluded.xp_amount,
                    level = excluded.level
                """,
                values,
            )
        self.dirty = True

    def faction_reputations(self, player_row_id: int) -> list[FactionReputation]:
        pawn_id = self._player_actor_ids(player_row_id)["pawn"]
        rows = self._db.execute(
            """
            SELECT f.id, f.name, coalesce(r.reputation_amount, 0)
            FROM factions AS f
            LEFT JOIN player_faction_reputation AS r
              ON r.faction_id = f.id AND r.actor_id = ?
            WHERE lower(f.name) <> 'none'
            ORDER BY f.id
            """,
            (pawn_id,),
        ).fetchall()
        return [FactionReputation(int(row[0]), str(row[1]), int(row[2])) for row in rows]

    def update_faction_reputations(self, player_row_id: int, updates: dict[int, int]) -> None:
        pawn_id = self._player_actor_ids(player_row_id)["pawn"]
        known_ids = {
            int(row[0])
            for row in self._db.execute("SELECT id FROM factions WHERE lower(name) <> 'none'")
        }
        if not updates.keys() <= known_ids:
            raise StatError("Unknown faction")
        values: list[tuple[int, int, int]] = []
        for faction_id, amount in updates.items():
            if (
                isinstance(amount, bool)
                or int(amount) != amount
                or amount < -2_147_483_648
                or amount > 2_147_483_647
            ):
                raise StatError("Faction reputation is outside the supported integer range")
            values.append((pawn_id, faction_id, int(amount)))
        with self._db:
            self._db.executemany(
                """
                INSERT INTO player_faction_reputation (actor_id, faction_id, reputation_amount)
                VALUES (?, ?, ?)
                ON CONFLICT(actor_id, faction_id) DO UPDATE SET
                    reputation_amount = excluded.reputation_amount
                """,
                values,
            )
        self.dirty = True

    def carried_inventories(self, player_row_id: int) -> list[Inventory]:
        rows = self._db.execute(
            """
            SELECT inv.id, inv.inventory_type, inv.max_item_count, inv.max_item_volume,
                   CASE WHEN inv.actor_id = ps.player_pawn_id
                        THEN 'Character' ELSE 'Controller' END,
                   inv.actor_id
            FROM player_state AS ps
            JOIN inventories AS inv
              ON inv.actor_id IN (ps.player_pawn_id, ps.player_controller_id)
            WHERE ps.id = ? AND inv.inventory_type = 0
            ORDER BY CASE WHEN inv.actor_id = ps.player_pawn_id THEN 0 ELSE 1 END, inv.id
            """,
            (player_row_id,),
        ).fetchall()
        return [
            Inventory(
                inventory_id=int(row[0]),
                inventory_type=int(row[1]),
                max_item_count=None if row[2] is None else int(row[2]),
                max_item_volume=None if row[3] is None else float(row[3]),
                owner_kind=str(row[4]),
                owner_id=int(row[5]),
            )
            for row in rows
        ]

    def _table_has_columns(self, table: str, columns: set[str]) -> bool:
        exists = self._db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if not exists:
            return False
        present = {str(row[1]) for row in self._db.execute(f'PRAGMA table_info("{table}")')}
        return columns <= present

    @staticmethod
    def _vehicle_name(actor_class: str, actor_name: str) -> str:
        combined = f"{actor_class} {actor_name}".casefold()
        known_names = (
            (("ornithoptertransport", "carrierornithopter"), "Carrier Ornithopter"),
            (("ornithoptermedium",), "Assault Ornithopter"),
            (("ornithopterlight",), "Scout Ornithopter"),
            (("sandbike", "onemangroundcar"), "Sandbike"),
            (("buggy",), "Buggy"),
        )
        for markers, label in known_names:
            if any(marker in combined for marker in markers):
                return label
        source = actor_name.strip("#") or actor_class.rsplit("/", 1)[-1]
        source = source.removeprefix("BP_").removesuffix("_C")
        words: list[str] = []
        current = ""
        for character in source.replace("_", " "):
            if current and character.isupper() and current[-1].islower():
                words.append(current)
                current = character
            elif character == " ":
                if current:
                    words.append(current)
                    current = ""
            else:
                current += character
        if current:
            words.append(current)
        return " ".join(words) or "Vehicle"

    def vehicle_inventories(self, player_row_id: int) -> list[Inventory]:
        """Return usable storage inventories belonging to the selected player's vehicles."""
        required = {
            "vehicles": {"id"},
            "permission_actor_rank": {"permission_actor_id", "player_id"},
            "permission_actor": {"actor_id", "actor_name"},
            "actors": {"id", "class"},
        }
        if any(not self._table_has_columns(table, columns) for table, columns in required.items()):
            return []

        actor_ids = self._player_actor_ids(player_row_id)
        possible_player_ids = sorted({player_row_id, *actor_ids.values()})
        placeholders = ", ".join("?" for _ in possible_player_ids)
        rows = self._db.execute(
            f"""
            SELECT DISTINCT inv.id, inv.inventory_type, inv.max_item_count,
                   inv.max_item_volume, v.id, coalesce(a.class, ''),
                   coalesce(pa.actor_name, '')
            FROM permission_actor_rank AS rank
            JOIN vehicles AS v ON v.id = rank.permission_actor_id
            JOIN actors AS a ON a.id = v.id
            JOIN inventories AS inv ON inv.actor_id = v.id
            LEFT JOIN permission_actor AS pa ON pa.actor_id = v.id
            WHERE rank.player_id IN ({placeholders})
              AND inv.inventory_type = 0
              AND coalesce(inv.max_item_count, 0) > 0
            ORDER BY v.id, inv.id
            """,
            possible_player_ids,
        ).fetchall()
        inventories: list[Inventory] = []
        for row in rows:
            owner_kind = self._vehicle_name(str(row[5]), str(row[6]))
            if owner_kind == "Carrier Ornithopter":
                continue
            inventories.append(
                Inventory(
                    inventory_id=int(row[0]),
                    inventory_type=int(row[1]),
                    max_item_count=int(row[2]),
                    max_item_volume=None if row[3] is None else float(row[3]),
                    owner_kind=owner_kind,
                    owner_id=int(row[4]),
                )
            )
        return inventories

    def inventory_items(self, inventory_id: int) -> list[InventoryItem]:
        rows = self._db.execute(
            """
            SELECT id, position_index, template_id, stack_size, quality_level, stats
            FROM items WHERE inventory_id = ? ORDER BY position_index, id
            """,
            (inventory_id,),
        ).fetchall()
        return [
            InventoryItem(
                item_id=int(row[0]),
                position_index=int(row[1]),
                template_id=str(row[2]),
                stack_size=int(row[3]),
                quality_level=int(row[4]),
                stats=str(row[5]),
            )
            for row in rows
        ]

    def stats_for_template(self, template_id: str) -> str | None:
        row = self._db.execute(
            "SELECT stats FROM items WHERE template_id = ? ORDER BY id DESC LIMIT 1",
            (template_id,),
        ).fetchone()
        return str(row[0]) if row else None

    def _inventory_limits(self, inventory_id: int) -> tuple[int | None, int]:
        row = self._db.execute(
            "SELECT max_item_count, inventory_type FROM inventories WHERE id = ?",
            (inventory_id,),
        ).fetchone()
        if not row:
            raise InventoryError("Inventory no longer exists")
        if row[1] != 0:
            raise InventoryError("Only item-storage inventories (type 0) can be edited")
        return (None if row[0] is None else int(row[0]), int(row[1]))

    def add_item(
        self,
        inventory_id: int,
        template_id: str,
        stack_size: int,
        stats: str,
        quality_level: int = 0,
    ) -> int:
        if not template_id.strip():
            raise InventoryError("Template ID is required")
        if stack_size <= 0:
            raise InventoryError("Stack size must be positive")
        if quality_level < 0:
            raise InventoryError("Quality level cannot be negative")
        try:
            json.loads(stats)
        except json.JSONDecodeError as exc:
            raise InventoryError("Item stats must be valid JSON") from exc

        max_count, _ = self._inventory_limits(inventory_id)
        occupied = {
            int(row[0])
            for row in self._db.execute(
                "SELECT position_index FROM items WHERE inventory_id = ?",
                (inventory_id,),
            )
        }
        if max_count is not None and max_count >= 0:
            position = next((slot for slot in range(max_count) if slot not in occupied), None)
            if position is None:
                raise InventoryError("The selected inventory has no free slot")
        else:
            position = max(occupied, default=-1) + 1

        row = self._db.execute("SELECT next_id FROM items_id_sequencer LIMIT 1").fetchone()
        if not row:
            raise SaveFormatError("items_id_sequencer is empty")
        max_item_id = int(self._db.execute("SELECT coalesce(max(id), 0) FROM items").fetchone()[0])
        item_id = max(int(row[0]), max_item_id + 1)
        with self._db:
            self._db.execute("UPDATE items_id_sequencer SET next_id = ?", (item_id + 1,))
            self._db.execute(
                """
                INSERT INTO items (
                    id, inventory_id, stack_size, position_index, template_id,
                    is_new, acquisition_time, stats, quality_level, volume_override
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, NULL)
                """,
                (
                    item_id,
                    inventory_id,
                    stack_size,
                    position,
                    template_id.strip(),
                    int(time.time()),
                    stats,
                    quality_level,
                ),
            )
        self.dirty = True
        return item_id

    def update_stack_size(self, item_id: int, stack_size: int) -> None:
        if stack_size <= 0:
            raise InventoryError("Stack size must be positive; use Remove for zero")
        with self._db:
            cursor = self._db.execute(
                "UPDATE items SET stack_size = ? WHERE id = ?",
                (stack_size, item_id),
            )
        if cursor.rowcount != 1:
            raise InventoryError("Item no longer exists")
        self.dirty = True

    def update_item_durability(
        self, item_id: int, current_durability: float, maximum_durability: float
    ) -> None:
        if isinstance(current_durability, bool) or isinstance(maximum_durability, bool):
            raise InventoryError("Durability must be numeric")
        current = float(current_durability)
        maximum = float(maximum_durability)
        if not math.isfinite(current) or not math.isfinite(maximum):
            raise InventoryError("Durability must be finite")
        if maximum <= 0:
            raise InventoryError("This item does not have editable durability")
        if current < 0 or current > maximum:
            raise InventoryError(f"Durability must be between 0 and {maximum:g}")

        row = self._db.execute("SELECT json(stats) FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise InventoryError("Item no longer exists")
        try:
            payload = json.loads(row[0])
        except (TypeError, json.JSONDecodeError) as exc:
            raise InventoryError("Item durability data is invalid") from exc
        values = payload.get("FItemStackAndDurabilityStats")
        if not isinstance(values, list) or len(values) < 2 or not isinstance(values[1], dict):
            raise InventoryError("This item does not store editable durability data")
        values[1]["CurrentDurability"] = current
        encoded = json.dumps(payload, separators=(",", ":"))
        with self._db:
            cursor = self._db.execute("UPDATE items SET stats = ? WHERE id = ?", (encoded, item_id))
        if cursor.rowcount != 1:
            raise InventoryError("Item no longer exists")
        self.dirty = True

    def remove_item(self, item_id: int) -> None:
        child = self._db.execute(
            "SELECT id FROM inventories WHERE item_id = ? LIMIT 1", (item_id,)
        ).fetchone()
        if child:
            count = int(
                self._db.execute(
                    "SELECT count(*) FROM items WHERE inventory_id = ?", (child[0],)
                ).fetchone()[0]
            )
            if count:
                raise InventoryError("Refusing to remove a container item that still has contents")
        with self._db:
            cursor = self._db.execute("DELETE FROM items WHERE id = ?", (item_id,))
        if cursor.rowcount != 1:
            raise InventoryError("Item no longer exists")
        self.dirty = True

    @staticmethod
    def _validate_packed(packed: bytes) -> None:
        _, raw = unpack_save(packed)
        db = sqlite3.connect(":memory:")
        try:
            db.deserialize(raw)
            DuneSave._validate_database(db)
        finally:
            db.close()

    def save(self, destination: Path | str | None = None) -> Path | None:
        target = Path(destination).resolve() if destination else self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target == self.path:
            current = self.path.read_bytes()
            if hashlib.sha256(current).digest() != self._source_digest:
                raise SaveChangedError(
                    "The save changed on disk after it was opened. "
                    "Reopen it instead of overwriting it."
                )

        if self._db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise SaveError("Refusing to save because SQLite quick_check failed")
        packed = pack_save(self._db.serialize(), self._tag)
        self._validate_packed(packed)

        backup: Path | None = None
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup_directory = target.parent / "Save Editor Backups"
            backup_directory.mkdir(parents=True, exist_ok=True)
            backup = backup_directory / f"{target.name}.backup-{stamp}"
            shutil.copy2(target, backup)

        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(packed)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

        self.path = target
        self._source_digest = hashlib.sha256(packed).digest()
        self.dirty = False
        return backup

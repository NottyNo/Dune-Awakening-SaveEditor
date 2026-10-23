import hashlib
import sqlite3

import pytest

from dune_save_editor.save_file import (
    DuneSave,
    SaveChangedError,
    SaveFormatError,
    pack_save,
    unpack_save,
)


def make_save(path):
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE player_state (
            id INTEGER PRIMARY KEY, character_name TEXT NOT NULL,
            player_controller_id INTEGER, player_pawn_id INTEGER,
            last_login_time INTEGER
        ) STRICT;
        CREATE TABLE actors (
            id INTEGER PRIMARY KEY, properties BLOB, gas_attributes BLOB
        ) STRICT;
        CREATE TABLE inventories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER,
            item_id INTEGER, vehicle_module_id INTEGER, inventory_type INTEGER,
            max_item_count INTEGER, max_item_volume REAL
        ) STRICT;
        CREATE TABLE items (
            id INTEGER UNIQUE NOT NULL PRIMARY KEY AUTOINCREMENT,
            inventory_id INTEGER REFERENCES inventories(id) ON DELETE CASCADE,
            stack_size INTEGER NOT NULL CHECK (stack_size > 0),
            position_index INTEGER NOT NULL CHECK (position_index >= 0),
            template_id TEXT NOT NULL, is_new INTEGER DEFAULT 0,
            acquisition_time INTEGER NOT NULL DEFAULT 0, stats TEXT NOT NULL,
            quality_level INTEGER NOT NULL DEFAULT 0, volume_override REAL
        ) STRICT;
        CREATE TABLE items_id_sequencer (next_id INTEGER NOT NULL DEFAULT 1) STRICT;
        CREATE TABLE specialization_tracks (
            player_id INTEGER NOT NULL, track_type INTEGER NOT NULL,
            xp_amount INTEGER NOT NULL, level REAL NOT NULL,
            PRIMARY KEY (player_id, track_type)
        ) STRICT;
        CREATE TABLE factions (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL
        ) STRICT;
        CREATE TABLE player_faction_reputation (
            actor_id INTEGER NOT NULL, faction_id INTEGER NOT NULL,
            reputation_amount INTEGER NOT NULL,
            PRIMARY KEY (actor_id, faction_id)
        ) STRICT;
        INSERT INTO player_state VALUES (1, 'Test Character', 10, 11, 1);
        INSERT INTO factions VALUES (1, 'Atreides'), (2, 'Harkonnen'), (3, 'None'),
            (4, 'Smuggler');
        INSERT INTO inventories (id, actor_id, inventory_type, max_item_count)
            VALUES (20, 11, 0, 3);
        INSERT INTO items_id_sequencer VALUES (1000);
        INSERT INTO items (
            id, inventory_id, stack_size, position_index, template_id, stats, quality_level
        ) VALUES (900, 20, 2, 0, 'ExistingItem',
            '{"FItemStackAndDurabilityStats":[[],{}]}', 0);
        """
    )
    pawn_properties = """{
        "BP_DunePlayerCharacter_C": {
            "m_EyesOfIbadValue": 0.5,
            "m_bEyesOfIbadVisible": false,
            "m_bHeatstroke": false
        },
        "DamageableActorComponent": {
            "m_CurrentMaxHealth": 100.0,
            "m_TotalMaxHealth": 100.0
        },
        "TechKnowledgePlayerComponent": {"m_TechKnowledgePoints": 3}
    }"""
    gas_attributes = """{
        "DuneHydrationAttributeSet": {
            "ClothingCapturedWater": {"BaseValue": 1.0, "CurrentValue": 1.0},
            "CurrentHydration": {"BaseValue": 50.0, "CurrentValue": 50.0},
            "DehydrationPenalty": {"BaseValue": 0.0, "CurrentValue": 0.0},
            "HeatExhaustion": {"BaseValue": 0.0, "CurrentValue": 0.0}
        },
        "DuneSpiceAddictionAttributeSet": {
            "CurrentSpice": {"BaseValue": 2.0, "CurrentValue": 2.0},
            "SpiceAddictionLevel": {"BaseValue": 0.0, "CurrentValue": 0.0},
            "SpiceExposure": {"BaseValue": 4.0, "CurrentValue": 4.0},
            "SpiceTolerance": {"BaseValue": 5.0, "CurrentValue": 5.0}
        }
    }"""
    controller_properties = '{"BP_JourneyComponent_C":{"CurrentSpiceExposureThresholdLevel":1}}'
    db.execute(
        "INSERT INTO actors VALUES (11, jsonb(?), jsonb(?))",
        (pawn_properties, gas_attributes),
    )
    db.execute(
        "INSERT INTO actors VALUES (10, jsonb(?), jsonb('{}'))",
        (controller_properties,),
    )
    path.write_bytes(pack_save(db.serialize()))
    db.close()


def test_unpack_rejects_invalid_wrapper():
    with pytest.raises(SaveFormatError):
        unpack_save(b"not a save")


def test_add_edit_remove_and_round_trip(tmp_path):
    source = tmp_path / "game.db"
    output = tmp_path / "edited.db"
    make_save(source)
    save = DuneSave.open(source)
    player = save.players()[0]
    inventory = save.carried_inventories(player.row_id)[0]

    new_id = save.add_item(
        inventory.inventory_id,
        "NewItem",
        3,
        '{"FItemStackAndDurabilityStats":[[],{}]}',
        quality_level=5,
    )
    save.update_stack_size(new_id, 2)
    save.remove_item(900)
    assert save.dirty
    assert save.save(output) is None
    save.close()

    reopened = DuneSave.open(output)
    rows = reopened.inventory_items(inventory.inventory_id)
    assert [(row.template_id, row.stack_size, row.position_index) for row in rows] == [
        ("NewItem", 2, 1)
    ]
    assert rows[0].quality_level == 5
    reopened.close()


def test_save_creates_backup_and_detects_external_change(tmp_path):
    source = tmp_path / "game.db"
    make_save(source)
    original_digest = hashlib.sha256(source.read_bytes()).digest()
    save = DuneSave.open(source)
    inventory = save.carried_inventories(save.players()[0].row_id)[0]
    save.update_stack_size(save.inventory_items(inventory.inventory_id)[0].item_id, 3)
    backup = save.save()

    assert backup is not None and backup.exists()
    assert hashlib.sha256(backup.read_bytes()).digest() == original_digest

    source.write_bytes(source.read_bytes() + b"changed")
    save.update_stack_size(save.inventory_items(inventory.inventory_id)[0].item_id, 4)
    with pytest.raises(SaveChangedError):
        save.save()
    save.close()


def test_edit_character_stats_and_round_trip(tmp_path):
    source = tmp_path / "game.db"
    output = tmp_path / "edited.db"
    make_save(source)
    save = DuneSave.open(source)

    values = save.character_stats(1)
    assert values["maximum_health"] == 100.0
    assert values["current_hydration"] == 50.0
    assert values["tech_knowledge_points"] == 3

    save.update_character_stats(
        1,
        {
            "maximum_health": 250.0,
            "current_hydration": 75.5,
            "tech_knowledge_points": 20,
            "eyes_of_ibad_visible": True,
        },
    )
    save.save(output)
    save.close()

    reopened = DuneSave.open(output)
    values = reopened.character_stats(1)
    assert values["maximum_health"] == 250.0
    assert values["current_hydration"] == 75.5
    assert values["tech_knowledge_points"] == 20
    assert values["eyes_of_ibad_visible"] is True
    reopened.close()


def test_upsert_specializations_and_faction_reputation(tmp_path):
    source = tmp_path / "game.db"
    make_save(source)
    save = DuneSave.open(source)

    assert [(row.name, row.level) for row in save.specializations(1)] == [
        ("Crafting", 0.0),
        ("Gathering", 0.0),
        ("Exploration", 0.0),
        ("Combat", 0.0),
        ("Sabotage", 0.0),
    ]
    save.update_specializations(1, {1: (12_345, 12.0), 4: (54_321, 25.5)})
    save.update_faction_reputations(1, {1: 5_000, 2: -25})

    tracks = {row.track_type: row for row in save.specializations(1)}
    factions = {row.faction_id: row for row in save.faction_reputations(1)}
    assert (tracks[1].xp_amount, tracks[1].level) == (12_345, 12.0)
    assert (tracks[4].xp_amount, tracks[4].level) == (54_321, 25.5)
    assert factions[1].reputation_amount == 5_000
    assert factions[2].reputation_amount == -25
    save.close()

import json

from dune_save_editor.catalog import (
    catalog_from_fmodel,
    default_item_stats,
    load_catalog,
    write_catalog,
)


def test_catalog_from_fmodel_extracts_item_fields(tmp_path):
    source = tmp_path / "CDT_BaseItems.json"
    source.write_text(
        json.dumps(
            {
                "Rows": {
                    "SpiceFiber": {
                        "StaticData": {
                            "Name": {"LocalizedString": "Spice Fiber"},
                            "ShortDesc": {"SourceString": "A useful material."},
                            "ItemTags": ["Items.Resource"],
                            "bIsEnabled": True,
                            "ItemSize": 2.5,
                        },
                        "StackAndDurability": {"MaxStackSize": 100, "MaxDurability": 0},
                        "bIsDeprecated": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    items = catalog_from_fmodel(source)

    assert len(items) == 1
    assert items[0].template_id == "SpiceFiber"
    assert items[0].display_name == "Spice Fiber"
    assert items[0].max_stack_size == 100
    assert items[0].item_size == 2.5
    assert items[0].category == "Resource"
    assert "FItemStackAndDurabilityStats" in default_item_stats(items[0])


def test_catalog_directory_merges_sources_and_deduplicates_ids(tmp_path):
    items_dir = tmp_path / "Items"
    base_dir = items_dir / "BaseItems"
    quality_dir = items_dir / "Quality"
    base_dir.mkdir(parents=True)
    quality_dir.mkdir()
    base_rows = {
        "D_LegacyBlade": {
            "StaticData": {
                "Name": {"LocalizedString": "Legacy Blade"},
                "ShortDesc": {"LocalizedString": "An older weapon."},
                "ItemTags": ["Items.Holsters.MeleeWeapons.ShortBlade"],
                "bIsEnabled": True,
            },
            "StackAndDurability": {"MaxStackSize": 1, "MaxDurability": 100},
            "bIsDeprecated": True,
        },
        "SpiceFiber": {
            "StaticData": {
                "Name": {"LocalizedString": "Spice Fiber"},
                "ItemTags": ["Items.Resources"],
            },
            "StackAndDurability": {"MaxStackSize": 100},
        },
    }
    base_table = {
        "Properties": {"RowStruct": {"ObjectName": "Class'BaseItemTableRow'"}},
        "Rows": base_rows,
    }
    (items_dir / "CDT_BaseItems.json").write_text(json.dumps(base_table), encoding="utf-8")
    (base_dir / "DT_BaseItems_Weapons.json").write_text(
        json.dumps({**base_table, "Rows": {"D_LegacyBlade": base_rows["D_LegacyBlade"]}}),
        encoding="utf-8",
    )
    (base_dir / "DT_BaseItems_Resources.json").write_text(
        json.dumps({**base_table, "Rows": {"SpiceFiber": base_rows["SpiceFiber"]}}),
        encoding="utf-8",
    )
    (items_dir / "DT_ItemTableWeapons.json").write_text(
        json.dumps(
            {
                "Properties": {"RowStruct": {"ObjectName": "Class'WeaponItemTableRow'"}},
                "Rows": {"LegacyBlade": {}, "SPICEFIBER": {}, "NewBlade": {}},
            }
        ),
        encoding="utf-8",
    )
    (items_dir / "CDT_InventoryItems.json").write_text(
        json.dumps(
            {
                "Rows": {
                    "Starter": {
                        "m_Items": [
                            {"TemplateId": {"Name": "LegacyBlade"}},
                            {"TemplateId": {"Name": "ReferencedOnly"}},
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (items_dir / "DA_ItemsAndRecipesToRemove.json").write_text(
        json.dumps({"Properties": {"m_ItemsToRemove": ["LegacyBlade"]}}),
        encoding="utf-8",
    )
    (quality_dir / "DA_StatChangesPerQuality.json").write_text(
        json.dumps(
            {
                "Properties": {
                    "StatChangesPerItemTag": [
                        {
                            "Key": {"TagDictionary": [{"TagName": "Items.Holsters.MeleeWeapons"}]},
                            "Value": {
                                "StatChangePercentagePerQuality": [
                                    {
                                        "StatChangePercentagesPerQualityCurve": {
                                            "ObjectName": "CurveFloat'CF_TestQuality'"
                                        }
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    (quality_dir / "CF_TestQuality.json").write_text(
        json.dumps(
            {
                "Properties": {
                    "FloatCurve": {"Keys": [{"Time": level, "Value": 1.0} for level in range(6)]}
                }
            }
        ),
        encoding="utf-8",
    )

    items = catalog_from_fmodel(items_dir)
    by_id = {item.template_id.casefold(): item for item in items}

    assert len(items) == len(by_id) == 5
    assert by_id["legacyblade"].display_name == "Legacy Blade"
    assert by_id["legacyblade"].source_name == "Legacy Blade"
    assert by_id["legacyblade"].category == "Weapons"
    assert by_id["legacyblade"].deprecated is True
    assert by_id["legacyblade"].status == "removed"
    assert by_id["legacyblade"].quality_levels == ()
    assert by_id["d_legacyblade"].display_name == "Legacy Blade"
    assert by_id["d_legacyblade"].status == "deprecated"
    assert by_id["spicefiber"].quality_levels == ()
    assert by_id["newblade"].display_name == "New Blade"
    assert by_id["newblade"].status == "unlocalized"
    assert by_id["referencedonly"].category == "Referenced Items"
    assert sum(item.template_id.casefold() == "spicefiber" for item in items) == 1


def test_catalog_cleans_placeholder_marker_but_keeps_source_name(tmp_path):
    source = tmp_path / "CDT_BaseItems.json"
    source.write_text(
        json.dumps(
            {
                "Rows": {
                    "SandbikeInventory_7": {
                        "StaticData": {
                            "Name": {"LocalizedString": "PH_Chromium Sandbike Inventory"},
                            "bIsEnabled": True,
                        },
                        "bIsDeprecated": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    item = catalog_from_fmodel(source)[0]

    assert item.display_name == "Chromium Sandbike Inventory"
    assert item.source_name == "PH_Chromium Sandbike Inventory"
    assert item.status == "placeholder"


def test_catalog_uses_exported_string_table_and_preserves_template_id(tmp_path):
    dune_dir = tmp_path / "Dune"
    items_dir = dune_dir / "Systems" / "Items"
    localization_dir = dune_dir / "Localization"
    items_dir.mkdir(parents=True)
    localization_dir.mkdir()
    (items_dir / "CDT_BaseItems.json").write_text(
        json.dumps(
            {
                "Rows": {
                    "WayOfTheMisr": {
                        "StaticData": {
                            "Name": {
                                "TableId": (
                                    "/Game/Dune/Localization/"
                                    "ST_Localization_Items.ST_Localization_Items"
                                ),
                                "Key": "ITEMS/WEAPON_WAY_OF_THE_MISR_NAME",
                                "LocalizedString": "Stale Name",
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (localization_dir / "ST_Localization_Items.json").write_text(
        json.dumps(
            [
                {
                    "StringTable": {
                        "KeysToEntries": {"ITEMS/WEAPON_WAY_OF_THE_MISR_NAME": "Way of the Misr"}
                    }
                }
            ]
        ),
        encoding="utf-8",
    )

    item = catalog_from_fmodel(items_dir)[0]

    assert item.template_id == "WayOfTheMisr"
    assert item.display_name == "Way of the Misr"
    assert item.source_name == "Way of the Misr"


def test_removed_vehicle_rank_name_falls_back_to_readable_identifier(tmp_path):
    items_dir = tmp_path / "Items"
    items_dir.mkdir()
    (items_dir / "CDT_BaseItems.json").write_text(
        json.dumps(
            {
                "Rows": {
                    "D_SandbikeInventory_5": {
                        "StaticData": {"Name": {"LocalizedString": "Adept Sandbike Inventory"}},
                        "bIsDeprecated": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (items_dir / "DT_ItemTableBuildables.json").write_text(
        json.dumps(
            {
                "Properties": {"RowStruct": {"ObjectName": "Class'BuildableItemTableRow'"}},
                "Rows": {"SandbikeInventory_5": {}},
            }
        ),
        encoding="utf-8",
    )
    (items_dir / "DA_ItemsAndRecipesToRemove.json").write_text(
        json.dumps({"Properties": {"m_ItemsToRemove": ["SandbikeInventory_5"]}}),
        encoding="utf-8",
    )

    by_id = {item.template_id: item for item in catalog_from_fmodel(items_dir)}

    assert by_id["D_SandbikeInventory_5"].display_name == "Sandbike Inventory 5"
    assert by_id["SandbikeInventory_5"].display_name == "Sandbike Inventory 5"
    assert by_id["SandbikeInventory_5"].template_id == "SandbikeInventory_5"


def test_catalog_version_two_round_trip_preserves_category(tmp_path):
    source = tmp_path / "CDT_BaseItems.json"
    source.write_text(
        json.dumps(
            {
                "Rows": {
                    "SpiceFiber": {
                        "StaticData": {
                            "Name": {"LocalizedString": "Spice Fiber"},
                            "ItemTags": ["Items.Resource"],
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    destination = tmp_path / "catalog.json"

    write_catalog(catalog_from_fmodel(source), destination)
    loaded = load_catalog(destination)

    assert loaded[0].category == "Resource"

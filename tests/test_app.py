from dune_save_editor.app import (
    ASSET_DIRECTORY,
    CatalogChoice,
    catalog_item_for_template,
    durability_summary,
    effective_max_durability,
    inventory_weight_summary,
    visible_catalog_columns,
    visible_inventory_columns,
)
from dune_save_editor.catalog import CatalogItem
from dune_save_editor.save_file import Inventory, InventoryItem


def test_brand_assets_are_bundled_in_supported_formats():
    logo = ASSET_DIRECTORY / "app_logo.png"
    icon_png = ASSET_DIRECTORY / "app_icon.png"
    icon_ico = ASSET_DIRECTORY / "app_icon.ico"

    assert logo.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert icon_png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert icon_ico.read_bytes().startswith(b"\x00\x00\x01\x00")


def test_catalog_choice_labels_grade_without_changing_template_id():
    item = CatalogItem(
        template_id="UniqueSda6",
        display_name="Way of the Misr",
        description="",
        max_stack_size=1,
        max_durability=100.0,
        item_size=1.0,
        tags=("Items.Holsters.RangedWeapons.Light.Pistol",),
        enabled=True,
        deprecated=False,
        category_name="Weapons",
        quality_levels=(1, 2, 3, 4, 5),
    )

    assert CatalogChoice(item).display_name == "Way of the Misr"
    assert CatalogChoice(item, 3).display_name == "Way of the Misr Grade 3"
    assert CatalogChoice(item, 3).item.template_id == "UniqueSda6"


def test_saved_template_ids_match_catalog_without_case_sensitivity():
    item = CatalogItem(
        template_id="DewReaper_Prototype",
        display_name="Dew Reaper Mk2",
        description="",
        max_stack_size=1,
        max_durability=100.0,
        item_size=2.0,
        tags=(),
        enabled=True,
        deprecated=False,
        category_name="Weapons",
    )
    catalog_by_id = {item.template_id.casefold(): item}

    matched = catalog_item_for_template(catalog_by_id, "DewReaper_prototype")

    assert matched is item
    assert matched.display_name == "Dew Reaper Mk2"


def test_inventory_weight_summary_shows_current_and_maximum_weight():
    item = CatalogItem(
        template_id="BauxiteOre",
        display_name="Bauxite Ore",
        description="",
        max_stack_size=500,
        max_durability=0.0,
        item_size=0.6,
        tags=(),
        enabled=True,
        deprecated=False,
        category_name="Resources",
    )
    inventory = Inventory(126, 0, 20, 1500.0, "Buggy", 184)
    records = [InventoryItem(1, slot, "BauxiteOre", 500, 0, "{}") for slot in range(5)]

    assert inventory_weight_summary(inventory, records, {item.template_id: item}) == (
        "Max inventory weight: 1,500  •  Estimated load: 1,500"
    )


def test_visible_catalog_columns_can_hide_category_and_keep_weight():
    selections = {
        "name": True,
        "template": True,
        "category": False,
        "grade": False,
        "stack": True,
        "weight": True,
    }

    assert visible_catalog_columns(selections) == ("name", "template", "stack", "weight")


def test_visible_inventory_columns_and_durability_summary():
    selections = {
        "slot": False,
        "name": True,
        "template": False,
        "category": True,
        "quantity": True,
        "quality": False,
        "durability": True,
        "weight": True,
        "total_weight": True,
    }
    record = InventoryItem(
        1,
        0,
        "TestBlade",
        1,
        0,
        '{"FItemStackAndDurabilityStats":[[],{'
        '"CurrentDurability":25.25,"DecayedMaxDurability":50.5}]}',
    )

    assert visible_inventory_columns(selections) == (
        "name",
        "category",
        "quantity",
        "durability",
        "weight",
        "total_weight",
    )
    assert effective_max_durability(record, None) == 50.5
    assert durability_summary(record, None) == "25.25/50.5"

import json

from dune_save_editor.catalog import catalog_from_fmodel, default_item_stats


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

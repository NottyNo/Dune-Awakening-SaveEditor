from dune_save_editor.app import CatalogChoice
from dune_save_editor.catalog import CatalogItem


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

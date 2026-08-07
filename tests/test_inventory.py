from pathlib import Path

from quasimorph_optimizer.inventory import load_inventory, save_inventory
from quasimorph_optimizer.models import Item


def test_inventory_round_trip_preserves_order_and_availability(tmp_path: Path) -> None:
    path = tmp_path / "inventory.csv"
    items = [
        Item("Second", "agga", 80, 20, False),
        Item("First", "eon", 110, 25, True),
    ]
    save_inventory(path, items)
    loaded = load_inventory(path)
    assert loaded == items
    assert [item.name for item in loaded] == ["Second", "First"]


def test_v04_bundled_inventory_shape() -> None:
    from importlib import resources

    from quasimorph_optimizer.inventory import load_inventory

    resource = resources.files("quasimorph_optimizer.data").joinpath("default_inventory.csv")
    with resources.as_file(resource) as path:
        items = load_inventory(path)
    assert len(items) == 38
    assert items[0].name == "Load of Gold Bars"
    assert items[25].name == "Spider Joint"
    assert items[25].essence == "agga"
    assert items[31].name == "Shard"
    assert items[31].enabled is False
    assert items[-1].name == "Eye of Wrath"

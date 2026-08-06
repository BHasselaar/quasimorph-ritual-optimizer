from quasimorph_optimizer.inventory import migrate_inventory
from quasimorph_optimizer.models import Item


def test_migrates_known_spider_joint_error_only() -> None:
    items = [
        Item("Spider Joint", "shavva", 80, 25),
        Item("Custom Spider Joint", "shavva", 81, 25),
    ]
    migrated, changed = migrate_inventory(items)
    assert changed is True
    assert migrated[0].essence == "agga"
    assert migrated[1].essence == "shavva"

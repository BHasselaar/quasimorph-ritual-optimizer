from pathlib import Path
from types import SimpleNamespace

from quasimorph_optimizer import sprite_investigator as si


class _Object:
    def __init__(self, tree=None):
        self.tree = tree or {}

    def generate_monobehaviour_node(self):
        return object()

    def read_typetree(self, nodes=None):
        return self.tree

    def read(self):
        raise AssertionError("image export is monkeypatched in this test")


def test_raw_unity_version_is_preserved():
    env = SimpleNamespace(
        files={
            "resources.assets": SimpleNamespace(
                unity_version="2022.3.62f1",
                version="2022.3f1",
            )
        }
    )
    assert si._environment_unity_version(env) == "2022.3.62f1"


def test_pact_descriptor_arrays_resolve_item_icon(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(si, "_safe_asset_image", lambda obj, destination: "")

    trees = {
        10: {
            "_ids": ["moon_weapon_parts", "moon_armor_plates"],
            "_descriptors": [
                {"m_FileID": 0, "m_PathID": 19},
                {"m_FileID": 0, "m_PathID": 20},
            ],
        },
        20: {"_icon": {"m_FileID": 0, "m_PathID": 30}},
    }
    by_path = {
        10: _Object(trees[10]),
        20: _Object(trees[20]),
        30: _Object(),
    }
    info = {
        10: {
            "type": "MonoBehaviour",
            "name": "pactcomponents_descriptors",
            "class": "MGSC.DescriptorsCollection [Assembly-CSharp]",
        },
        20: {
            "type": "MonoBehaviour",
            "name": "quasiplumbum descriptor",
            "class": "MGSC.ItemContentDescriptor [Assembly-CSharp]",
        },
        30: {"type": "Sprite", "name": "confirmed_quasiplumbum_inv", "class": ""},
    }

    report = si._resolve_descriptor_collection(
        asset_file=Path("resources.assets"),
        by_path=by_path,
        trees=trees,
        info=info,
        output_dir=tmp_path,
    )

    resolved = report["items"]["moon_armor_plates"]
    assert resolved["index"] == 1
    assert resolved["descriptor"]["path_id"] == 20
    assert {
        key: resolved["icon"][key]
        for key in ("file", "path_id", "type", "asset_name")
    } == {
        "file": "resources.assets",
        "path_id": 30,
        "type": "Sprite",
        "asset_name": "confirmed_quasiplumbum_inv",
    }


def test_collection_is_discovered_by_exact_target_id_without_metadata(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(si, "_safe_asset_image", lambda obj, destination: "")

    collection = {
        "_ids": ["moon_armor_plates"],
        "_descriptors": [{"m_FileID": 0, "m_PathID": 2}],
    }
    report = si._resolve_descriptor_collection(
        asset_file=Path("resources.assets"),
        by_path={
            1: _Object(collection),
            2: _Object({"_icon": {"m_FileID": 0, "m_PathID": 3}}),
            3: _Object(),
        },
        trees={1: collection},
        info={
            1: {
                "type": "MonoBehaviour",
                "name": "",
                "class": "",
            },
            2: {"type": "MonoBehaviour", "name": "", "class": ""},
            3: {"type": "Sprite", "name": "quasiplumbum_inv", "class": ""},
        },
        output_dir=tmp_path,
    )
    assert report["collections_found"][0]["contains_target"] is True
    assert report["items"]["moon_armor_plates"]["icon"]["asset_name"] == "quasiplumbum_inv"


def test_runtime_placeholder_is_used_when_descriptor_icon_is_null(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(si, "_safe_asset_image", lambda obj, destination: "")

    collection = {
        "_ids": ["moon_armor_plates"],
        "_descriptors": [{"m_FileID": 0, "m_PathID": 2}],
    }
    factory = {
        "_iconOneSlotPlaceholder": {"m_FileID": 0, "m_PathID": 5},
        "_iconTwoSlotPlaceholder": {"m_FileID": 0, "m_PathID": 6},
    }
    report = si._resolve_descriptor_collection(
        asset_file=Path("resources.assets"),
        by_path={
            1: _Object(collection),
            2: _Object({"_icon": {"m_FileID": 0, "m_PathID": 0}}),
            4: _Object(factory),
            5: _Object(),
            6: _Object(),
        },
        trees={1: collection, 4: factory},
        info={
            1: {
                "type": "MonoBehaviour",
                "name": "pactcomponents_descriptors",
                "class": "MGSC.DescriptorsCollection [Assembly-CSharp]",
            },
            2: {
                "type": "MonoBehaviour",
                "name": "view",
                "class": "MGSC.ItemContentDescriptor [Assembly-CSharp]",
            },
            4: {
                "type": "MonoBehaviour",
                "name": "item factory",
                "class": "MGSC.ItemFactory [Assembly-CSharp]",
            },
            5: {"type": "Sprite", "name": "one_slot_placeholder", "class": ""},
            6: {"type": "Sprite", "name": "two_slot_placeholder", "class": ""},
        },
        output_dir=tmp_path,
        item_records={
            "moon_armor_plates": {
                "InventoryWidthSize": "2",
                "ItemClass": "Parts",
                "_section": "pactcomponents",
                "_line_number": 123,
                "_raw_line": "moon_armor_plates\t...\t2",
            }
        },
    )

    resolved = report["items"]["moon_armor_plates"]
    assert resolved["icon_source"] == "ItemFactory.ResolveIcon placeholder"
    assert resolved["placeholder_decision"] == {
        "InventoryWidthSize": 2,
        "field": "_iconTwoSlotPlaceholder",
    }
    assert resolved["icon"]["asset_name"] == "two_slot_placeholder"


def test_global_runtime_placeholder_applies_after_all_assets_are_scanned():
    report = {
        "authoritative_descriptor_resolution": {
            "item_factory_fallbacks": {
                "placeholders": {
                    "_iconOneSlotPlaceholder": {
                        "reference": {"m_FileID": 0, "m_PathID": 781},
                        "icon": {
                            "file": "sharedassets0.assets",
                            "path_id": 781,
                            "type": "Sprite",
                            "asset_name": "item_placeholder_one_inv",
                            "image": "runtime_fallback_icons/iconOneSlotPlaceholder.png",
                        },
                        "image": "runtime_fallback_icons/iconOneSlotPlaceholder.png",
                    }
                }
            },
            "items": {
                "moon_armor_plates": {
                    "item_record": {
                        "InventoryWidthSize": "",
                        "_raw_line": "moon_armor_plates\t\t\t",
                    },
                    "descriptor_icon_reference": {"file_id": 0, "path_id": 0},
                    "icon_reference": {"file_id": 0, "path_id": 0},
                    "error": "ItemContentDescriptor._icon is null or was not decoded.",
                }
            },
        }
    }

    si._apply_runtime_icon_fallbacks(report)

    resolved = report["authoritative_descriptor_resolution"]["items"]["moon_armor_plates"]
    assert resolved["icon_source"] == "ItemFactory.ResolveIcon placeholder"
    assert resolved["placeholder_decision"] == {
        "InventoryWidthSize": 1,
        "field": "_iconOneSlotPlaceholder",
    }
    assert resolved["icon"]["asset_name"] == "item_placeholder_one_inv"
    assert "error" not in resolved


def test_config_items_records_keep_inventory_width():
    text = "\n".join([
        "#pactcomponents",
        "Id\tCategories\tInventoryWidthSize\tItemClass\tMaxStack",
        "moon_armor_plates\tRitualItem\t2\tParts\t5",
    ])

    records = si._parse_config_items_records(text)

    assert records["moon_armor_plates"]["_section"] == "pactcomponents"
    assert records["moon_armor_plates"]["InventoryWidthSize"] == "2"
    assert si._inventory_width_size(records["moon_armor_plates"]) == 2


def test_blank_inventory_width_uses_itemrecord_constructor_default():
    assert si._inventory_width_size({"InventoryWidthSize": ""}) == 1


def test_large_text_hits_are_truncated():
    value = "prefix moon_armor_plates " + "x" * 1000
    hit = si._exact_text_hits({"body": value}, "moon_armor_plates")[0]
    assert hit["value_length"] == len(value)
    assert len(hit["value"]) == 503


def test_managed_tree_is_forced_even_when_a_basic_tree_exists():
    class ManagedObject(_Object):
        def __init__(self):
            super().__init__({"_ids": ["moon_armor_plates"]})
            self.generated = False

        def generate_monobehaviour_node(self):
            self.generated = True
            return "managed-node"

        def read_typetree(self, nodes=None):
            assert nodes == "managed-node"
            return self.tree

    obj = ManagedObject()
    tree, error, method = si._safe_managed_tree(obj)
    assert error == ""
    assert method == "generated"
    assert obj.generated is True
    assert tree["_ids"] == ["moon_armor_plates"]


def test_manual_nodes_match_dll_field_layout():
    from UnityPy.helpers.UnityVersion import UnityVersion

    obj = SimpleNamespace(version=UnityVersion.from_list(2022, 3, 62, 1))
    collection = si._manual_managed_node(obj, "DescriptorsCollection")
    descriptor = si._manual_managed_node(obj, "ItemContentDescriptor")
    factory = si._manual_managed_node(obj, "ItemFactory")

    assert [node.m_Name for node in collection.m_Children[-2:]] == [
        "_descriptors", "_ids"
    ]
    assert [node.m_Name for node in descriptor.m_Children[-4:]] == [
        "_overridenRenderId", "_icon", "_smallIcon", "_shadow"
    ]
    assert [node.m_Name for node in factory.m_Children[-4:]] == [
        "_iconOneSlotPlaceholder",
        "_iconTwoSlotPlaceholder",
        "_smallIconPlaceholder",
        "_shadowPlaceholder",
    ]

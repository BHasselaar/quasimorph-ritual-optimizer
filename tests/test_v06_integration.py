from __future__ import annotations

import json
from pathlib import Path

from quasimorph_optimizer.game_data import parse_resources_assets
from quasimorph_optimizer.models import Item
from quasimorph_optimizer.optimizer import optimize_parallel, quantity_ring_order_count
from quasimorph_optimizer.save_sync import read_save


def test_quantity_ring_count_repeated_single_type():
    items=[Item("Gold","eon",110,25,True,"precious_metals",5)]
    assert quantity_ring_order_count(items)==1


def test_quantity_search_can_use_same_component_five_times():
    items=[Item("Gold","eon",110,25,True,"precious_metals",5)]
    result=optimize_parallel(items,center_essence="gavvakh",tier=1,objective="jackpot",top_n=5,workers=1,
                             flat_power_bonus=100).results[0]
    assert len(result.order)==5
    assert all(x.internal_id=="precious_metals" for x in result.order)
    assert round(result.probabilities.jackpot*100)==13


def test_parse_embedded_config_tables(tmp_path: Path):
    raw=(b"BINARY\x00#pactcomponents\t\t\n"
         b"Id\t\tCategories\tEssence\tEssencePower\tEssenceStability\t\n"
         b"spider_joint\t\t\tagga\t80\t25\t\n#end\x00"
         b"#pacttiers\nTier\tEssencePower\tEssenceStability\tSidegradeCoef\n1\t650\t100\t3.5\n#end\x00"
         b"#essenceaffinity\nId\tSourceEssenceId\tTargetEssenceId\tPowerMult\tStabilityMult\n"
         b"agga_agga\tagga\tagga\t1\t1\n#end\x00SkullRitualUpgradeChanceCap\t0.7\t")
    p=tmp_path/"resources.assets"; p.write_bytes(raw)
    db=parse_resources_assets(p)
    assert db.items[0].internal_id=="spider_joint"
    assert db.items[0].power==80
    assert db.rules.tier_rules[1].power_target==650
    assert db.rules.jackpot_cap==0.7


def test_save_parser_quantities_and_morph_bonuses(tmp_path: Path):
    payload={"Components":[
        {"Type":"MGSC.MagnumCargo","Content":{"ShipCargo":{"Items":[
            {"Content":{"Id":"spider_joint","StackCount":"3"}},
            {"Content":{"Id":"spider_joint","StackCount":"2"}},
        ]},"FridgeStorage":[],"RecyclingStorage":[]}},
        {"Type":"MGSC.MagnumProgression","Content":{"_purchasedPerks":[
            "moranl_upgrade_power","moranl_upgrade_power_2","moranl_upgrade_stability"]}},
    ]}
    p=tmp_path/"slot_0_session.dat"; p.write_text("\ufeff"+json.dumps(payload),encoding="utf-8")
    snap=read_save(p)
    assert snap.quantities["spider_joint"]==5
    assert snap.power_bonus==200
    assert snap.stability_bonus==40


def test_quantity_parallel_matches_single_process():
    items=[
        Item("A","eon",110,25,True,"a",3), Item("B","gavvakh",100,20,True,"b",2),
        Item("C","agga",90,20,True,"c",1), Item("D","siaira",80,25,True,"d",1), Item("E","shavva",75,20,True,"e",1),
    ]
    one=optimize_parallel(items,center_essence="siaira",tier=2,objective="balanced",top_n=30,workers=1)
    two=optimize_parallel(items,center_essence="siaira",tier=2,objective="balanced",top_n=30,workers=2)
    assert [r.order_text for r in one.results]==[r.order_text for r in two.results]

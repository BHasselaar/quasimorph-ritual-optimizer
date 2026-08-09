import itertools

from quasimorph_optimizer.models import Item
from quasimorph_optimizer.optimizer import evaluate_ritual, objective_key, optimize_parallel, ritual_order_count
from quasimorph_optimizer.sprites import _candidate_score


def items7():
    ess = ["eon", "gavvakh", "shavva", "siaira", "agga", "eon", "gavvakh"]
    return [Item(f"Item {i}", e, 60+i*9, 10+(i*4)%18, True, f"item_{i}", 3, price=100+i) for i,e in enumerate(ess)]


def test_distinct_default_ignores_extra_owned_copies_for_search_size():
    items = items7()
    assert ritual_order_count(items, False) == 21 * 24
    assert ritual_order_count(items, True) > ritual_order_count(items, False)


def test_numpy_distinct_backend_matches_small_exhaustive_reference():
    items = items7()
    summary = optimize_parallel(items, center_essence="siaira", tier=3, objective="sidegrade", top_n=10, workers=1)
    # Enumerate each 5-set with its minimum index anchored first: 24 ring orders each.
    candidates=[]
    for combo in itertools.combinations(range(len(items)),5):
        a=combo[0]
        for tail in itertools.permutations(combo[1:]):
            order=(a,*tail)
            result=evaluate_ritual(tuple(items[i] for i in order),center_essence="siaira",tier=3)
            candidates.append((objective_key(result,"sidegrade"),tuple(-i for i in order),result.order_text))
    expected=[x[2] for x in sorted(candidates,reverse=True)[:10]]
    assert [r.order_text for r in summary.results] == expected
    assert summary.backend == "numpy-batch"


def test_price_and_sprite_matching_helpers():
    order=tuple(items7()[:5])
    result=evaluate_ritual(order,center_essence="gavvakh",tier=1)
    assert result.total_price == sum(x.price for x in order)
    spider=Item("Spider Joint","agga",80,25,True,"spider_joint")
    assert _candidate_score(spider,"spiderJoint_icon","Sprite") >= 150
    assert _candidate_score(spider,"random_rifle_inv","Sprite") < 150

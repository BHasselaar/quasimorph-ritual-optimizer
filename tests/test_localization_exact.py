from quasimorph_optimizer.game_data import resolve_localized_names


def test_exact_tsv_localization_lookup():
    text = (
        "\tEnglish\tRussian\tGerman\n"
        "item.quasi_medical_kit_1.name\tGavvakh\tГаввах\tGavvakh\n"
        "item.ron_blood.name\tShavva\tШавва\tShavva\n"
        "item.impaler.name\tOssuary\tКостница\tOssarium\n"
    )
    resolved, diag = resolve_localized_names(
        text,
        ["quasi_medical_kit_1", "ron_blood", "impaler"],
    )
    assert resolved["quasi_medical_kit_1"] == "Gavvakh"
    assert resolved["ron_blood"] == "Shavva"
    assert resolved["impaler"] == "Ossuary"
    assert diag["resolved_count"] == 3
    assert diag["missing_count"] == 0


def test_shortdesc_is_never_used_as_name():
    text = (
        "\tEnglish\tRussian\n"
        "item.foo.shortdesc\tWrong value\tНеверно\n"
    )
    resolved, diag = resolve_localized_names(text, ["foo"])
    assert "foo" not in resolved
    assert diag["missing_item_ids"] == ["foo"]

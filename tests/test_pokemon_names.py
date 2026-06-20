from app import pokemon_names


def test_exact_chinese_links_to_other_locales():
    names = pokemon_names.localized_names("喷火龙")
    assert names["en"] == "Charizard"
    assert names["ja"] == "リザードン"
    assert names["zh-tw"] == "噴火龍"
    assert names["zh-cn"] == "喷火龙"


def test_english_is_case_insensitive():
    assert pokemon_names.localized_names("charizard")["ja"] == "リザードン"


def test_traditional_query_links_to_english():
    assert pokemon_names.localized_names("噴火龍")["en"] == "Charizard"


def test_query_containing_species_name_matches():
    # 喷火龙ex / Charizard VMAX style queries still resolve the species.
    assert pokemon_names.localized_names("喷火龙ex")["en"] == "Charizard"


def test_partial_prefix_matches_species():
    assert pokemon_names.localized_names("喷火")["en"] == "Charizard"


def test_unknown_query_returns_empty():
    assert pokemon_names.localized_names("totally-not-a-pokemon-1234") == {}
    assert pokemon_names.localized_names("") == {}

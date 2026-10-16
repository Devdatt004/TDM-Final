from classification.dictionary_detector import find_dictionary_matches


def test_finds_exact_dictionary_match():
    result = find_dictionary_matches(
        ["Bengaluru", "UnknownCity"],
        {"approved_cities": ["Bengaluru", "Mysuru"]},
    )

    assert result == [
        {
            "index": 0,
            "dictionary": "approved_cities",
            "matched": True,
        }
    ]


def test_matching_is_case_insensitive():
    result = find_dictionary_matches(
        ["bengaluru"],
        {"approved_cities": ["Bengaluru"]},
    )

    assert len(result) == 1
    assert result[0]["dictionary"] == "approved_cities"


def test_ignores_null_and_empty_values():
    result = find_dictionary_matches(
        [None, "", "   "],
        {"approved_terms": ["Example"]},
    )

    assert result == []


def test_unmatched_values_return_no_results():
    result = find_dictionary_matches(
        ["UnknownCity"],
        {"approved_cities": ["Bengaluru", "Mysuru"]},
    )

    assert result == []


def test_supports_multiple_dictionaries():
    result = find_dictionary_matches(
        ["Bengaluru", "Example"],
        {
            "approved_cities": ["Bengaluru"],
            "approved_terms": ["Example"],
        },
    )

    assert len(result) == 2
    assert {item["dictionary"] for item in result} == {
        "approved_cities",
        "approved_terms",
    }
def test_does_not_match_substrings():
    result = find_dictionary_matches(
        ["Bengaluru-East"],
        {"approved_cities": ["Bengaluru"]},
    )

    assert result == []
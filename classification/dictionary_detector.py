"""Dictionary-based candidate detection using caller-approved terms."""

from typing import Iterable


def find_dictionary_matches(
    values: Iterable[object],
    dictionaries: dict[str, Iterable[str]],
) -> list[dict[str, object]]:
    """Find exact, case-insensitive matches against approved dictionaries.

    Terms must be supplied by the caller from an approved source.
    This function does not establish identity or prove sensitivity.
    """
    normalized_dictionaries = {}

    for dictionary_name, terms in dictionaries.items():
        normalized_terms = {
            term.strip().casefold()
            for term in terms
            if isinstance(term, str) and term.strip()
        }
        if normalized_terms:
            normalized_dictionaries[dictionary_name] = normalized_terms

    matches = []

    for index, value in enumerate(values):
        if value is None:
            continue

        normalized_value = str(value).strip().casefold()
        if not normalized_value:
            continue

        for dictionary_name, terms in normalized_dictionaries.items():
            if normalized_value in terms:
                matches.append(
                    {
                        "index": index,
                        "dictionary": dictionary_name,
                        "matched": True,
                    }
                )

    return matches

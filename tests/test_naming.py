"""Tests for the Siri Name Cleaner."""

from __future__ import annotations

import pytest


class TestStripsArea:
    def test_strips_prefix(self, naming):
        assert (
            naming.clean_entity_name("Living Room Ceiling Light", "Living Room") == "Ceiling Light"
        )

    def test_strips_suffix(self, naming):
        assert (
            naming.clean_entity_name("Ceiling Light Living Room", "Living Room") == "Ceiling Light"
        )

    def test_multi_word_area_prefix(self, naming):
        assert naming.clean_entity_name("Master Bedroom Lamp", "Master Bedroom") == "Lamp"

    def test_multi_word_area_suffix(self, naming):
        assert naming.clean_entity_name("Lamp Master Bedroom", "Master Bedroom") == "Lamp"

    def test_case_insensitive_match(self, naming):
        # User typed the area in CamelCase, friendly_name is lowercase.
        assert naming.clean_entity_name("kitchen light", "Kitchen") == "light"

    def test_accent_insensitive_match(self, naming):
        # Friendly name lacks accents but area has them — Unicode normalization
        # test, not language-specific.
        assert naming.clean_entity_name("Cafe Lamp", "Café") == "Lamp"

    def test_strips_trailing_separator(self, naming):
        assert naming.clean_entity_name("Kitchen - Light", "Kitchen") == "Light"


class TestNoOp:
    def test_none_inputs(self, naming):
        assert naming.clean_entity_name(None, "Kitchen") is None
        assert naming.clean_entity_name("Light", None) is None

    def test_empty_inputs(self, naming):
        assert naming.clean_entity_name("", "Kitchen") is None
        assert naming.clean_entity_name("Light", "") is None

    def test_area_in_middle_is_not_stripped(self, naming):
        # We only strip prefix/suffix to avoid mangling "Lamp Kitchen Main".
        assert naming.clean_entity_name("Lamp Kitchen Main", "Kitchen") is None

    def test_area_equals_full_name_keeps_name(self, naming):
        # Pure single-token match — stripping would leave us with an empty alias.
        assert naming.clean_entity_name("Kitchen", "Kitchen") is None

    def test_single_token_match_when_area_is_multi(self, naming):
        # Can't strip more tokens than the name has.
        assert naming.clean_entity_name("Light", "Master Bedroom") is None

    def test_partial_token_match_not_stripped(self, naming):
        # "Kitchen" is a prefix of "Kitchens" but not the same token.
        assert naming.clean_entity_name("Kitchens Lamp", "Kitchen") is None


class TestTranslateAlias:
    def test_no_translations_returns_none(self, naming):
        # Identity overrides are noise — return None so the coordinator
        # doesn't bloat entity_config with them.
        assert naming.translate_alias("Ceiling Light", {}) is None

    def test_none_input(self, naming):
        assert naming.translate_alias(None, {"x": "y"}) is None

    def test_single_word_substitution(self, naming):
        assert naming.translate_alias("Lamp", {"lamp": "lampe"}) == "lampe"

    def test_multi_word_phrase_wins_over_single(self, naming):
        # "ceiling light" must beat "ceiling" alone — that's the whole point
        # of the longest-match algorithm.
        assert (
            naming.translate_alias(
                "Ceiling Light",
                {"ceiling": "plafond", "ceiling light": "plafonnier"},
            )
            == "plafonnier"
        )

    def test_unmatched_tokens_pass_through(self, naming):
        assert naming.translate_alias("Living Room Lamp", {"lamp": "lampe"}) == "Living Room lampe"

    def test_case_insensitive_match(self, naming):
        assert naming.translate_alias("LAMP", {"lamp": "lampe"}) == "lampe"

    def test_no_match_returns_none(self, naming):
        # When nothing changes the function reports None — same convention
        # as clean_entity_name.
        assert naming.translate_alias("Spotlight", {"lamp": "lampe"}) is None


class TestIdempotency:
    """Critical: re-running the cleaner on its own output must not change it.

    If this property breaks, the coordinator can enter an oscillation:
    push override → registry event → recompute → different override → loop.
    """

    @pytest.mark.parametrize(
        "friendly,area",
        [
            ("Living Room Ceiling Light", "Living Room"),
            ("Ceiling Light Living Room", "Living Room"),
            ("Master Bedroom Lamp", "Master Bedroom"),
            ("Cafe Lamp", "Café"),
            ("Lamp Kitchen Main", "Kitchen"),
            ("Kitchen", "Kitchen"),
        ],
    )
    def test_clean_then_clean_is_stable(self, naming, friendly, area):
        once = naming.clean_entity_name(friendly, area)
        if once is None:
            return  # no override — nothing to re-apply
        twice = naming.clean_entity_name(once, area)
        # Cleaning the already-clean form must be a no-op (returns None
        # because there's nothing left to strip).
        assert twice is None

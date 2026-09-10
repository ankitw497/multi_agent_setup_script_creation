"""Tests for planning/archetypes.py (plan §9, §10.2)."""
from planning.archetypes import ALL_ARCHETYPES, get_archetype_spec, load_archetype_specs


def test_all_six_archetypes_are_defined():
    specs = load_archetype_specs()
    assert set(specs.keys()) == set(ALL_ARCHETYPES)
    assert len(ALL_ARCHETYPES) == 6


def test_every_archetype_has_core_roles_and_a_driver():
    for name in ALL_ARCHETYPES:
        spec = get_archetype_spec(name)
        assert len(spec.core_roles) >= 2
        assert spec.driver


def test_mystery_matches_the_plan_9_table():
    spec = get_archetype_spec("mystery")
    assert spec.core_roles == ["expectation", "contradiction", "mechanism", "resolution"]
    assert "suspects" in spec.optional_roles
    assert spec.driver == "unanswered cause"


def test_optional_roles_are_never_in_core_roles():
    for name in ALL_ARCHETYPES:
        spec = get_archetype_spec(name)
        assert not set(spec.core_roles) & set(spec.optional_roles)

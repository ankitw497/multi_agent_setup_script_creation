"""Loads config/archetypes.yaml into ArchetypeSpec objects (plan §9, §10.2).

The six shapes are config, not code -- never hard-code a role list or a
driver string in a prompt when this module can supply the real one.
"""
from __future__ import annotations

from functools import lru_cache

from config import CONFIG_DIR
from config.loader import load_yaml

from .models import Archetype, ArchetypeSpec

ALL_ARCHETYPES: tuple[Archetype, ...] = (
    "mystery", "build", "experiment", "derivation", "foundation", "framework",
)


@lru_cache
def load_archetype_specs() -> dict[Archetype, ArchetypeSpec]:
    raw = load_yaml("archetypes.yaml")
    return {name: ArchetypeSpec(archetype=name, **spec) for name, spec in raw.items()}


def get_archetype_spec(archetype: Archetype) -> ArchetypeSpec:
    return load_archetype_specs()[archetype]

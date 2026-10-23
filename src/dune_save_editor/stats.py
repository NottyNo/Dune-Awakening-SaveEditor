from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Number = int | float


@dataclass(frozen=True, slots=True)
class StatDefinition:
    key: str
    label: str
    group: str
    actor: Literal["pawn", "controller"]
    document: Literal["properties", "gas_attributes"]
    path: tuple[str, ...]
    kind: Literal["integer", "real", "boolean"]
    minimum: Number | None = None
    maximum: Number | None = None
    mirrored_paths: tuple[tuple[str, ...], ...] = ()
    help_text: str = ""


CHARACTER_STATS: tuple[StatDefinition, ...] = (
    StatDefinition(
        "maximum_health",
        "Maximum health",
        "Vitals",
        "pawn",
        "properties",
        ("DamageableActorComponent", "m_CurrentMaxHealth"),
        "real",
        1,
        1_000_000,
        (("DamageableActorComponent", "m_TotalMaxHealth"),),
        "Updates both persisted maximum-health values.",
    ),
    StatDefinition(
        "tech_knowledge_points",
        "Tech knowledge points",
        "Progression",
        "pawn",
        "properties",
        ("TechKnowledgePlayerComponent", "m_TechKnowledgePoints"),
        "integer",
        0,
        1_000_000,
    ),
    StatDefinition(
        "current_hydration",
        "Current hydration",
        "Hydration & Heat",
        "pawn",
        "gas_attributes",
        ("DuneHydrationAttributeSet", "CurrentHydration", "CurrentValue"),
        "real",
        0,
        1_000_000,
        (("DuneHydrationAttributeSet", "CurrentHydration", "BaseValue"),),
    ),
    StatDefinition(
        "captured_water",
        "Clothing captured water",
        "Hydration & Heat",
        "pawn",
        "gas_attributes",
        ("DuneHydrationAttributeSet", "ClothingCapturedWater", "CurrentValue"),
        "real",
        0,
        1_000_000,
        (("DuneHydrationAttributeSet", "ClothingCapturedWater", "BaseValue"),),
    ),
    StatDefinition(
        "dehydration_penalty",
        "Dehydration penalty",
        "Hydration & Heat",
        "pawn",
        "gas_attributes",
        ("DuneHydrationAttributeSet", "DehydrationPenalty", "CurrentValue"),
        "real",
        0,
        1_000_000,
        (("DuneHydrationAttributeSet", "DehydrationPenalty", "BaseValue"),),
    ),
    StatDefinition(
        "heat_exhaustion",
        "Heat exhaustion",
        "Hydration & Heat",
        "pawn",
        "gas_attributes",
        ("DuneHydrationAttributeSet", "HeatExhaustion", "CurrentValue"),
        "real",
        0,
        1_000_000,
        (("DuneHydrationAttributeSet", "HeatExhaustion", "BaseValue"),),
    ),
    StatDefinition(
        "current_spice",
        "Current spice",
        "Spice",
        "pawn",
        "gas_attributes",
        ("DuneSpiceAddictionAttributeSet", "CurrentSpice", "CurrentValue"),
        "real",
        0,
        1_000_000,
        (("DuneSpiceAddictionAttributeSet", "CurrentSpice", "BaseValue"),),
    ),
    StatDefinition(
        "spice_addiction_level",
        "Spice addiction level",
        "Spice",
        "pawn",
        "gas_attributes",
        ("DuneSpiceAddictionAttributeSet", "SpiceAddictionLevel", "CurrentValue"),
        "real",
        0,
        1_000_000,
        (("DuneSpiceAddictionAttributeSet", "SpiceAddictionLevel", "BaseValue"),),
    ),
    StatDefinition(
        "spice_exposure",
        "Spice exposure",
        "Spice",
        "pawn",
        "gas_attributes",
        ("DuneSpiceAddictionAttributeSet", "SpiceExposure", "CurrentValue"),
        "real",
        0,
        1_000_000,
        (("DuneSpiceAddictionAttributeSet", "SpiceExposure", "BaseValue"),),
    ),
    StatDefinition(
        "spice_tolerance",
        "Spice tolerance",
        "Spice",
        "pawn",
        "gas_attributes",
        ("DuneSpiceAddictionAttributeSet", "SpiceTolerance", "CurrentValue"),
        "real",
        0,
        1_000_000,
        (("DuneSpiceAddictionAttributeSet", "SpiceTolerance", "BaseValue"),),
    ),
    StatDefinition(
        "spice_threshold_level",
        "Spice exposure threshold",
        "Spice",
        "controller",
        "properties",
        ("BP_JourneyComponent_C", "CurrentSpiceExposureThresholdLevel"),
        "integer",
        0,
        100,
    ),
    StatDefinition(
        "eyes_of_ibad_value",
        "Eyes of Ibad intensity",
        "Spice",
        "pawn",
        "properties",
        ("BP_DunePlayerCharacter_C", "m_EyesOfIbadValue"),
        "real",
        0,
        1,
    ),
    StatDefinition(
        "eyes_of_ibad_visible",
        "Eyes of Ibad visible",
        "Status Flags",
        "pawn",
        "properties",
        ("BP_DunePlayerCharacter_C", "m_bEyesOfIbadVisible"),
        "boolean",
    ),
    StatDefinition(
        "heatstroke",
        "Heatstroke active",
        "Status Flags",
        "pawn",
        "properties",
        ("BP_DunePlayerCharacter_C", "m_bHeatstroke"),
        "boolean",
    ),
)


SPECIALIZATION_TRACKS: tuple[tuple[int, str], ...] = (
    (1, "Crafting"),
    (2, "Gathering"),
    (3, "Exploration"),
    (4, "Combat"),
    (5, "Sabotage"),
)

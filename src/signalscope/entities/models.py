from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EntityModelSpec:
    """Who runs an entity extraction model and which model it is."""

    provider: str
    model: str


# The local entity model for this phase. It is multilingual and finds any
# labels it is given, so the labels below are a choice, not part of the model.
GLINER_MULTI = EntityModelSpec(provider="gliner", model="urchade/gliner_multi-v2.1")

# The entity types SignalScope asks for. The database accepts any type, so this
# list can grow without a migration.
ENTITY_LABELS = (
    "person",
    "organization",
    "location",
    "country",
    "city",
    "product",
    "event",
    "date",
)

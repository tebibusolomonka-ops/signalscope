import pytest

from signalscope.evaluation.extraction.dataset import (
    ExtractionDataset,
    ExtractionDocument,
    GoldRelation,
)
from signalscope.evaluation.extraction.relations import evaluate_relations
from signalscope.evaluation.extraction.scoring import ExtractionScore
from signalscope.relations.provider import ExtractedRelation

pytestmark = pytest.mark.anyio

TEXT = "Ana Silva works for Acme. Acme is located in Porto."


class ScriptedRelations:
    provider_name = "test"
    model_name = "scripted"

    def __init__(self, relations: list[ExtractedRelation]) -> None:
        self.relations = relations

    async def extract(self, text: str) -> list[ExtractedRelation]:
        return self.relations if text == TEXT else []


DATASET = ExtractionDataset(
    name="relations",
    documents=(ExtractionDocument("a", TEXT), ExtractionDocument("b", "Nothing here.")),
    relations=(
        GoldRelation("a", "Ana Silva", "works_for", "Acme"),
        GoldRelation("a", "Acme", "located_in", "Porto"),
    ),
)


def found(subject: str, relation_type: str, obj: str) -> ExtractedRelation:
    return ExtractedRelation(subject_text=subject, relation_type=relation_type, object_text=obj)


async def score(*relations: ExtractedRelation) -> ExtractionScore:
    return await evaluate_relations(DATASET, ScriptedRelations(list(relations)))


WORKS = found("Ana Silva", "works_for", "Acme")
LOCATED = found("Acme", "located_in", "Porto")


async def test_perfect() -> None:
    result = await score(WORKS, LOCATED)

    assert (result.kind, result.document_count, result.gold_count, result.matched_count) == (
        "relation",
        2,
        2,
        2,
    )
    assert (result.precision, result.recall, result.f1) == (1.0, 1.0, 1.0)


async def test_wrong_relation_type() -> None:
    result = await score(found("Ana Silva", "member_of", "Acme"), LOCATED)

    assert result.matched_count == 1


async def test_reversed_relation_does_not_match() -> None:
    result = await score(found("Acme", "works_for", "Ana Silva"), LOCATED)

    assert result.matched_count == 1
    assert result.documents[0].missed == ("Ana Silva works_for Acme",)
    assert result.documents[0].extra == ("Acme works_for Ana Silva",)


async def test_missing() -> None:
    result = await score(WORKS)

    assert (result.precision, result.recall) == (1.0, 0.5)


async def test_extra() -> None:
    result = await score(WORKS, LOCATED, found("Ana Silva", "located_in", "Porto"))

    assert result.precision == pytest.approx(2 / 3)
    assert result.f1 == pytest.approx(0.8)


async def test_duplicates_do_not_add_matches() -> None:
    result = await score(WORKS, WORKS, WORKS)

    assert (result.matched_count, result.predicted_count) == (1, 3)
    assert result.precision == pytest.approx(1 / 3)


async def test_case_and_spacing_are_normalized() -> None:
    result = await score(
        found(" ana   SILVA ", " Works_For ", "ACME"), found("acme", "LOCATED_IN", "porto")
    )

    assert result.matched_count == 2


async def test_no_predictions() -> None:
    result = await score()

    assert (result.predicted_count, result.precision, result.recall, result.f1) == (
        0,
        None,
        0.0,
        None,
    )

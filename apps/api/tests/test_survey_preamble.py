"""Prose between questions reaches the model as that question's `preamble`.

The parser threw away everything that was not a question, an option or a table row: the product
stimulus (Section C), the five concept descriptions (Section E) and the respondent instructions.
It now keeps that prose on the next question as `preamble`. Ids, text and types are untouched.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from src.adapters.legacy_backend.runtime import load_module


_PROVIDED_INFO = pathlib.Path(__file__).resolve().parents[1] / "legacy_runtime" / "Provided Info"
_HIGHMED = _PROVIDED_INFO / "Neo Smart Living — Survey_HighMedPriority.md"


@pytest.fixture
def parser(test_settings):
    return load_module("backend.survey.parser", test_settings.legacy_app_root)


@pytest.fixture
def normalizer(test_settings):
    return load_module("backend.survey.schema_normalizer", test_settings.legacy_app_root)


@pytest.fixture
def schemas(test_settings):
    return load_module("backend.schemas", test_settings.legacy_app_root)


@pytest.fixture
def prompt_builder(test_settings):
    return load_module("backend.simulation.prompt_builder", test_settings.legacy_app_root)


def _parse(parser, text: str, source_format: str = "md") -> dict:
    return parser.parse_text_to_raw_payload(text=text, source_format=source_format)


def _by_id(payload: dict) -> dict:
    return {question["id"]: question for question in payload["questions"]}


PREAMBLE_SURVEY = """# Preamble fixture

Intro line before any question.

---

## Section A: Warm-up

Q1: Have you used a product like this before?

- [ ] Yes
- [ ] No

---

## Section B: Product Stimulus

**[Respondents read the following product description before answering.]**

**Product Description — Widget**

[Product image]

*[Fallback link if image rendering is blocked: Widget model page]*

The Widget is a compact 10-square-foot unit that costs $1,000 installed.

### Purchase Interest (RQ1)

**Q2. Purchase interest** How interested are you in the Widget?

| Not at all | Slightly | Very |
|---|---|---|
| 1 | 2 | 3 |

**[Instructions to respondent:]** *Read the concept, then rate it.*

---

### Concept 1: Backyard Office

> **"Work from the garden."** A quiet office steps from your door.

Q3: For each barrier, rate how much it reduces your likelihood.

| Barrier | 1 | 2 | 3 |
|---|---|---|---|
| Cost | o | o | o |
| Space | o | o | o |

Q4: Anything else?
"""


def test_prose_between_questions_becomes_the_next_questions_preamble(parser):
    by_id = _by_id(_parse(parser, PREAMBLE_SURVEY))
    assert by_id["Q1"]["preamble"] is None
    assert by_id["Q2"]["preamble"] == (
        "Product Description — Widget\n"
        "The Widget is a compact 10-square-foot unit that costs $1,000 installed."
    )


def test_instruction_text_concept_heading_and_quote_are_kept_in_reading_order(parser):
    by_id = _by_id(_parse(parser, PREAMBLE_SURVEY))
    assert by_id["Q3_1"]["preamble"] == (
        "Read the concept, then rate it.\n"
        "Concept 1: Backyard Office\n"
        '"Work from the garden." A quiet office steps from your door.'
    )


def test_matrix_sub_questions_share_the_parents_preamble(parser):
    by_id = _by_id(_parse(parser, PREAMBLE_SURVEY))
    assert by_id["Q3_1"]["preamble"]
    assert by_id["Q3_1"]["preamble"] == by_id["Q3_2"]["preamble"]


def test_markup_rules_stage_directions_and_table_rows_never_reach_a_preamble(parser):
    payload = _parse(parser, PREAMBLE_SURVEY)
    joined = "\n".join(question["preamble"] or "" for question in payload["questions"])
    for junk in ("Product image", "Fallback link", "Respondents read", "Section ", "(RQ", "---", "|", "**", "> ", "#"):
        assert junk not in joined, f"{junk!r} leaked into a preamble: {joined!r}"
    assert _by_id(payload)["Q4"]["preamble"] is None


def test_question_ids_text_and_types_are_unchanged(parser):
    payload = _parse(parser, PREAMBLE_SURVEY)
    by_id = _by_id(payload)
    assert [question["id"] for question in payload["questions"]] == ["Q1", "Q2", "Q3_1", "Q3_2", "Q4"]
    assert by_id["Q1"]["text"] == "Have you used a product like this before?"
    assert by_id["Q2"]["text"] == "Purchase interest How interested are you in the Widget?"
    assert by_id["Q3_1"]["text"] == "For each barrier, rate how much it reduces your likelihood. — Cost"
    assert by_id["Q4"]["text"] == "Anything else?"
    assert [question["question_type"] for question in payload["questions"]] == [
        "single_choice", "likert", "likert", "likert", "open_text",
    ]
    assert by_id["Q2"]["options"] == ["Not at all", "Slightly", "Very"]
    assert (by_id["Q2"]["min_value"], by_id["Q2"]["max_value"]) == (1, 3)


def test_description_no_longer_carries_horizontal_rules(parser):
    payload = _parse(parser, PREAMBLE_SURVEY)
    assert payload["description"] == "Intro line before any question."


def test_flat_docx_text_collects_no_preamble(parser):
    by_id = _by_id(_parse(parser, PREAMBLE_SURVEY, source_format="docx"))
    assert all(question["preamble"] is None for question in by_id.values())


def test_highmed_stimulus_and_concepts_attach_to_their_questions(parser):
    payload = _parse(parser, _HIGHMED.read_text(encoding="utf-8"))
    by_id = _by_id(payload)
    assert len(by_id) == 39
    assert "117-square-foot" in by_id["Q1"]["preamble"]
    assert "$23,000" in by_id["Q1"]["preamble"]
    q9a_lines = by_id["Q9A"]["preamble"].split("\n")
    assert q9a_lines[0].startswith("You will now read five short descriptions")
    assert "Concept 1: Backyard Home Office" in q9a_lines
    assert "Work smarter" in by_id["Q9A"]["preamble"]
    assert by_id["Q10A"]["preamble"].startswith("Concept 2: Guest Suite / STR Income")
    assert by_id["Q15"]["preamble"].startswith("Neo Smart Living emphasizes three key advantages")
    assert by_id["Q5_1"]["preamble"] == by_id["Q5_2"]["preamble"]
    assert by_id["Q0A"]["preamble"] is None
    with_preamble = {qid for qid, q in by_id.items() if q["preamble"]}
    assert with_preamble == {"Q1", "Q9A", "Q10A", "Q11A", "Q12A", "Q13A", "Q15"}
    assert "---" not in payload["description"]
    assert "Target population" in payload["description"]


def _raw(questions: list) -> dict:
    return {"survey_title": "Upload", "source_format": "md", "parse_warnings": [], "questions": questions}


def test_normalizer_passes_the_preamble_through(normalizer):
    schema = normalizer.normalize_survey_payload(_raw([
        {"id": "Q1", "text": "Interest?", "question_type": "open_text", "preamble": "  The Widget costs $1,000.  "},
        {"id": "Q2", "text": "Why?", "question_type": "open_text"},
    ]))
    assert schema.questions[0].preamble == "The Widget costs $1,000."
    assert schema.questions[1].preamble is None
    assert schema.questions[0].model_dump()["preamble"] == "The Widget costs $1,000."


def test_a_blank_preamble_normalizes_to_none(normalizer):
    schema = normalizer.normalize_survey_payload(_raw([{"id": "Q1", "text": "Interest?", "question_type": "open_text", "preamble": "   "}]))
    assert schema.questions[0].preamble is None


def test_a_question_dict_without_the_key_still_validates(schemas):
    assert schemas.SurveyQuestion(id="Q1", text="Interest?", question_type="open_text").preamble is None


def test_highmed_preambles_survive_normalization_and_validation(test_settings):
    from src.adapters.legacy_backend.domain import parse_normalize_validate_survey

    payload = parse_normalize_validate_survey(_HIGHMED.name, _HIGHMED.read_bytes(), test_settings.legacy_app_root)
    by_id = {q["id"]: q for q in payload["questions"]}
    assert len(by_id) == 39
    assert "117-square-foot" in by_id["Q1"]["preamble"] and "$23,000" in by_id["Q1"]["preamble"]
    assert "Concept 1: Backyard Home Office" in by_id["Q9A"]["preamble"].split("\n")
    assert "Guest Suite" in by_id["Q10A"]["preamble"]
    assert by_id["Q5_1"]["preamble"] == by_id["Q5_2"]["preamble"]
    assert by_id["Q0A"]["preamble"] is None
    assert "---" not in (payload["description"] or "")

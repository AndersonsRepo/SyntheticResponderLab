"""Barrier rows are named by their matrix row, not by the preamble every row shares.

The parsers expand the Q5 barrier matrix into Q5_1..Q5_7, each worded "<shared preamble> — <row>". Compacting
that text from the front gave every row the same truncated label, so the Insights headline read
"Barrier severity matrix Below is a list of potentia... is the heaviest objection signal." whichever
barrier led.
"""

from __future__ import annotations

from src.adapters.legacy_backend.domain import build_insights_view

PREAMBLE = (
    "Barrier severity matrix Below is a list of potential concerns a homeowner might have about purchasing a "
    "backyard prefab unit. For each, please indicate how strongly it would reduce your likelihood of "
    "purchasing the Tahoe Mini. (1 = Would not reduce my likelihood at all, 5 = Would strongly reduce my "
    "likelihood)"
)
BARRIERS = [
    ("Q5_1", "The total cost (~$23,000)", [5, 4]),
    ("Q5_2", "HOA restrictions or community rules", [2, 3]),
    ("Q5_3", "Uncertainty about whether a building permit is required", [4, 4]),
]
SEGMENTS = ["Remote Professionals", "Wellness-Oriented"]


def _payload() -> dict:
    records = []
    for index in range(4):
        for question_id, row, answers in BARRIERS:
            records.append(
                {
                    "respondent_id": f"RESP_{index + 1:03d}",
                    "model": "openai/gpt-4o-mini",
                    "experiment_mode": "split",
                    "survey_title": "Neo Smart Living Demo Survey",
                    "question_id": question_id,
                    "question_text": f"{PREAMBLE} — {row}",
                    "question_type": "likert",
                    "answer": answers[index % len(answers)],
                    "segment_label": SEGMENTS[index % len(SEGMENTS)],
                    "run_id": "run_neo_labels",
                }
            )
    return {
        "run_id": "run_neo_labels",
        "status": "completed",
        "survey_title": "Neo Smart Living Demo Survey",
        "models_used": ["openai/gpt-4o-mini"],
        "experiment_mode": "split",
        "response_records": records,
    }


def test_barrier_rows_are_labelled_by_their_matrix_row(test_settings):
    view = build_insights_view(settings=test_settings, study_mode="neo_smart", latest_run_payload=_payload())

    rows = view["charts"]["barrier_ranking"]["rows"]
    assert [row["label"] for row in rows] == [
        "The total cost (~$23,000)",
        "Uncertainty about whether a building permit is required",
        "HOA restrictions or community rules",
    ]

    finding = next(f for f in view["top_findings"] if f.get("title") == "Barrier severity")
    assert finding["headline"] == "The total cost (~$23,000) is the heaviest objection signal."

    heatmap_labels = {row["question_id"]: row["label"] for row in view["charts"]["segment_heatmap"]["rows"]}
    assert heatmap_labels["Q5_1"] == "The total cost (~$23,000)"


def test_model_difference_rows_name_the_barrier(test_settings):
    payload = _payload()
    for record in payload["response_records"]:
        respondent = int(record["respondent_id"].rsplit("_", 1)[1])
        record["model"] = ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5"][respondent % 2]
    payload["models_used"] = ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5"]
    view = build_insights_view(settings=test_settings, study_mode="neo_smart", latest_run_payload=payload)

    labels = {row["question_id"]: row["label"] for row in view["charts"]["model_difference"]["rows"]}
    assert labels, "two models answered, so the model difference chart has rows"
    assert all(not label.startswith("Barrier severity matrix") for label in labels.values())


def test_a_question_without_a_matrix_row_keeps_its_compact_label(test_settings):
    payload = _payload()
    for record in payload["response_records"]:
        if record["question_id"] == "Q5_2":
            record["question_text"] = "Barrier: HOA rules"
    view = build_insights_view(settings=test_settings, study_mode="neo_smart", latest_run_payload=payload)

    labels = {row["question_id"]: row["label"] for row in view["charts"]["barrier_ranking"]["rows"]}
    assert labels["Q5_2"] == "Barrier: HOA rules"

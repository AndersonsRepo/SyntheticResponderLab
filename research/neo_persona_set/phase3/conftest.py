"""Offline fixtures: a fake two-header AYTM-style CSV (12 respondents) and a fake phase-2 run (6 personas)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

N_REAL = 12
C1 = 'Concept 1: Backyard Home Office ("Work smarter — right in your backyard")'
C5 = 'Concept 5: Message-First ("Skip the stress of traditional building")'
NONE_CONCEPT = "None of the above — I would not be motivated by any of these"
LIKERT_INTEREST = "Not at all interested|Slightly interested|Moderately interested|Very interested|Extremely interested"
LIKERT_WOULD = "Definitely would not|Probably would not|Might or might not|Probably would|Definitely would"
LIKERT_INCREASE = "Does not increase at all|Slightly increases|Moderately increases|Strongly increases|Very strongly increases"
Q0A_OPTIONS = ["Yes, I have actively researched or priced options", "Yes, I have thought about it but not researched it",
               "I'm aware it's possible but haven't seriously considered it", "No, I have never considered this"]
Q6_OPTIONS = "The total cost (~$23,000)|HOA restrictions or community rules|Uncertainty about whether a building permit is required|Limited backyard space or access|Lack of financing options|Concerns about build quality or durability|Uncertainty about resale value|None — I have no significant concerns"
Q20_OPTIONS = "Outdoor club sponsorships / community events|Social media ads (Facebook, Instagram)|Google / Search ads|Home improvement expos|Real estate partner referrals|Friend / family referral"
Q22_OPTIONS = "Under $50,000|$50,000–$74,999|$75,000–$99,999|$100,000–$149,999|$150,000–$199,999|$200,000 or more|Prefer not to say"


def _selected(label: str, indices: Iterable[int]) -> List[str]:
    chosen = set(indices)
    return [label if i in chosen else "" for i in range(N_REAL)]


def fake_real_columns() -> List[Tuple[str, str, List[str]]]:
    """(row-1 text, row-2 label, 12 cells) per column; Q1 is the intro screen so the offset test bites."""
    return [
        ("Response ID", "", [str(1000 + i) for i in range(N_REAL)]),
        ("Gender", "", ["Female", "Male"] * 6),
        ("Age", "", ["24", "31", "38", "45", "52", "58", "63", "67", "72", "29", "41", "55"]),
        ("Household Income", "", ["$0 - $24,999", "$25,000 - $49,999", "$50,000 - $74,999", "$75,000 - $99,999", "$100,000 - $199,999", "$200,000 or more"] * 2),
        ("PQ1: Does your property have any outdoor area where a small detached structure could be placed?", "", ["Yes"] * 10 + ["I'm not sure, but possibly."] * 2),
        ("Q1: Please read: (Neo Smart Living is a Southern California company)", "", ["read"] * N_REAL),
        ("Q2: Have you ever looked into or considered adding a small detached structure?", "", [Q0A_OPTIONS[i // 3] for i in range(N_REAL)]),
        ("Q6: Based on the product description above, how interested would you be in purchasing?", "", ["1 - Not interested"] * 2 + ["2"] * 2 + ["3"] * 4 + ["4"] * 2 + ["5 - Extremely interested"] * 2),
        ("Q9: Below is a list of potential concerns a homeowner might have.", "The total cost (~$23,000) : Below is a list of potential concerns", ["5 - Would strongly reduce my likelihood"] * 6 + ["4"] * 3 + ["3"] * 3),
        ("", "HOA restrictions or community rules : Below is a list of potential concerns", ["1 - Would not reduce my likelihood at all"] * 6 + ["2"] * 6),
        ("Q11: Which one barrier above would be the single greatest obstacle?", "", ["The total cost (~$23,000)"] * 6 + ["HOA restrictions or community rules"] * 2 + ["Other (please specify)"] * 2 + ["None — I have no significant concerns"] * 2),
        ('Q12: This question is for quality assurance. Please select "Moderately interested".', "", ["Moderately interested"] * N_REAL),
        ("Q29: Of the five concepts you just reviewed, which one would most strongly motivate you?", "", ["Concept 1: Backyard Home Office"] * 5 + ["Concept 5: Simplicity (Transparency + Speed + Less Headache)"] * 3 + [NONE_CONCEPT] * 4),
        ("Q30: Neo Smart Living emphasizes several key advantages of the Tahoe Mini.", 'Permit-light positioning: "At 117 sq ft, the Tahoe Mini is sized to avoid permits."', ["2"] * 6 + ["4"] * 6),
        ("", 'Installation speed: "The Tahoe Mini is delivered as flat-packed panels."', ["5 - Very strongly increases"] * N_REAL),
        ("", 'Build quality and details: "The Tahoe Mini comes standard with pre-wired electrical."', ["1 - Does not increase"] * 4 + ["3"] * 4 + ["5 - Very strongly increases"] * 4),
        ("Q31: Which value driver most increases your purchase likelihood?", "", ["Build quality and details"] * 5 + ["Installation speed"] * 3 + ["Permit-light positioning"] * 2 + ["Smart Technology"] * 2),
        ("Q32: If Neo Smart Living partnered with local outdoor clubs or events, how would that affect your trust?", "", ["1 - Decrease a lot", "2"] + ["3"] * 6 + ["4"] * 2 + ["5 - Increase a lot"] * 2),
        ("Q33.A1: Which outreach methods would most likely get your attention?", "", _selected("Outdoor club sponsorships / community events", range(0, 6))),
        ("Q33.A2: Which outreach methods would most likely get your attention?", "", _selected("Social media ads (Facebook, Instagram)", range(0, 3))),
        ("Q33.A5: Which outreach methods would most likely get your attention?", "", _selected("Google / Search ads", range(0, 10))),
        ("Q33.A11: Which outreach methods would most likely get your attention?", "", _selected("Other (please specify)", (10, 11))),
        ("Q33.A11.OE", "", _selected("carrier pigeon,\nby hand", (10, 11))),
        ("Q34.2: For this product, at which point would you consider the price to be...", "1. so cheap that you would think it couldn't be a quality product.", ["9000"] * N_REAL),
        ("Q35: Is your home subject to a Homeowners Association (HOA)?", "", ["Yes"] * 4 + ["No"] * 6 + ["I'm not sure"] * 2),
        ("Q36: How frequently do you participate in outdoor recreation activities?", "", ["Never"] * 2 + ["A few times a year"] * 4 + ["About once a month"] * 2 + ["2–3 times per month"] * 2 + ["Weekly or more"] * 2),
        ("Q37.A1: Are you currently a member of any organized outdoor recreation club?", "", _selected("Mountain bike club", range(0, 4))),
        ("Q37.A14: Are you currently a member of any organized outdoor recreation club?", "", _selected("No, I am not part of any organized outdoor recreation clubs or community groups.", range(4, 12))),
    ]


def build_fake_real_csv(path: Path) -> Path:
    columns = fake_real_columns()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([c[0] for c in columns])
        writer.writerow([c[1] for c in columns])
        for i in range(N_REAL):
            writer.writerow([c[2][i] for c in columns])
    return path


FAKE_QUESTIONS: List[Tuple[str, str, str, str, str, str]] = [
    ("S3", "single_choice", "", "", "Yes|I'm not sure, but possibly|No", "Outdoor space feasibility"),
    ("Q0A", "single_choice", "", "", "|".join(Q0A_OPTIONS), "Prior consideration"),
    ("Q1", "likert", "1", "5", LIKERT_INTEREST, "Purchase interest at $23,000"),
    ("Q2", "likert", "1", "5", LIKERT_WOULD, "Purchase likelihood (24-month horizon)"),
    ("Q5_1", "likert", "1", "5", "", "Barrier severity matrix — The total cost (~$23,000)"),
    ("Q5_2", "likert", "1", "5", "", "Barrier severity matrix — HOA restrictions or community rules"),
    ("Q6", "single_choice", "", "", Q6_OPTIONS, "Single greatest barrier"),
    ("Q7", "likert", "1", "5", "Decreases my likelihood|No effect on my likelihood|Slightly increases my likelihood|Moderately increases my likelihood|Greatly increases my likelihood", "Permit-light effect on likelihood"),
    ("Q14", "single_choice", "", "", "|".join([C1, C5, NONE_CONCEPT]), "Concept preference"),
    ("Q15", "likert", "1", "5", LIKERT_INCREASE, "Permit-light positioning"),
    ("Q16", "likert", "1", "5", LIKERT_INCREASE, "Installation speed"),
    ("Q17", "likert", "1", "5", LIKERT_INCREASE, "Build quality and details"),
    ("Q18", "single_choice", "", "", "Permit-light positioning|Installation speed|Build quality and details", "Most persuasive value driver"),
    ("Q19", "likert", "1", "5", "Decrease a lot|Decrease a little|No effect|Increase a little|Increase a lot", "Sponsorship impact"),
    ("Q20", "multi_choice", "", "", Q20_OPTIONS, "Most effective outreach channel (select up to 2)"),
    ("Q21", "single_choice", "", "", "18–24|25–34|35–44|45–54|55–64|65 or older", "Age"),
    ("Q22", "single_choice", "", "", Q22_OPTIONS, "Household income"),
    ("Q24", "single_choice", "", "", "Yes|No|I'm not sure", "HOA status"),
    ("Q25", "single_choice", "", "", "Never|A few times a year|About once a month|2–3 times per month|Weekly or more", "Outdoor recreation frequency"),
    ("Q26", "single_choice", "", "", "Yes|No", "Outdoor club membership"),
    ("Q30", "single_choice", "", "", LIKERT_INTEREST, "Attention check"),
]

FAKE_ANSWERS: Dict[str, List[str]] = {
    "S3": ["Yes", "Yes", "No", "I'm not sure, but possibly", "Yes", "No"],
    "Q0A": [Q0A_OPTIONS[0], Q0A_OPTIONS[1], Q0A_OPTIONS[2], Q0A_OPTIONS[3], Q0A_OPTIONS[1], Q0A_OPTIONS[3]],
    "Q1": ["3", "3", "1", "4", "5", "2"],
    "Q2": ["2", "3", "1", "4", "3", "2"],
    "Q5_1": ["5", "4", "1", "5", "3", "2"],
    "Q5_2": ["1", "2", "5", "1", "2", "4"],
    "Q6": ["The total cost (~$23,000)", "The total cost (~$23,000)", "HOA restrictions or community rules", "The total cost (~$23,000)", "Limited backyard space or access", "None — I have no significant concerns"],
    "Q7": ["3", "4", "2", "3", "5", "3"],
    "Q14": [C1, C1, C5, C1, NONE_CONCEPT, C5],
    "Q15": ["2", "4", "3", "2", "4", "1"],
    "Q16": ["5", "5", "4", "5", "5", "3"],
    "Q17": ["1", "3", "5", "3", "5", "1"],
    "Q18": ["Build quality and details", "Build quality and details", "Permit-light positioning", "Build quality and details", "Build quality and details", "Permit-light positioning"],
    "Q19": ["3", "4", "3", "5", "2", "3"],
    "Q20": ["Outdoor club sponsorships / community events|Google / Search ads", "Google / Search ads", "Social media ads (Facebook, Instagram)|Home improvement expos",
            "Outdoor club sponsorships / community events|Friend / family referral", "Google / Search ads|Real estate partner referrals", "Home improvement expos"],
    "Q21": ["25–34", "35–44", "45–54", "55–64", "65 or older", "18–24"],
    "Q22": ["Under $50,000", "$100,000–$149,999", "$150,000–$199,999", "Prefer not to say", "$200,000 or more", "$50,000–$74,999"],
    "Q24": ["Yes", "No", "No", "I'm not sure", "No", "Yes"],
    "Q25": ["A few times a year", "Weekly or more", "Never", "About once a month", "2–3 times per month", "A few times a year"],
    "Q26": ["Yes", "No", "No", "Yes", "No", "No"],
    "Q30": ["Moderately interested"] * 6,
}
FALLBACK_CELLS = {("P001", "Q19")}
PERSONA_IDS = [f"P00{i}" for i in range(1, 7)]


def build_fake_run(run_dir: Path, *, run_id: str = "fake_run_r1", model: str = "stub/model-a", repeat: str = "1", seed: str = "7") -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    question_ids = [q[0] for q in FAKE_QUESTIONS]
    types = {q[0]: q[1] for q in FAKE_QUESTIONS}
    with open(run_dir / "questions.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["question_id", "question_type", "min_value", "max_value", "options", "text"])
        writer.writerows(FAKE_QUESTIONS)
    base = ["run_id", "model", "repeat", "seed", "persona_id", "respondent_id"]
    with open(run_dir / "answers_wide.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(base + question_ids + ["n_fallback", "all_live"])
        for index, pid in enumerate(PERSONA_IDS):
            fallbacks = sum(1 for qid in question_ids if (pid, qid) in FALLBACK_CELLS)
            writer.writerow([run_id, model, repeat, seed, pid, f"RESP_{index + 1:03d}"] + [FAKE_ANSWERS[qid][index] for qid in question_ids] + [fallbacks, "true" if not fallbacks else "false"])
    with open(run_dir / "answers_long.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(base + ["question_id", "question_type", "answer", "answer_json", "is_fallback"])
        for index, pid in enumerate(PERSONA_IDS):
            for qid in question_ids:
                answer = FAKE_ANSWERS[qid][index]
                payload = answer.split("|") if types[qid] == "multi_choice" else (int(answer) if types[qid] == "likert" else answer)
                writer.writerow([run_id, model, repeat, seed, pid, f"RESP_{index + 1:03d}", qid, types[qid], answer, json.dumps(payload, ensure_ascii=False), "true" if (pid, qid) in FALLBACK_CELLS else "false"])
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": run_id, "status": "completed", "model": {"requested": model}, "personas": {"path": "fake_personas.csv", "rows_used": 6}}, indent=2) + "\n", encoding="utf-8")
    return run_dir


@pytest.fixture
def fake_real_csv(tmp_path: Path) -> Path:
    return build_fake_real_csv(tmp_path / "real" / "fake-raw-data.csv")


@pytest.fixture
def fake_run_dir(tmp_path: Path) -> Path:
    return build_fake_run(tmp_path / "runs" / "fake_run_r1")


@pytest.fixture
def second_fake_run_dir(tmp_path: Path) -> Path:
    return build_fake_run(tmp_path / "runs" / "fake_run_r2", run_id="fake_run_r2", model="stub/model-b", repeat="2")

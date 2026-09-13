"""Declarative crosswalk from our 39 survey items to the AYTM export columns.

Our survey renumbers the AYTM questionnaire: our Q1 is the real Q6, our Q5_1..Q5_7 are the rows of
the real Q9 matrix, our Q15..Q17 are three of the five rows of the real Q30 matrix, and so on.
compare_real.py interprets this table; write_crosswalk_csv() renders it as crosswalk.csv.

    apps/api/.venv/bin/python research/neo_persona_set/phase3/crosswalk.py --questions <run_dir>/questions.csv --out crosswalk.csv
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

KINDS = ("likert", "single", "multi", "screener", "derived_binary", "age_bin", "income_band", "none")

_DASHES = re.compile("[‐‑‒–—―−]")
_SPACES = re.compile(r"\s+")
_TAGLINE = re.compile("\\s*\\(\\s*[\"“][^\"”]*[\"”]\\s*\\)\\s*$")
_CONCEPT = re.compile(r"^concept\s*(\d+)")
_NUMBER = re.compile(r"\d+")


def normalize_label(text: str) -> str:
    """Case-, dash-, quote-, whitespace- and trailing-period-insensitive form of a label."""
    plain = _DASHES.sub("-", str(text)).replace("’", "'").replace("“", '"').replace("”", '"')
    return _SPACES.sub(" ", plain).strip().casefold().rstrip(".").strip()


def strip_tagline(label: str) -> str:
    """'Concept 1: Backyard Home Office ("Work smarter ...")' -> 'Concept 1: Backyard Home Office'."""
    return _TAGLINE.sub("", str(label)).strip()


def normalize_concept(text: str) -> str:
    base = normalize_label(text)
    match = _CONCEPT.match(base)
    if match:
        return f"concept {int(match.group(1))}"
    if base.startswith("none of the above"):
        return "none of the above"
    return base


def normalize_other(text: str) -> str:
    base = normalize_label(text)
    return "other" if base.startswith("other") else base


NORMALIZERS: Dict[str, Callable[[str], str]] = {"default": normalize_label, "concept": normalize_concept, "other": normalize_other}


@dataclass
class Question:
    question_id: str
    question_type: str
    min_value: Optional[int]
    max_value: Optional[int]
    options: List[str]
    text: str


def _optional_int(raw: Optional[str]) -> Optional[int]:
    return int(raw) if raw is not None and raw.strip() else None


def load_questions(path: Path) -> Dict[str, Question]:
    """questions.csv of a run -> ordered {question_id: Question}."""
    questions: Dict[str, Question] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            questions[row["question_id"]] = Question(
                question_id=row["question_id"], question_type=row["question_type"],
                min_value=_optional_int(row.get("min_value")), max_value=_optional_int(row.get("max_value")),
                options=[option for option in (row.get("options") or "").split("|") if option], text=row.get("text") or "",
            )
    return questions


AGE_OPTIONS = ["18–24", "25–34", "35–44", "45–54", "55–64", "65 or older"]
INCOME_BANDS = ["Under $50,000", "$50,000-$74,999", "$75,000-$99,999", "$100,000-$199,999", "$200,000 or more"]
OUR_INCOME_TO_BAND: Dict[str, Optional[str]] = {
    "Under $50,000": "Under $50,000",
    "$50,000–$74,999": "$50,000-$74,999",
    "$75,000–$99,999": "$75,000-$99,999",
    "$100,000–$149,999": "$100,000-$199,999",
    "$150,000–$199,999": "$100,000-$199,999",
    "$200,000 or more": "$200,000 or more",
    "Prefer not to say": None,
}
REAL_INCOME_TO_BAND: Dict[str, str] = {
    "$0 - $24,999": "Under $50,000",
    "$25,000 - $49,999": "Under $50,000",
    "$50,000 - $74,999": "$50,000-$74,999",
    "$75,000 - $99,999": "$75,000-$99,999",
    "$100,000 - $199,999": "$100,000-$199,999",
    "$200,000 or more": "$200,000 or more",
}


def bucket_bounds(option: str) -> Optional[Tuple[float, float]]:
    text = normalize_label(option).replace(",", "").replace("$", "")
    numbers = [float(number) for number in _NUMBER.findall(text)]
    if not numbers:
        return None
    if len(numbers) >= 2:
        return min(numbers[:2]), max(numbers[:2])
    if any(word in text for word in ("under", "less than", "below")):
        return float("-inf"), numbers[0] - 1e-9
    return numbers[0], float("inf")


def age_bucket_for(age: Optional[int], options: Sequence[str] = AGE_OPTIONS) -> Optional[str]:
    if age is None:
        return None
    for option in options:
        bounds = bucket_bounds(option)
        if bounds and bounds[0] <= age <= bounds[1]:
            return option
    return None


@dataclass
class QuestionMap:
    our_id: str
    real_key: Optional[str]
    kind: str
    option_map: Dict[str, Optional[str]] = field(default_factory=dict)
    real_map: Dict[str, str] = field(default_factory=dict)
    normalizer: str = "default"
    scored: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"{self.our_id}: kind must be one of {KINDS}, got {self.kind!r}")
        if self.normalizer not in NORMALIZERS:
            raise ValueError(f"{self.our_id}: unknown normalizer {self.normalizer!r}")
        if (self.real_key is None) != (self.kind == "none"):
            raise ValueError(f"{self.our_id}: real_key must be None exactly when kind is 'none'")

    def map_our_label(self, label: str) -> Optional[str]:
        wanted = normalize_label(label)
        for ours, real in self.option_map.items():
            if normalize_label(ours) == wanted:
                return real
        return label

    def map_real_label(self, label: str) -> str:
        wanted = normalize_label(label)
        for real, category in self.real_map.items():
            if normalize_label(real) == wanted:
                return category
        return label

    def normalize(self, label: str) -> str:
        return NORMALIZERS[self.normalizer](label)


def real_base(real_key: Optional[str]) -> Optional[str]:
    return real_key.split("|", 1)[0] if real_key else None


CONCEPT_LABELS = [
    'Concept 1: Backyard Home Office ("Work smarter — right in your backyard")',
    'Concept 2: Guest Suite / STR Income ("Add space for guests — or extra income")',
    'Concept 3: Wellness / Studio Space ("Your personal studio — steps from your door")',
    'Concept 4: Adventure Lifestyle / Community ("Basecamp for your passions")',
    'Concept 5: Message-First ("Skip the stress of traditional building")',
]
Q14_OPTION_MAP: Dict[str, Optional[str]] = {label: strip_tagline(label) for label in CONCEPT_LABELS}
BARRIER_ROWS = [
    "The total cost (~$23,000)", "HOA restrictions or community rules", "Uncertainty about whether a building permit is required",
    "Limited backyard space or access", "Lack of financing options", "Concerns about build quality or durability", "Uncertainty about resale value",
]
CONCEPT_PAIRS = [("Q9", "Q15", "Q16"), ("Q10", "Q18", "Q19"), ("Q11", "Q21", "Q22"), ("Q12", "Q24", "Q25"), ("Q13", "Q27", "Q28")]


def _likert(our_id: str, real_key: str, notes: str) -> QuestionMap:
    return QuestionMap(our_id, real_key, "likert", notes=notes)


def _concept_maps() -> List[QuestionMap]:
    maps: List[QuestionMap] = []
    for index, (ours, appeal, purchase) in enumerate(CONCEPT_PAIRS, start=1):
        maps.append(_likert(f"{ours}A", appeal, f"Concept {index} appeal, 1-5."))
        maps.append(_likert(f"{ours}B", purchase, f"Concept {index} purchase likelihood, 1-5."))
    return maps


CROSSWALK: List[QuestionMap] = [
    QuestionMap("S3", "PQ1", "screener", option_map={"I'm not sure, but possibly": "I'm not sure, but possibly."},
                notes="Real respondents who answered No were terminated (none in the file); --require-outdoor-space drops our No personas to match."),
    QuestionMap("Q0A", "Q2", "single", notes="Prior consideration; 4 labels byte-identical."),
    _likert("Q0B", "Q3", "Category interest, 1-5."),
    _likert("Q1", "Q6", "Purchase interest at $23,000; note the numbering offset (our Q1 = real Q6)."),
    _likert("Q2", "Q7", "Purchase likelihood within 24 months, 1-5."),
    QuestionMap("Q3", "Q8", "single", option_map={"Other: ___________": "Other (please specify)"}, normalizer="other",
                notes="Primary use. Any label starting with 'Other' matches on both sides; the free text in Q8.OE is not compared."),
    *[_likert(f"Q5_{index}", f"Q9|{row}", f"Barrier severity matrix, row {index} of 7.") for index, row in enumerate(BARRIER_ROWS, start=1)],
    QuestionMap("Q6", "Q11", "single", notes="Single greatest barrier. Real has an extra 'Other (please specify)' option, reported as the real off-list share."),
    QuestionMap("Q7", None, "none", notes="Permit-light effect on likelihood: not asked in the AYTM survey."),
    *_concept_maps(),
    QuestionMap("Q14", "Q29", "single", option_map=Q14_OPTION_MAP, normalizer="concept",
                notes="Concept preference. Our labels carry a tagline that is stripped; labels match on the concept number (real names concept 5 'Simplicity', ours 'Message-First')."),
    _likert("Q15", "Q30|Permit-light positioning", "Value-driver matrix, row 1 of 5 (rows 4-5, Smart Technology and Showroom, have no synthetic counterpart)."),
    _likert("Q16", "Q30|Installation speed", "Value-driver matrix, row 2 of 5."),
    _likert("Q17", "Q30|Build quality and details", "Value-driver matrix, row 3 of 5."),
    QuestionMap("Q18", "Q31", "single", notes="Most persuasive driver. Real also offers Smart Technology, Showroom and Other; real shares are renormalized on the 3 shared options and the off-list share is reported."),
    _likert("Q19", "Q32", "Sponsorship impact, 1 = Decrease a lot .. 5 = Increase a lot."),
    QuestionMap("Q20", "Q33", "multi", notes="Outreach channels. Real offers 12 options (max 3 picks), ours 6 (max 2). Compared on the share of respondents selecting each shared option; off-list = share of real picks outside the 6."),
    QuestionMap("Q21", "Age", "age_bin", notes="Real integer age binned into our six buckets."),
    QuestionMap("Q22", "Household Income", "income_band", option_map=OUR_INCOME_TO_BAND, real_map=REAL_INCOME_TO_BAND,
                notes="Both sides collapsed to five bands; our 100-149k and 150-199k merge; our 'Prefer not to say' has no real counterpart (synthetic off-list)."),
    QuestionMap("Q23", None, "none", notes="Work arrangement: not asked in the AYTM survey."),
    QuestionMap("Q24", "Q35", "single", notes="HOA status; Yes / No / I'm not sure."),
    QuestionMap("Q25", "Q36", "single", notes="Outdoor recreation frequency; 5 labels identical."),
    QuestionMap("Q26", "Q37", "derived_binary", real_map={"A14": "No"}, notes="Real is a multi-select of club types; any of A1..A13 selected = Yes, A14 = No."),
    QuestionMap("Q30", "Q12", "single", scored=False, notes="Attention check; degenerate (everyone should pick 'Moderately interested'). Reported, not scored."),
]

BY_OUR_ID: Dict[str, QuestionMap] = {qmap.our_id: qmap for qmap in CROSSWALK}
if len(BY_OUR_ID) != len(CROSSWALK):
    raise RuntimeError("duplicate our_id in CROSSWALK")


def mapped_real_bases() -> Set[str]:
    return {real_base(qmap.real_key) for qmap in CROSSWALK if qmap.real_key}


CROSSWALK_COLUMNS = ["our_id", "real_column", "match_type", "our_options", "real_options", "notes"]


def write_crosswalk_csv(path: Path, our_options: Optional[Dict[str, List[str]]] = None, real_options: Optional[Dict[str, List[str]]] = None) -> Path:
    ours = our_options or {}
    reals = real_options or {}
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(CROSSWALK_COLUMNS)
        for qmap in CROSSWALK:
            match_type = qmap.kind if qmap.scored else f"{qmap.kind} (report only)"
            writer.writerow([qmap.our_id, qmap.real_key or "", match_type, "|".join(ours.get(qmap.our_id, [])), "|".join(reals.get(qmap.our_id, [])), qmap.notes])
    return Path(path)


def our_options_from_questions(questions: Dict[str, Question]) -> Dict[str, List[str]]:
    """Option list per question; likert items are the numeric scale, since the labels are what the
    prompt shows but the numbers are what is compared."""
    options: Dict[str, List[str]] = {}
    for question_id, question in questions.items():
        if question.question_type == "likert":
            low, high = question.min_value or 1, question.max_value or 5
            options[question_id] = [str(value) for value in range(low, high + 1)]
        else:
            options[question_id] = list(question.options)
    return options


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", type=Path, default=None, help="a run's questions.csv, to fill the our_options column")
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    our_options = our_options_from_questions(load_questions(args.questions)) if args.questions else {}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_crosswalk_csv(args.out, our_options=our_options)
    print(f"wrote {args.out} ({len(CROSSWALK)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

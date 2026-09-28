from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional


PERSONA_SEED_PATH = Path(__file__).resolve().parents[2] / "seed_data" / "personas-B.csv"
EXPECTED_PERSONA_COUNT = 30


def _census_profile(row: Dict[str, str]) -> str:
    parts: List[str] = []

    exact_age = row.get("exact_age", "").strip()
    sex = row.get("sex", "").strip()
    if exact_age:
        parts.append(f"You are {exact_age}{f', {sex.lower()}' if sex else ''}")

    county = row.get("county", "").strip()
    if county:
        parts.append(f"You live in {county} County, California")

    direct_fields = (
        ("marital_status", "Your marital status is {}"),
        ("education", "Your education level is {}"),
        ("occupation", "You work as a {}"),
        ("hours_worked_per_week", "You work about {} hours a week"),
    )
    for key, template in direct_fields:
        value = row.get(key, "").strip()
        if value:
            parts.append(template.format(value))

    commute_mode = row.get("commute_mode", "").strip()
    commute_minutes = row.get("commute_minutes", "").strip()
    if commute_mode:
        commute_detail = f", about {commute_minutes} minutes each way" if commute_minutes else ""
        parts.append(f"You get to work by {commute_mode.lower()}{commute_detail}")

    household_size = row.get("household_size", "").strip()
    children = row.get("children_in_household", "").strip()
    if household_size:
        children_detail = ""
        if children and children != "0":
            children_detail = f", including {children} child{'ren' if children != '1' else ''}"
        parts.append(f"There are {household_size} people in your household{children_detail}")

    income = row.get("exact_household_income", "").strip()
    if income.isdigit():
        parts.append(f"Your household income is about ${int(income):,} a year")

    bedrooms = row.get("bedrooms", "").strip()
    year_built = row.get("year_built", "").strip()
    if bedrooms and bedrooms != "0":
        year_detail = f" and was built {year_built}" if year_built else ""
        parts.append(f"Your home has {bedrooms} bedrooms{year_detail}")
    elif year_built:
        parts.append(f"Your home was built {year_built}")

    housing_cost = row.get("housing_cost_pct_of_income", "").strip()
    if housing_cost:
        parts.append(f"Housing costs take about {housing_cost}% of your income")

    return f"{'. '.join(parts)}." if parts else ""


def _persona_profile(row: Dict[str, str]) -> dict:
    return {
        "persona_id": row.get("persona_id", "").strip(),
        "age_bucket": row.get("age_bucket", "").strip(),
        "income_bucket": row.get("income_bucket", "").strip(),
        "ownership": row.get("ownership", "").strip(),
        "home_type": row.get("home_type", "").strip(),
        "work_mode": row.get("work_mode", "").strip(),
        "fit_tier": row.get("fit_tier", "").strip(),
        "lifestyle_tags": [
            value.strip()
            for value in row.get("lifestyle_tags", "").split(";")
            if value.strip()
        ],
        "census_profile": _census_profile(row),
        "headline": row.get("headline", "").strip(),
    }


def load_persona_seed_rows(path: Optional[Path] = None) -> List[dict]:
    seed_path = path or PERSONA_SEED_PATH
    with seed_path.open(newline="", encoding="utf-8-sig") as handle:
        profiles = [_persona_profile(row) for row in csv.DictReader(handle)]

    if len(profiles) != EXPECTED_PERSONA_COUNT:
        raise ValueError(
            f"Persona seed must contain exactly {EXPECTED_PERSONA_COUNT} rows; found {len(profiles)}."
        )

    persona_ids = [profile["persona_id"] for profile in profiles]
    if any(not persona_id for persona_id in persona_ids) or len(set(persona_ids)) != len(persona_ids):
        raise ValueError("Persona seed must contain a unique, non-empty persona_id for every row.")

    return [
        {
            "persona_id": profile["persona_id"],
            "row_index": index,
            "profile_json": profile,
        }
        for index, profile in enumerate(profiles)
    ]


# --- persona cards: what a student sees when choosing who to recruit (Lin fix 1) ---

SOURCE_NOTE = (
    "Source-backed attributes come from one real household record in the Census Bureau's "
    "American Community Survey microdata (ACS PUMS, California). The name is invented. In a "
    "focus group the persona is also given an invented speaking manner and, once the concept "
    "is shown, an invented stance toward it. Anything the record does not cover is marked "
    "unknown: the persona may improvise it, and nothing it says is evidence about real customers."
)
UNKNOWN = "Unknown"


def card_attribute(key: str, label: str, value: str, source: str) -> dict:
    """source is "census" (from the ACS record), "fictional" (invented), or "unknown"."""
    value = (value or "").strip()
    return {"key": key, "label": label, "value": value or UNKNOWN,
            "source": source if value else "unknown"}


def screener(tenure: str, outdoor: str, willing: str, tenure_source: str, other_source: str) -> List[dict]:
    """The PA3.5 screener — homeowner/landowner, usable outdoor space, open to more space —
    answered only as far as the profile actually says."""
    def verdict(criterion, meets, why_meets, why_not, why_unknown, source):
        if meets is None:
            return {"criterion": criterion, "verdict": "unknown", "why": why_unknown, "source": "unknown"}
        return {"criterion": criterion, "verdict": "meets" if meets else "does_not_meet",
                "why": why_meets if meets else why_not, "source": source}

    lowered = tenure.lower()
    owns = True if lowered.startswith("own") else False if lowered.startswith("rent") else None
    has_space = {"yes": True, "no": False}.get(outdoor)
    open_to = {"yes": True, "maybe": True, "no": False}.get(willing)
    return [
        verdict("Homeowner or landowner", owns, f"Tenure: {tenure}.", f"Tenure: {tenure}.",
                "Tenure is not recorded.", tenure_source),
        verdict("Has usable outdoor space", has_space, "Profile says yes.", "Profile says no.",
                "Not recorded. A detached home often has a yard, but that is an assumption to check "
                "with a screener question, not a fact.", other_source),
        verdict("Open to adding living or work space", open_to, "Profile says open to it.",
                "Profile says not interested.",
                "Not recorded — this is exactly what a screener question has to ask.", other_source),
    ]


def persona_card(row: Dict[str, str]) -> dict:
    get = lambda key: (row.get(key) or "").strip()  # noqa: E731
    size, children = get("household_size"), get("children_in_household")
    household = ", ".join(part for part in (
        get("household_type"),
        f"{size} {'person' if size == '1' else 'people'}" if size else "",
        f"{children} child{'ren' if children != '1' else ''}" if children and children != "0" else "",
    ) if part)
    income = get("exact_household_income")
    commute = get("commute_mode")
    work = "; ".join(part for part in (
        get("occupation"), get("employment_status"),
        f"{get('hours_worked_per_week')} hours/week" if get("hours_worked_per_week") else "",
        f"commutes by {commute.lower()}, {get('commute_minutes')} min" if commute else "",
    ) if part)
    home = ", ".join(part for part in (
        get("home_type"), f"{get('bedrooms')} bedrooms" if get("bedrooms") not in ("", "0") else "",
        f"{get('rooms')} rooms" if get("rooms") else "", f"built {get('year_built')}" if get("year_built") else "",
    ) if part)
    tenure = get("tenure_detail") or get("ownership")
    return {
        "persona_id": get("persona_id"),
        "name": get("name"),
        "origin": "source_grounded_roster",
        "origin_label": "Roster persona grounded in one ACS household record",
        "attributes": [
            card_attribute("name", "Name", get("name"), "fictional"),
            card_attribute("household", "Household", household, "census"),
            card_attribute("tenure", "Homeowner or renter", tenure, "census"),
            card_attribute("outdoor_space", "Usable outdoor space", "", "unknown"),
            card_attribute("willing_more_space", "Willing to consider more living/work space", "", "unknown"),
            card_attribute("current_space_use", "How they use their space today", "", "unknown"),
            card_attribute("age", "Age", ", ".join(p for p in (get("exact_age"), get("sex").lower()) if p), "census"),
            card_attribute("county", "Lives in", f"{get('county')} County, California" if get("county") else "", "census"),
            card_attribute("home", "Home", home, "census"),
            card_attribute("moved_in", "Lived there", get("moved_in"), "census"),
            card_attribute("income", "Household income", f"${int(income):,} a year" if income.isdigit() else "", "census"),
            card_attribute("housing_cost", "Housing cost share of income",
                           f"{get('housing_cost_pct_of_income')}%" if get("housing_cost_pct_of_income") else "", "census"),
            card_attribute("work", "Work", work, "census"),
        ],
        "screener": screener(tenure, "", "", "census", "unknown"),
        "source_note": SOURCE_NOTE,
    }


@lru_cache(maxsize=1)
def persona_cards() -> Dict[str, dict]:
    """Cards read straight off the seed file. They are for the student's eyes only: the
    model still gets the profile_json description it always had."""
    with PERSONA_SEED_PATH.open(newline="", encoding="utf-8-sig") as handle:
        return {card["persona_id"]: card for card in map(persona_card, csv.DictReader(handle))}

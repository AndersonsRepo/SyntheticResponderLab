"""Phase 1, step 2 — have a language model write each persona's story.

Bias controls, in order of how much they actually do:

1. Race and Hispanic origin were never downloaded. The pipeline cannot leak what it does not hold.
2. Names are assigned from a fixed pool by an independent random stream (see names.py), so a name
   cannot correlate with income, occupation, or county. Letting the model choose names produced
   exactly that correlation.
3. The model is told the name was randomly assigned and carries no information, and is forbidden
   from writing ethnicity, heritage, immigration status, religion, or accent.
4. audit_bias.py checks the finished stories for the correlations this is meant to prevent.

The story is a general life profile. It deliberately contains NO reaction to any product: these
personas will later answer a survey, and pre-writing their opinion would bias that answer and make
any comparison against the real respondents circular.

Runs against Claude or OpenRouter, whichever key is configured; see providers.py.

Usage:
    python phase1/write_stories.py --tag survey600
    python phase1/write_stories.py --tag survey600 --provider anthropic --workers 8
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import names as name_pool  # noqa: E402
import providers  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent / "out"
CACHE_DIR = OUT_DIR / "phase1_story_cache"
REPO_ROOT = HERE.parents[2]
LLM_CLIENT_PATH = REPO_ROOT / "apps/api/legacy_runtime/backend/simulation/llm_client.py"
API_ENV_PATH = REPO_ROOT / "apps/api/.env"

SYSTEM_PROMPT = """\
You write short, factual profiles of American households for a market-research panel.

You will be given a REAL household's record from US Census microdata. Write a believable person who
fits that record exactly.

ABSOLUTE RULES ON BIAS — these override everything else:
- The person's name was assigned at random from a fixed list. It tells you NOTHING about them.
  Never infer ethnicity, race, heritage, ancestry, immigration status, religion, language, or
  accent from the name, the county, the occupation, or the income.
- Write no ethnic, racial, cultural, religious, or national-origin characterisation of any kind.
  No "first-generation", no "traditional family values", no heritage foods, no bilingual notes,
  no cultural community references.
- This includes ACTIVITIES, not just labels. Do not write church attendance, services, worship,
  prayer, or any religious observance into a routine. The only exception is when the Census
  occupation itself is religious, such as Clergy, where the workplace is a reported fact.
- Do not mention religion in order to DENY it either. Writing "church is not part of their
  routine" still puts religion in the profile. Simply describe what the person does and leave
  religion out entirely, in both directions.
- Do not use income to imply sophistication, taste, intelligence, work ethic, or family structure.
  A lower-income household is not more chaotic and a higher-income one is not more refined.
- Describe what this person DOES, not what kind of person they supposedly are.

ACCURACY RULES:
- Never contradict the Census record. Household size, children, marital status, occupation,
  education, commute, and home details are facts, not suggestions.
- If the record says the person is not working, do not give them a job.
- Household income is for the WHOLE household and may include several earners. Do not assume the
  named person earns all of it.
- No statistics, no percentages, no market-research jargon.
- Do not mention any product, purchase, or buying intention. This is a life profile only.

DEPTH RULE:
These profiles are used to answer a survey later, so they need enough substance for the person to
respond consistently across many questions. Write concrete specifics — what is in the house, how
the days actually run, who is involved in decisions — rather than adjectives about character.
Describe PROCESS and HISTORY, never conclusions about what they would buy.

Return ONLY valid JSON with exactly these keys:
  "headline"            one neutral phrase under 70 characters describing their situation
  "biography"           4-5 sentences: work history, household, how they came to this home
  "daily_routine"       3-4 sentences on a typical weekday, start to end
  "weekend_routine"     2-3 sentences on a typical weekend
  "household_and_home"  3-4 sentences on the house: rooms, condition, who uses what
  "outdoor_space"       2-3 sentences on whatever outdoor area this home actually has and how
                        it is used now. If the structure is an apartment, mobile home, or boat,
                        do NOT invent a private yard — describe what such a home really has
                        (a balcony, shared grounds, a shared lot, or none).
  "home_projects"       2-3 sentences on maintenance and improvements done or postponed, and why
  "work_setup"          2-3 sentences on where and how they work, including any space at home
  "space_pressure"      2-3 sentences on which parts of the home feel tight and which do not
  "money_decisions"     3 sentences on HOW a large household purchase gets made: who is consulted,
                        how long they take, whether they research or finance. Never say what they
                        would decide about any particular thing.
  "priorities"          array of 4 short strings — what they are focused on over the next year
  "financial_picture"   3 sentences on how money works in this household
  "free_time"           2-3 sentences on what they do outside work
  "communication_style" 2 sentences on how this person talks: brief or expansive, blunt or hedging,
                        concrete or general. Used to keep their survey answers in a consistent voice.
"""


def load_llm_client():
    if not LLM_CLIENT_PATH.exists():
        raise SystemExit(f"LLM client not found at {LLM_CLIENT_PATH}")
    spec = importlib.util.spec_from_file_location("app_llm_client", LLM_CLIENT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _location(persona: dict) -> str:
    """Describe where the household lives without asserting a state it is not in.

    County is only resolvable for California PUMAs, so a national draw falls back to the state.
    Hardcoding "California" here would have put every matched persona in the wrong place.
    """
    county = persona.get("county")
    state = persona.get("state")
    if county and state:
        return f"{county} County, {state}"
    if county:
        return f"{county} County"
    return state or "United States"


def build_prompt(persona: dict) -> str:
    """Render the Census record. Only facts the household actually reported appear here."""
    lines = [
        "CENSUS RECORD (every line is real data about one household):",
        f"- Assigned name: {persona['name']}  (random, carries no information)",
        f"- Age: {persona['age']}",
        f"- Sex: {persona['sex']}",
        f"- Location: {_location(persona)}",
        f"- Marital status: {persona['marital_status']}",
        f"- Education: {persona['education']}",
        f"- Employment status: {persona['employment_status']}",
    ]
    if persona.get("occupation") and persona["occupation"] not in {"None", None}:
        lines.append(f"- Occupation: {persona['occupation']}")
    if persona.get("hours_worked_per_week"):
        lines.append(f"- Usual hours worked per week: {persona['hours_worked_per_week']}")
    if persona.get("commute_mode"):
        commute = persona["commute_mode"]
        if persona.get("commute_minutes"):
            commute += f", about {persona['commute_minutes']} minutes each way"
        lines.append(f"- Commute: {commute}")

    lines += [
        f"- Total household income: ${persona['household_income']:,} per year (all earners combined)",
        f"- Household size: {persona['household_size']} people",
        f"- Children in household: {persona['children_in_household']}",
        f"- Household type: {persona['household_type']}",
        # Structure type comes from the household's own BLD. It was hardcoded as detached, which
        # was fine while every draw screened for that, but in a matched draw the set contains
        # apartments and mobile homes and the prompt must not claim otherwise.
        f"- Home: {persona.get('home_type') or 'unknown structure type'}, "
        f"{persona['bedrooms']} bedrooms, {persona['rooms']} rooms",
        f"- Tenure: {persona['tenure']}",
        f"- Structure built: {persona['year_built']}",
        f"- Moved in: {persona['moved_in']}",
        f"- Vehicles: {persona['vehicles']}",
    ]
    if persona.get("housing_cost_pct_of_income") is not None:
        lines.append(
            f"- Housing costs take {persona['housing_cost_pct_of_income']}% of household income"
        )

    lines += [
        "",
        "Write this person as JSON now. Remember: no ethnic, racial, cultural, or religious",
        "characterisation, and no mention of any product or purchase.",
    ]
    return "\n".join(lines)


def parse_json_response(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.lstrip().lower().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in response: {text[:200]}")
    return json.loads(cleaned[start : end + 1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        default="auto",
        choices=["auto", "anthropic", "openrouter"],
        help="auto prefers Anthropic when ANTHROPIC_API_KEY is set.",
    )
    parser.add_argument("--model", default=None, help="Defaults to the provider's model.")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--name-seed", type=int, default=7_312_026)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--tag", default="mixed", help="Which drawn set to write stories for.")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent API calls.")
    parser.add_argument("--retries", type=int, default=5, help="Retries per persona on transient errors.")
    args = parser.parse_args()

    provider = providers.resolve(args.provider)
    model = args.model or providers.default_model(provider)
    client = providers.Generator(provider, model)
    print(f"Provider: {provider}  |  model: {model}")

    payload = json.loads((OUT_DIR / f"phase1_personas_{args.tag}.json").read_text())
    personas = payload["personas"]

    # Names first, from their own random stream, before the model sees anything.
    assigned = name_pool.assign_names([p.get("sex") for p in personas], args.name_seed)
    for persona, name in zip(personas, assigned):
        persona["name"] = name

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Writing {len(personas)} stories ({args.workers} workers)\n")

    lock = threading.Lock()
    done = {"n": 0, "generated": 0, "cached": 0, "failed": 0}

    def build_one(persona: dict) -> tuple[dict, str | None]:
        """Fetch or generate one story. Returns (persona, error) so one failure cannot
        abandon the other 599 — a partial set with a named failure list is far more useful
        than an exception halfway through a long run."""
        prompt = build_prompt(persona)
        digest = hashlib.sha256((model + prompt).encode()).hexdigest()[:16]
        cache_path = CACHE_DIR / f"{args.tag}_{persona['persona_id']}_{digest}.json"

        try:
            if cache_path.exists() and not args.force:
                persona["story"] = json.loads(cache_path.read_text())
                source = "cached"
            else:
                # Free tiers rate-limit, and a long run should not lose a persona to a transient
                # 429. Retry with exponential backoff plus jitter so workers do not resynchronise
                # and hammer the endpoint in lockstep. Credit exhaustion (402) is not transient,
                # so it is raised immediately rather than retried five times.
                last_error: Exception | None = None
                for attempt in range(args.retries):
                    try:
                        text = client.generate(
                            system_prompt=SYSTEM_PROMPT,
                            user_prompt=prompt,
                            temperature=args.temperature,
                            max_tokens=2400,
                        )
                        persona["story"] = parse_json_response(text)
                        break
                    except Exception as error:  # noqa: BLE001 - retried or re-raised below
                        if "402" in str(error):
                            raise
                        last_error = error
                        if attempt < args.retries - 1:
                            time.sleep(min(2 ** attempt, 30) + random.uniform(0, 3))
                else:
                    raise last_error  # type: ignore[misc]

                cache_path.write_text(json.dumps(persona["story"], indent=2))
                source = "generated"
        except Exception as error:  # noqa: BLE001 - reported per persona below
            with lock:
                done["n"] += 1
                done["failed"] += 1
            return persona, f"{type(error).__name__}: {error}"

        with lock:
            done["n"] += 1
            done[source] += 1
            if done["n"] % 25 == 0 or done["n"] == len(personas):
                print(
                    f"  {done['n']:>4}/{len(personas)}  "
                    f"generated {done['generated']}  cached {done['cached']}  failed {done['failed']}"
                )
        return persona, None

    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(build_one, p): p for p in personas}
        for future in as_completed(futures):
            persona, error = future.result()
            if error:
                failures.append((persona["persona_id"], error))

    if failures:
        print(f"\n  {len(failures)} failed:")
        for persona_id, error in failures[:10]:
            print(f"    {persona_id}  {error[:90]}")
        personas = [p for p in personas if p.get("story")]
        print(f"  continuing with the {len(personas)} that succeeded")

    payload["name_assignment"] = (
        "Names are drawn at random from a fixed pool, independent of every persona attribute "
        f"except sex (seed {args.name_seed}). They carry no information about the household."
    )
    payload["story_model"] = f"{provider}:{model}"
    payload["field_provenance"] = {
        "census_grounded": [
            "age", "sex", "county", "puma", "marital_status", "education", "occupation",
            "employment_status", "hours_worked_per_week", "commute_mode", "commute_minutes",
            "household_income", "household_size", "children_in_household", "household_type",
            "tenure", "home_type", "bedrooms", "rooms", "year_built", "moved_in", "vehicles",
            "housing_cost_pct_of_income",
        ],
        "randomly_assigned": ["name"],
        "llm_written": [
            "headline", "biography", "daily_routine", "household_and_home",
            "priorities", "financial_picture", "free_time",
        ],
    }

    out_path = OUT_DIR / f"phase1_personas_{args.tag}_full.json"
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"\nWrote {out_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

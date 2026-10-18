"""Prompt builders for live survey generation."""

from __future__ import annotations

import json
from typing import Any

from backend.schemas import AudienceFilter, BusinessProductContext, MarketContext, PersonaProfile, SurveySchema

# Sent only when at least one question carries a preamble, so surveys without one keep their prompt.
PREAMBLE_INSTRUCTION = (
	"A question's \"preamble\" is material the respondent read just before that question. "
	"Read it before answering; do not answer it."
)


def build_openrouter_prompt_payload(
	*,
	persona: PersonaProfile,
	survey_schema: SurveySchema,
	business_product_context: BusinessProductContext | None,
	market_context: MarketContext | None,
	audience_filter: AudienceFilter | None,
) -> dict[str, Any]:
	"""Build OpenRouter chat payload for one respondent persona."""
	survey_questions = []
	for question in survey_schema.questions:
		question_payload = {
			"id": question.id,
			"text": question.text,
			"question_type": question.question_type,
			"options": question.options,
			"min_value": question.min_value,
			"max_value": question.max_value,
			"required": question.required,
		}
		if question.preamble:
			question_payload["preamble"] = question.preamble
		survey_questions.append(question_payload)
	has_preamble = any("preamble" in q for q in survey_questions)

	context_bundle = {
		"persona_profile": persona.model_dump(),
		"audience_filter": audience_filter.model_dump() if audience_filter is not None else None,
		"business_product_context": business_product_context.model_dump() if business_product_context is not None else None,
		"market_context": market_context.model_dump() if market_context is not None else None,
		"survey": {
			"title": survey_schema.survey_title,
			"description": survey_schema.description,
			"questions": survey_questions,
		},
	}

	system_instruction = (
		"You are answering a survey as the given persona. "
		"Stay consistent with persona traits and provided business/market context. "
		"Return strict JSON only with no prose, no markdown, and no extra keys."
	)

	output_contract = {
		"answers": [
			{
				"question_id": "<question id>",
				"answer": "<answer value matching question type>",
			}
		]
	}

	preamble_note = f"{PREAMBLE_INSTRUCTION}\n\n" if has_preamble else ""
	user_instruction = (
		"Use the following context and produce survey answers.\n\n"
		f"CONTEXT_JSON:\n{json.dumps(context_bundle, ensure_ascii=False)}\n\n"
		f"{preamble_note}"
		"Output requirements:\n"
		"1) Return one answer per question id.\n"
		"2) For single_choice, answer must be one listed option exactly.\n"
		"3) For multi_choice, answer must be a JSON array of listed options.\n"
		"4) For likert/numeric, answer must be numeric and within min/max when provided.\n"
		"5) For open_text, answer must be a concise string.\n"
		"6) Return strict JSON only, matching this contract:\n"
		f"{json.dumps(output_contract, ensure_ascii=False)}"
	)

	return {
		"messages": [
			{"role": "system", "content": system_instruction},
			{"role": "user", "content": user_instruction},
		],
		"temperature": 0.2,
		"max_tokens": 1200,
	}

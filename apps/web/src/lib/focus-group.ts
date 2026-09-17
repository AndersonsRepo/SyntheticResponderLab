import type { InterviewModelCatalogEntry } from "./api";
import { isInterviewModelSelectable } from "./interview-models";

// Mirrors apps/api/src/services/focus_group.py. The student approves a number before
// anything is spent, so the number they see has to be the one the server bills
// against; a pytest pins these two copies together.
export const MIN_PERSONAS = 3;
export const MAX_PERSONAS = 8;
export const MAX_ROUNDS = 12;
export const ESTIMATED_PROMPT_TOKENS_PER_TURN = 2000;
export const ESTIMATED_COMPLETION_TOKENS_PER_TURN = 400;

export const FOCUS_GROUP_STAGES = [
  "icebreaker",
  "space_needs",
  "concept",
  "price_reactions",
  "close",
] as const;

export type FocusGroupStage = (typeof FOCUS_GROUP_STAGES)[number];

export const FOCUS_GROUP_STAGE_LABELS: Record<FocusGroupStage, string> = {
  icebreaker: "Icebreaker",
  space_needs: "General space needs",
  concept: "The Tahoe Mini concept",
  price_reactions: "Price reactions",
  close: "Close",
};

export type FocusGroupAnswer = {
  persona_id: string;
  text: string;
  status: "answered" | "missing";
  error: { code: string; message: string } | null;
};

export type FocusGroupRoom = {
  room_id: string;
  status: "running" | "completed" | "failed" | "budget_stopped" | "cancelled";
  revision: number;
  stage: FocusGroupStage;
  stages_reached: FocusGroupStage[];
  persona_ids: string[];
  model: string;
  max_rounds: number;
  estimated_cost_usd: string;
  complete: boolean;
  rounds: { index: number; stage: FocusGroupStage; question: string; answers: FocusGroupAnswer[] }[];
  memo: { themes: unknown[] | null } | null;
  session_usage: { cost_usd: string };
  error: { code: string; message: string; stage?: string; missing?: unknown[] } | null;
};

export type FocusGroupMemo = {
  room_id: string;
  revision: string;
  eligible: boolean;
  available: boolean;
  stale: boolean;
  message: string;
  answered_turns: number;
  estimated_cost_usd: string;
  model: string;
  saved: {
    attempt: number;
    message?: string;
    budget_stop?: string;
    themes:
      | {
          label: string;
          synthesis: string;
          quote: string;
          persona_id: string;
          sentiment: string;
          located_at: { persona_id: string; round: number; stage: FocusGroupStage; question: string };
        }[]
      | null;
    surprise?: { summary: string; quote: string; persona_id: string };
    // persona_id is optional on an answer option: the server validates it on themes and
    // the surprise but not here, so attribute from located_at, which it derives itself.
    answer_options?: {
      text: string;
      persona_id?: string;
      located_at: { persona_id: string; round: number; stage: FocusGroupStage; question: string };
    }[];
  } | null;
};

/** Personas times rounds, not one call — the whole room is what gets charged. */
export function estimateFocusGroupCost(
  personaCount: number,
  rounds: number,
  model: InterviewModelCatalogEntry | undefined
) {
  if (!model) return 0;
  const perTurn =
    (model.prompt_price_per_million * ESTIMATED_PROMPT_TOKENS_PER_TURN +
      model.completion_price_per_million * ESTIMATED_COMPLETION_TOKENS_PER_TURN) /
    1_000_000;
  return perTurn * personaCount * rounds;
}

export function formatFocusGroupCostEstimate(costUsd: number) {
  return `$${costUsd.toFixed(3)}`;
}

/** Why the start control is refusing, in the words the student should see. */
export function focusGroupSetupRefusal(setup: {
  personaIds: string[];
  rounds: number;
  model?: InterviewModelCatalogEntry;
  expensiveOptIn: boolean;
}): string | null {
  const unique = new Set(setup.personaIds);
  if (unique.size !== setup.personaIds.length) {
    return "Each persona can only take one seat in the room.";
  }
  if (setup.personaIds.length < MIN_PERSONAS) {
    return `A focus group needs at least ${MIN_PERSONAS} personas — with fewer than that you are running an interview, not a group.`;
  }
  if (setup.personaIds.length > MAX_PERSONAS) {
    return `A room holds at most ${MAX_PERSONAS} personas.`;
  }
  if (!Number.isInteger(setup.rounds) || setup.rounds < 1 || setup.rounds > MAX_ROUNDS) {
    return `Plan between 1 and ${MAX_ROUNDS} questions for the room.`;
  }
  if (!setup.model) {
    return "Choose a model from the curated catalog.";
  }
  // Persona count never unlocks an expensive model; only the checkbox does.
  if (!isInterviewModelSelectable(setup.model, setup.expensiveOptIn)) {
    return "Expensive models require the opt-in checkbox for this room.";
  }
  return null;
}

export function canStartFocusGroup(setup: Parameters<typeof focusGroupSetupRefusal>[0]) {
  return focusGroupSetupRefusal(setup) === null;
}

/** Stages reached so far, plus the next one. Nothing further: no skipping the funnel. */
export function selectableStages(room: Pick<FocusGroupRoom, "stages_reached"> | null) {
  const reached = room?.stages_reached ?? [];
  const furthest = reached.reduce(
    (max, stage) => Math.max(max, FOCUS_GROUP_STAGES.indexOf(stage)),
    -1
  );
  return FOCUS_GROUP_STAGES.slice(0, Math.min(furthest + 2, FOCUS_GROUP_STAGES.length));
}

export function canAskStage(room: Pick<FocusGroupRoom, "stages_reached"> | null, stage: FocusGroupStage) {
  return selectableStages(room).includes(stage);
}

/** Answers collected so far, whatever the room's status — going back never drops them. */
export function collectedAnswers(room: Pick<FocusGroupRoom, "rounds"> | null) {
  return (room?.rounds ?? []).flatMap((round) =>
    round.answers.filter((answer) => answer.status === "answered")
  );
}

export function missingAnswers(room: Pick<FocusGroupRoom, "rounds"> | null) {
  return (room?.rounds ?? []).flatMap((round) =>
    round.answers
      .filter((answer) => answer.status !== "answered")
      .map((answer) => ({ round: round.index, persona_id: answer.persona_id }))
  );
}

export function focusGroupPath(roomId?: string, suffix?: string) {
  const base = "focus-group/rooms";
  if (!roomId) return base;
  return suffix ? `${base}/${encodeURIComponent(roomId)}/${suffix}` : `${base}/${encodeURIComponent(roomId)}`;
}

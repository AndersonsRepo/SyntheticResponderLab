import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  addQuote,
  aiMemoRetryLabel,
  manualMemoFrom,
  quotableTurns,
  REHEARSAL_LABEL,
  type FocusGroupStage,
} from "../src/lib/focus-group";

const read = (path: string) => readFileSync(resolve(__dirname, "../..", path), "utf8");
const pageSource = read("src/app/focus-group/page.tsx");
const memoFormSource = read("src/components/focus-group/manual-memo-form.tsx");
const apiSource = readFileSync(resolve(__dirname, "../../../api/src/services/focus_group.py"), "utf8");

const ROOM = {
  rounds: [
    {
      index: 0,
      stage: "icebreaker" as FocusGroupStage,
      question: "q",
      answers: [
        { turn_id: "R1-P001", persona_id: "P001", text: "I use the garage.", status: "answered" as const, error: null },
        { turn_id: "R1-P002", persona_id: "P002", text: "", status: "missing" as const, error: null },
      ],
    },
  ],
};

// --- Fix 5 ------------------------------------------------------------------

test("rehearsal label: the page and the API carry the same words", () => {
  assert.equal(REHEARSAL_LABEL, "Synthetic rehearsal - not PA3.5 live fieldwork");
  assert.match(apiSource, /REHEARSAL_LABEL = "Synthetic rehearsal - not PA3\.5 live fieldwork"/);
  assert.match(pageSource, /\{REHEARSAL_LABEL\}/);
});

test("manual memo: a saved draft is restored, padded to three themes and three options", () => {
  const empty = manualMemoFrom(null);
  assert.equal(empty.themes.length, 3);
  assert.equal(empty.answer_options.length, 3);
  const restored = manualMemoFrom({
    themes: [{ label: "Cold garage", synthesis: "", quotes: [] }],
    surprise: { summary: "s", quote: { turn_id: "R1-P001", text: "garage" } },
    answer_options: [],
    moderation_improvement: "m",
  });
  assert.equal(restored.themes[0].label, "Cold garage");
  assert.equal(restored.themes.length, 3);
  assert.equal(restored.surprise.quote.turn_id, "R1-P001");
  // Re-opening a room and starting one both restore the saved draft.
  assert.equal((pageSource.match(/setManualMemo\(manualMemoFrom\(result\.room\.manual_memo\)\)/g) ?? []).length, 2);
});

test("manual memo: only answered turns are quotable, and a quote keeps its turn ID", () => {
  assert.deepEqual(quotableTurns(ROOM).map((t) => t.turn_id), ["R1-P001"]);
  const memo = addQuote(manualMemoFrom(null), "theme-1", quotableTurns(ROOM)[0]);
  assert.deepEqual(memo.themes[1].quotes, [{ turn_id: "R1-P001", text: "I use the garage." }]);
  assert.equal(addQuote(memo, "surprise", quotableTurns(ROOM)[0]).surprise.quote.turn_id, "R1-P001");
});

test("manual memo: the form comes before the optional AI draft and each turn shows its ID and a Quote control", () => {
  assert.ok(pageSource.indexOf("<ManualMemoForm") < pageSource.indexOf("Optional: AI draft memo"));
  assert.match(pageSource, /\[\{answer\.turn_id\}\]/);
  assert.match(pageSource, /aria-label=\{`Quote \$\{answer\.turn_id\} in your memo`\}/);
  assert.match(memoFormSource, /PA4 answer options/);
  assert.match(memoFormSource, /question topic/);
  assert.match(memoFormSource, /would change about how you moderated/);
  // Exporting saves the on-screen memo first, so typed work is never left out of the file.
  assert.match(pageSource, /postManualMemo\(\)\.then\(\(\) =>\s*interviewOperation/);
});

test("manual memo: a failed AI attempt's retry says it is a new charge and what the failure cost", () => {
  const label = aiMemoRetryLabel({
    estimated_cost_usd: "0.0021",
    saved: { attempt: 1, outcome: "charged", cost_usd: "0.002", themes: null },
  });
  assert.match(label, /new charge of about \$0\.002/);
  assert.match(label, /failed attempt was charged \$0\.0020/);
  assert.match(aiMemoRetryLabel({ estimated_cost_usd: "0.0021", saved: null }), /Confirm \$0\.002 and write it/);
});

// --- the classroom allowlist: every new student endpoint, nothing wider ---------

import { isClassroomInterviewApiRequest } from "../src/lib/classroom-access";

const ROOMS = "/api/backend/api/v1/studies/std_1/interview/focus-group/rooms";
const NEW_STUDENT_ENDPOINTS: [string, string][] = [
  ["POST", `${ROOMS}/fg_1/manual-memo`],
  ["POST", `${ROOMS}/fg_1/extend`],
];
const STILL_REFUSED: [string, string][] = [
  ["GET", `${ROOMS}/fg_1/manual-memo`],
  ["DELETE", `${ROOMS}/fg_1/manual-memo`],
  ["POST", `${ROOMS}/fg_1/manual-memo/extra`],
  ["POST", `${ROOMS}/fg_1/manual-memo%2F..%2F..`],
  ["POST", `${ROOMS}/fg_1/manual`],
  ["GET", `${ROOMS}/fg_1/extend`],
  ["POST", `${ROOMS}/fg_1/extend/more`],
];

test("classroom allowlist: every new student endpoint is reachable and nothing wider opened", () => {
  for (const [method, path] of NEW_STUDENT_ENDPOINTS) {
    assert.equal(isClassroomInterviewApiRequest(path, method), true, `${method} ${path}`);
  }
  for (const [method, path] of STILL_REFUSED) {
    assert.equal(isClassroomInterviewApiRequest(path, method), false, `${method} ${path}`);
  }
});

// --- Fix 2 ------------------------------------------------------------------

import { revealRefusal, sharedSummary } from "../src/lib/focus-group";

const conceptCardSource = read("src/components/focus-group/concept-card.tsx");

function roundAt(index: number, stage: FocusGroupStage, stimulus?: "concept" | "price") {
  return {
    index,
    stage,
    question: "q",
    ...(stimulus ? { stimulus: { kind: stimulus, text: `${stimulus} text` } } : {}),
    answers: [{ persona_id: "P001", text: "a", status: "answered" as const, error: null }],
  };
}

test("concept card: it sits directly above the question field and can be copied as text", () => {
  const card = pageSource.indexOf("<ConceptCardPanel");
  const input = pageSource.indexOf("value={question}");
  assert.ok(card > 0 && card < input, "the card renders before the question input");
  assert.equal(pageSource.slice(card, input).includes("<ol"), false, "nothing but the card sits between them");
  assert.match(conceptCardSource, /navigator\.clipboard\?\.writeText\(card\.text\)/);
  assert.match(conceptCardSource, /Introduction you read aloud \(edit freely\)/);
  assert.match(conceptCardSource, /card\.specs\.map/);
  // The page sends the reveal with the question; nothing is revealed on its own.
  assert.match(pageSource, /reveal: pendingReveal/);
});

test("concept card: Reveal price waits for the concept and an unaided price answer", () => {
  assert.match(String(revealRefusal({ rounds: [] }, "icebreaker", "concept")), /concept stage/);
  assert.equal(revealRefusal({ rounds: [] }, "concept", "concept"), null);
  const introduced = { rounds: [roundAt(0, "concept", "concept")] };
  assert.match(String(revealRefusal(introduced, "concept", "concept")), /already been shown/);
  assert.match(String(revealRefusal(introduced, "price_reactions", "price")), /unaided price question first/);
  const unaided = { rounds: [...introduced.rounds, roundAt(1, "price_reactions")] };
  assert.equal(revealRefusal(unaided, "price_reactions", "price"), null);
  assert.match(String(revealRefusal({ rounds: [roundAt(0, "price_reactions")] }, "price_reactions", "price")), /concept before/);
  assert.match(conceptCardSource, /disabled=\{busy \|\| priceRefusal !== null\}[\s\S]*?Reveal price/);
});

test("shared with participants: the panel lists each stimulus with its question, and what is withheld", () => {
  const none = sharedSummary({ rounds: [roundAt(0, "icebreaker")] });
  assert.deepEqual(none.shown, []);
  assert.deepEqual(none.withheld, ["Not shown yet: the concept card", "Not shown yet: the price"]);
  const some = sharedSummary({ rounds: [roundAt(0, "icebreaker"), roundAt(1, "concept", "concept")] });
  assert.equal(some.shown[0].line, "Before question 2 (The Tahoe Mini concept): the concept card");
  assert.equal(some.shown[0].text, "concept text");
  assert.deepEqual(some.withheld, ["Not shown yet: the price"]);
  assert.match(conceptCardSource, /Information shared with participants/);
});

// --- Fix 1 ------------------------------------------------------------------

import { CARD_SOURCE_LABELS, cardHeadline, type PersonaCard } from "../src/lib/focus-group";

const personaCardSource = read("src/components/focus-group/persona-card.tsx");
const CARD: PersonaCard = {
  persona_id: "P001",
  name: "Jorge Beltran",
  origin: "source_grounded_roster",
  origin_label: "Roster persona",
  attributes: [
    { key: "tenure", label: "Homeowner or renter", value: "Owned free and clear", source: "census" },
    { key: "outdoor_space", label: "Usable outdoor space", value: "Unknown", source: "unknown" },
  ],
  screener: [
    { criterion: "Homeowner or landowner", verdict: "meets", why: "Owned", source: "census" },
    { criterion: "Has usable outdoor space", verdict: "unknown", why: "Not recorded", source: "unknown" },
  ],
  source_note: "note",
};

test("persona card: recruitment shows an expandable card per persona, with each attribute's source", () => {
  assert.match(pageSource, /personas\.map\(\(persona\) => \([\s\S]*?Recruit \{persona\.persona_id\}[\s\S]*?<PersonaCardView\s+card=\{persona\.card\}/);
  assert.match(personaCardSource, /<details/);
  assert.match(personaCardSource, /CARD_SOURCE_LABELS\[attribute\.source\]/);
  assert.match(personaCardSource, /SCREENER_VERDICT_LABELS\[entry\.verdict\]/);
  assert.deepEqual(CARD_SOURCE_LABELS, { census: "Source-backed (ACS)", fictional: "Fictional", unknown: "Unknown" });
  assert.equal(cardHeadline(CARD), "P001 · Jorge Beltran — screener: 1 meet, 0 do not, 1 unknown");
  // The old ID-only chip is gone.
  assert.doesNotMatch(pageSource, /aria-pressed=\{selectedPersonaIds/);
});

test("persona card: the seated participants' cards stay beside the discussion", () => {
  assert.match(pageSource, /<aside aria-label="Who is in the room"[\s\S]*?room\.participants[\s\S]*?<PersonaCardView/);
});

// --- Fix 4 ------------------------------------------------------------------

import {
  allowanceLine,
  askRefusal,
  missingAnswers,
  nextStage,
  questionKind,
  unansweredNote,
} from "../src/lib/focus-group";

const ALLOWANCE = { total: 8, used: 3, cores_total: 5, cores_left: 3, probes_used: 1, probes_left: 2, extensions_left: 4 };

test("recipient selector: whole room or selected participants, silence is not an error", () => {
  assert.match(pageSource, /Whole room[\s\S]*?Selected participant\(s\)/);
  assert.match(pageSource, /recipients: target\.selected/);
  assert.match(String(askRefusal(null, "icebreaker", { mode: "selected", selected: [] })), /at least one participant/);
  assert.equal(askRefusal(null, "icebreaker", { mode: "selected", selected: ["P002"] }), null);
  const room = {
    rounds: [
      {
        index: 0,
        stage: "icebreaker" as FocusGroupStage,
        question: "q",
        recipients: ["P002"],
        answers: [
          { persona_id: "P001", text: "", status: "silent" as const, error: null },
          { persona_id: "P002", text: "a", status: "answered" as const, error: null },
        ],
      },
    ],
  };
  assert.deepEqual(missingAnswers(room), [], "silent is never a missing answer");
  assert.equal(unansweredNote({ status: "silent", error: null }), "not asked — intentionally silent");
  // Technical provider text never lands in the dialogue.
  assert.equal(unansweredNote({ status: "missing", error: { code: "provider_unavailable", message: "HTTP 502 upstream" } }), "no answer — retry below");
  assert.match(unansweredNote({ status: "missing", error: { code: "out_of_character", message: "x" } }), /out of character/);
  assert.doesNotMatch(pageSource, /answer\.error\?\.message/);
  assert.match(pageSource, /answer\.status !== "silent"/);
});

test("recipient selector: Ask follow-up and Next stage are separate, stage buttons stay, allowance shows", () => {
  const room = { rounds: [{ index: 0, stage: "icebreaker" as FocusGroupStage, question: "q", answers: [] }], allowance: ALLOWANCE };
  assert.equal(questionKind(room, "icebreaker"), "probe");
  assert.equal(questionKind(room, "space_needs"), "core");
  assert.equal(nextStage("price_reactions"), "close");
  assert.equal(nextStage("close"), null);
  assert.equal(allowanceLine(ALLOWANCE), "Core questions left: 3 of 5 · Follow-up probes left: 2 (used 1)");
  assert.match(String(askRefusal({ ...room, allowance: { ...ALLOWANCE, probes_left: 0 } }, "icebreaker", { mode: "room", selected: [] })), /extend the room/);
  assert.equal(askRefusal({ ...room, allowance: { ...ALLOWANCE, probes_left: 0 } }, "space_needs", { mode: "room", selected: [] }), null, "a core question is never blocked by probes");
  assert.match(pageSource, /"Ask follow-up"[\s\S]*?"Ask core question"/);
  assert.match(pageSource, /Next stage: \$\{FOCUS_GROUP_STAGE_LABELS\[nextStage\(stage\)!\]\} →/);
  assert.match(pageSource, /FOCUS_GROUP_STAGES\.map\(\(entry, index\) => \(/, "manual stage buttons remain");
  assert.match(pageSource, /\{allowanceLine\(room\.allowance\)\}/);
  assert.match(pageSource, /aria-label="Confirm extension cost"[\s\S]*?Confirm and extend/);
  assert.match(pageSource, /extra_rounds: extendBy,\s*authorize_charge: true/);
});

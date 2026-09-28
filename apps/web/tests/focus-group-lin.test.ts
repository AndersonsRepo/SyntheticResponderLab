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
const NEW_STUDENT_ENDPOINTS: [string, string][] = [["POST", `${ROOMS}/fg_1/manual-memo`]];
const STILL_REFUSED: [string, string][] = [
  ["GET", `${ROOMS}/fg_1/manual-memo`],
  ["DELETE", `${ROOMS}/fg_1/manual-memo`],
  ["POST", `${ROOMS}/fg_1/manual-memo/extra`],
  ["POST", `${ROOMS}/fg_1/manual-memo%2F..%2F..`],
  ["POST", `${ROOMS}/fg_1/manual`],
];

test("classroom allowlist: every new student endpoint is reachable and nothing wider opened", () => {
  for (const [method, path] of NEW_STUDENT_ENDPOINTS) {
    assert.equal(isClassroomInterviewApiRequest(path, method), true, `${method} ${path}`);
  }
  for (const [method, path] of STILL_REFUSED) {
    assert.equal(isClassroomInterviewApiRequest(path, method), false, `${method} ${path}`);
  }
});

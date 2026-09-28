import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  canSendAnswer,
  describeFailure,
  HUMAN_INTERVIEWEE_MODEL,
  HUMAN_RESPONDENT_LABEL,
  humanInterviewExport,
  isUnfinished,
  NEW_HUMAN_INTERVIEW,
  withQuestion,
  type HumanInterview,
  type HumanQuestion,
} from "../src/lib/human-interview";
import { InterviewOperationError } from "../src/lib/standalone-interview";
import { isClassroomInterviewApiRequest, isClassroomStudentPage } from "../src/lib/classroom-access";

const read = (path: string) => readFileSync(resolve(__dirname, "../..", path), "utf8");
const pageSource = read("src/app/interview/you/page.tsx");
const libSource = read("src/lib/human-interview.ts");
const interviewPageSource = read("src/app/interview/page.tsx");
const API = "/api/backend/api/v1/studies/study_abc/interview";

function reply(over: Partial<HumanQuestion> = {}): HumanQuestion {
  return {
    session_id: "you_1", question: "What would you use it for?", complete: false, turn_number: 1,
    turn_limit: 8, interviewer_model: "google/gemini-2.5-flash-lite", session_usage: { cost_usd: "0.001" }, ...over,
  };
}

const asked: HumanInterview = withQuestion(NEW_HUMAN_INTERVIEW, [], reply());

test("interview page links to AI interviews you", () => {
  assert.match(interviewPageSource, /href="\/interview\/you"[\s\S]{0,400}AI interviews you/);
  assert.match(pageSource, /<h1[^>]*>AI interviews you<\/h1>/);
});

test("classroom students reach the page and its one API call, nothing wider", () => {
  assert.equal(isClassroomStudentPage("/interview/you"), true);
  assert.equal(isClassroomInterviewApiRequest(`${API}/human/next-question`, "POST"), true);
  assert.equal(isClassroomInterviewApiRequest(`${API}/human/next-question`, "GET"), false);
  assert.equal(isClassroomInterviewApiRequest(`${API}/human/other`, "POST"), false);
  assert.equal(isClassroomInterviewApiRequest(`${API}/interviewer/next-question`, "POST"), false);
  assert.equal(isClassroomInterviewApiRequest(`${API}/human/next-question%2F..`, "POST"), false);
});

test("send guard: only a non-blank answer to the open question, once, before End", () => {
  assert.equal(canSendAnswer(NEW_HUMAN_INTERVIEW, "hello", false), false, "no question yet");
  assert.equal(canSendAnswer(asked, "", false), false, "empty");
  assert.equal(canSendAnswer(asked, "  \n\t", false), false, "whitespace");
  assert.equal(canSendAnswer(asked, "A studio", true), false, "a request is already in flight");
  assert.equal(canSendAnswer({ ...asked, ended: true }, "A studio", false), false, "ended");
  assert.equal(canSendAnswer(asked, "A studio", false), true);
  const answered = [...asked.messages, { role: "assistant" as const, content: "A studio" }];
  assert.equal(canSendAnswer({ ...asked, messages: answered }, "again", false), false, "already answered");
  assert.match(pageSource, /disabled=\{!canSendAnswer\(interview, answer, pending\)\}/);
  assert.match(pageSource, /if \(!canSendAnswer\(interview, answer, pending\)\) return;/);
});

test("end: a question that arrives after End is dropped and the transcript still exports", () => {
  const ended = { ...asked, ended: true };
  const late = withQuestion(ended, [...asked.messages, { role: "assistant", content: "A studio" }], reply({ question: "Late?" }));
  assert.equal(late, ended);
  assert.equal(isUnfinished(ended), false);
  const done = withQuestion(asked, [...asked.messages, { role: "assistant", content: "A studio" }],
    reply({ question: null, complete: true }));
  assert.equal(done.ended, true);
  assert.equal(done.messages.length, 2);
  assert.ok(humanInterviewExport(ended, "md").blob.size > 0);
  assert.match(pageSource, /End interview/);
});

test("export: the batch file format, respondent labelled human on every row, formula-safe", async () => {
  const interview = withQuestion(asked, [...asked.messages, { role: "assistant", content: "=HYPERLINK(\"x\")" }],
    reply({ question: "Why that?", session_usage: { cost_usd: "0.002" } }));
  const csv = humanInterviewExport(interview, "csv");
  assert.equal(csv.filename, "you_1.csv");
  const text = await csv.blob.text();
  const [header, ...rows] = text.split("\r\n");
  assert.equal(header, '"Persona","Interviewer model","Interviewee model","Turn","Role","Text"');
  assert.equal(rows.length, 3);
  for (const row of rows) assert.ok(row.startsWith(`"${HUMAN_RESPONDENT_LABEL}","google/gemini-2.5-flash-lite","${HUMAN_INTERVIEWEE_MODEL}"`));
  assert.match(rows[1], /"Answer","'=HYPERLINK\(""x""\)"$/);
  const md = await humanInterviewExport(interview, "md").blob.text();
  assert.match(md, /Measured cost: \$0\.002/);
  assert.equal(md.match(new RegExp(`## ${HUMAN_RESPONDENT_LABEL.replace(/[()]/g, "\\$&")} — Turn`, "g"))?.length, 3);
  assert.match(md, new RegExp(`Interviewee: ${HUMAN_INTERVIEWEE_MODEL}`));
});

test("errors: budget stop ends the interview, a server or network failure keeps the answer", () => {
  const budget = describeFailure(new InterviewOperationError("Budget hard stop: the run has spent $0.50.", 429));
  assert.equal(budget.ends, true);
  assert.match(budget.message, /Budget hard stop[\s\S]*you can still export it/);
  const down = describeFailure(new InterviewOperationError("The AI interviewer did not answer. Your answer is kept; send it again to retry.", 503));
  assert.deepEqual(down, { message: "The AI interviewer did not answer. Your answer is kept; send it again to retry.", ends: false });
  assert.equal(describeFailure(new TypeError("Failed to fetch")).ends, false);
  assert.match(describeFailure(new SyntaxError("Unexpected token <")).message, /Your answer is kept/);
  // The answer box is only cleared on success, and only if it still holds what was sent.
  assert.match(pageSource, /setAnswer\(\(current\) => \(current === sentAnswer \? "" : current\)\)/);
  assert.match(pageSource, /if \(ends\) setInterview/);
  assert.match(pageSource, /role="alert"[^>]*>\{error\}/);
});

test("refresh: an unfinished interview warns before the page unloads", () => {
  assert.equal(isUnfinished(NEW_HUMAN_INTERVIEW), false);
  assert.equal(isUnfinished(asked), true);
  assert.match(pageSource, /addEventListener\("beforeunload", warn\)/);
  assert.match(pageSource, /if \(!unfinished\) return;/);
});

test("human data: answers go only to the next-question call", () => {
  for (const source of [pageSource, libSource]) {
    assert.doesNotMatch(source, /localStorage|sessionStorage|indexedDB|document\.cookie/);
    assert.doesNotMatch(source, /getInterviewTranscriptExport|interview\/export|sendBeacon|fetch\(/);
  }
  assert.deepEqual(libSource.match(/interviewOperation</g), ["interviewOperation<"]);
  assert.match(libSource, /"human\/next-question"/);
});

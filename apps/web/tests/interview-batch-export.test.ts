import test from "node:test";
import assert from "node:assert/strict";

import { batchExport, memoMarkdown, studentMemoMarkdown } from "../src/lib/interview-batch-export";

test("the markdown export carries the memo, not just the transcript", () => {
  // A transcript alone is not what PA3.5 asks a student to hand in.
  const memo = {
    themes: [{ label: "Quiet space", synthesis: "They want somewhere quiet.",
      representative_quote: "I need somewhere quiet", quote_persona_id: "P001", sentiment: "positive" }],
    surprise: { summary: "Noise beat price.", quote: "the noise matters more", quote_persona_id: "P002" },
    answer_options: [
      { text: "somewhere quiet to think", quote_persona_id: "P001" },
      { text: "a door I can close", quote_persona_id: "P002" },
      { text: "space away from the house", quote_persona_id: "P003" },
    ],
  };
  const withMemo = memoMarkdown(memo);
  assert.match(withMemo, /## Themes/);
  assert.match(withMemo, /## One surprise/);
  assert.match(withMemo, /Noise beat price\./);
  assert.match(withMemo, /a door I can close — P002/);
  assert.match(withMemo, /Closed-ended answer options/);

  // No memo yet is a transcript-only export, not a heading with nothing under it.
  assert.equal(memoMarkdown(null), "");
  assert.equal(memoMarkdown({ themes: [] }), "");
  // A rejected extraction saves themes: null. Its surprise is evidence for a memo
  // that does not exist, so nothing from it reaches the handed-in file.
  assert.equal(memoMarkdown({ themes: null, surprise: {
    summary: "s", quote: "q", quote_persona_id: "neo-001",
  }, answer_options: [{ text: "an option", quote_persona_id: "neo-001" }] }), "");

  // And it has to actually reach the downloaded file — testing the helper alone lets
  // someone drop the call from batchExport with nothing failing.
  const batch = {
    job_id: "batch_1", status: "completed", persona_count: 1, turn_limit: 1,
    completed_personas: 1, interviewer_model: "a", interviewee_model: "b",
    estimated_cost_usd: "0.01", session_usage: { cost_usd: "0.01" },
    transcripts: [{ persona_id: "P001", messages: [
      { role: "user" as const, content: "Why?" },
      { role: "assistant" as const, content: "I need somewhere quiet" },
    ] }],
  } as unknown as Parameters<typeof batchExport>[0];
  const mine = { themes: "People want quiet.", surprise: "Noise beat price for everyone.",
    options: ["somewhere quiet to think", "", "a door I can close"] };
  return batchExport(batch, "md", memo, mine).blob.text().then((md) => {
    // The student's own memo is the submission; ours is labelled as the reference.
    assert.match(md, /# Memo\n\n## Themes\n\nPeople want quiet\./);
    assert.match(md, /# AI reference — not the memo you hand in/);
    assert.equal(md.indexOf("# Memo") < md.indexOf("# AI reference"), true);
    assert.match(md, /Noise beat price\./);
    assert.match(md, /a door I can close — P002/);
    // An option left blank is not an option; it must not become an empty bullet.
    assert.doesNotMatch(md, /^- $/m);
  });
  // The no-memo case is covered where it belongs, in interview-batch-controls.test.ts.
});


test("an untouched memo form adds nothing to the download", () => {
  // A student who has written nothing yet gets a transcript, not empty headings.
  assert.equal(studentMemoMarkdown(null), "");
  assert.equal(studentMemoMarkdown({ themes: "", surprise: "", options: ["", "", ""] }), "");
  assert.match(studentMemoMarkdown({ themes: "", surprise: "", options: ["  a real option  "] }),
    /- a real option/);
});

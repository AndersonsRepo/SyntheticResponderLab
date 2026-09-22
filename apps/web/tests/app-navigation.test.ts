import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  canOpenCompactAppMenu,
  standaloneAppLinks,
} from "../src/lib/app-navigation";
import { workflowSections } from "../src/lib/workflow-sections";

test("student interview and focus group are standalone app destinations outside the study workflow", () => {
  assert.deepEqual(standaloneAppLinks, [
    { href: "/interview", label: "Student Interview" },
    { href: "/focus-group", label: "Focus Group" },
  ]);
  for (const id of ["interview", "focus-group"]) {
    assert.equal(
      workflowSections.some((section) => section.id === (id as string)),
      false
    );
  }
});

test("compact app menu remains openable for standalone destinations during a workflow lock", () => {
  assert.equal(canOpenCompactAppMenu(true, standaloneAppLinks.length), true);
  assert.equal(canOpenCompactAppMenu(true, 0), false);
});

test("the desktop nav sizes its track to what it holds, not to the viewport", () => {
  // The track lives inside an overflow-x-auto nav. `w-full` there means 100% of the
  // VISIBLE width, so once the tabs overflow, the bordered pill stops at the viewport
  // edge while the last tabs sit outside it — Focus Group rendered detached from the
  // nav it belongs to. `w-max min-w-full` grows with the content and still fills the
  // bar when the tabs are narrower than it.
  const nav = readFileSync(
    resolve(__dirname, "../../src/components/ui/workflow-nav.tsx"),
    "utf8"
  );
  const track = nav.split("\n").find((line) => line.includes("rounded-[1.5rem] border"));
  assert.ok(track, "desktop nav track not found");
  // A hyphen is a word boundary, so \bw-full\b also matches inside min-w-full.
  assert.doesNotMatch(track!, /(?<![\w-])w-full\b/);
  assert.match(track!, /\bw-max min-w-full\b/);
});

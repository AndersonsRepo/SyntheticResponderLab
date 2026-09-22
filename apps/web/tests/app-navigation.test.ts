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

test("the landing page offers the student a way in, and never two buttons to one place", () => {
  // Both CTAs used to point at /sign-in, so "Accept invite" only made a student wonder
  // which one was theirs. With classroom mode on, the way in has to be on the page they
  // actually land on — the classroom cookie is only set once they reach /interview.
  const shell = readFileSync(
    resolve(__dirname, "../../src/components/ui/public-landing-shell.tsx"),
    "utf8"
  );
  // Match the rendered label on its own line, so the comment explaining the removal
  // does not keep the test green or red by accident.
  assert.doesNotMatch(shell, /^\s*Accept invite\s*$/m);
  // Both the hero CTA and the top nav must reach it; one alone leaves a student
  // scrolling past a log-in wall on the page they were handed.
  assert.equal(shell.match(/href="\/interview"/g)?.length, 2);
  assert.match(shell, /Start as a student/);
  assert.match(shell, /classroomNoLogin/);

  const home = readFileSync(resolve(__dirname, "../../src/app/page.tsx"), "utf8");
  assert.match(home, /classroomNoLogin=\{isClassroomNoLoginEnabled\(\)\}/);
});

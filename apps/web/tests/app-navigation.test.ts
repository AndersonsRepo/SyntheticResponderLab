import test from "node:test";
import assert from "node:assert/strict";

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

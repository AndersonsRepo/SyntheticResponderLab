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

test("the desktop nav sizes its track to what it holds, not to a fixed column count", () => {
  // A fixed grid-cols-N fits only N children: the standalone links are siblings of the
  // workflow tabs, so any extra child wraps into a second row that the nav's own
  // overflow-hidden clips, silently removing those destinations at desktop widths.
  const nav = readFileSync(
    resolve(__dirname, "../../src/components/ui/workflow-nav.tsx"),
    "utf8"
  );
  const track = nav.split("\n").find((line) => line.includes("grid w-full"));
  assert.ok(track, "desktop nav track not found");
  assert.doesNotMatch(track!, /grid-cols-\d+/);
  assert.match(track!, /grid-flow-col auto-cols-fr/);
});

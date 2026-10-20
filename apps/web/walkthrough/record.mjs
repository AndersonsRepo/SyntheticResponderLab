#!/usr/bin/env node
/**
 * Records the narrated walkthrough of the app: one browser session, one chapter per entry in script.json.
 *
 *   BUILD_DIR=/path/outside/the/repo MODE=quick node record.mjs   # selector pass: one screenshot per chapter
 *   BUILD_DIR=/path/outside/the/repo MODE=full  node record.mjs   # screencast frames + marks.json for compose.sh
 *
 * Environment:
 *   BUILD_DIR        required; outputs go to $BUILD_DIR/selector_pass (quick) or $BUILD_DIR/$VERSION (full)
 *   MODE             quick | full (default quick)
 *   VERSION          output folder name for a full run (default v1)
 *   BASE_URL         the running web app (default http://127.0.0.1:3010)
 *   PLAYWRIGHT_MODULE path to a playwright package when `playwright` is not resolvable from here
 *   ONLY             quick mode only: comma-separated steps to screenshot (all chapters still run)
 *
 * The app must run locally with every provider key blank. The recording turns the Demo (no AI) switch on in the
 * first chapter and only uses the preloaded demo and the seeded/pre-recorded interview screens.
 * Full mode needs $BUILD_DIR/audio/durations.json from tts.sh: each chapter holds until its narration ends + 0.6 s.
 * A chapter listed in LEADS starts its page change (a click that loads another route) a moment before its mark, so
 * the new page is already on screen when its narration begins.
 */
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

const BUILD_DIR = process.env.BUILD_DIR;
if (!BUILD_DIR) {
  console.error("record.mjs: set BUILD_DIR to a folder outside the repository");
  process.exit(2);
}
const MODE = (process.env.MODE || "quick").toLowerCase();
const QUICK = MODE !== "full";
const VERSION = process.env.VERSION || "v1";
const BASE_URL = (process.env.BASE_URL || "http://127.0.0.1:3010").replace(/\/$/, "");
const ONLY = new Set((process.env.ONLY || "").split(",").map((s) => s.trim()).filter(Boolean));
const OUT_DIR = QUICK ? path.join(BUILD_DIR, "selector_pass") : path.join(BUILD_DIR, VERSION);
const FRAMES_DIR = path.join(OUT_DIR, "frames");
const GAP_AFTER_NARRATION = 0.6;
const VIEWPORT = { width: 1280, height: 800 };

const script = JSON.parse(fs.readFileSync(path.join(HERE, "script.json"), "utf8"));
const durations = QUICK ? {} : JSON.parse(fs.readFileSync(path.join(BUILD_DIR, "audio", "durations.json"), "utf8"));

function loadPlaywright() {
  const candidates = ["playwright", process.env.PLAYWRIGHT_MODULE].filter(Boolean);
  for (const id of candidates) {
    try {
      return require(id);
    } catch {
      /* try the next one */
    }
  }
  console.error("record.mjs: playwright not found. Run `npm install` in apps/web/walkthrough, or set PLAYWRIGHT_MODULE.");
  process.exit(2);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)));
const now = () => Date.now() / 1000;

/* ------------------------------------------------------------------------------------------------------------ */
/* In-page overlay: a visible cursor that follows real mouse events, a click ring, and a target highlight.       */
/* It is appended after hydration (and re-appended if React ever replaces the node), so it never causes a        */
/* hydration mismatch. It also hides the Next.js dev indicator (nextjs-portal).                                  */
/* ------------------------------------------------------------------------------------------------------------ */
const OVERLAY_INIT = () => {
  const CURSOR_SVG =
    '<svg width="26" height="26" viewBox="0 0 26 26" xmlns="http://www.w3.org/2000/svg">' +
    '<path d="M3 2 L3 20 L8 15.5 L11.5 23 L14.6 21.6 L11.2 14.3 L18 14.3 Z" fill="#111827" stroke="#ffffff" ' +
    'stroke-width="1.6" stroke-linejoin="round"/></svg>';
  // The floating Next/More arrow is hidden: it sits over the middle of the page and covers words on camera.
  // Smooth scrolling set in CSS is turned off: the app's own scrollTo(0, 0) on arriving home would otherwise
  // animate through every section. Scrolls the walkthrough means to show are animated here, frame by frame.
  const CSS = `
    nextjs-portal { display: none !important; }
    html { scroll-behavior: auto !important; }
    button[aria-label="Go to the next section"], button[aria-label="Continue through this section"] {
      display: none !important; }
    #__wt_cursor { position: fixed; left: 0; top: 0; width: 26px; height: 26px; z-index: 2147483647;
      pointer-events: none; will-change: transform; filter: drop-shadow(0 2px 3px rgba(0,0,0,.35)); }
    .__wt_ring { position: fixed; z-index: 2147483646; pointer-events: none; width: 18px; height: 18px;
      margin: -9px 0 0 -9px; border-radius: 50%; border: 3px solid rgba(234, 140, 30, .95);
      animation: __wt_ring .6s ease-out forwards; }
    @keyframes __wt_ring { from { transform: scale(.6); opacity: 1; } to { transform: scale(3.4); opacity: 0; } }
    .__wt_hl { position: fixed; z-index: 2147483645; pointer-events: none; border-radius: 14px;
      box-shadow: 0 0 0 3px rgba(234, 140, 30, .9), 0 0 22px 4px rgba(234, 140, 30, .35);
      opacity: 0; transition: opacity .25s ease; }`;
  const state = (window.__wtState = window.__wtState || { x: -100, y: -100 });
  const ensure = (pos) => {
    if (pos && typeof pos.x === "number") {
      state.x = pos.x;
      state.y = pos.y;
    }
    if (!document.body) return;
    if (!document.getElementById("__wt_style")) {
      const style = document.createElement("style");
      style.id = "__wt_style";
      style.textContent = CSS;
      document.documentElement.appendChild(style);
    }
    let cursor = document.getElementById("__wt_cursor");
    if (!cursor) {
      cursor = document.createElement("div");
      cursor.id = "__wt_cursor";
      cursor.innerHTML = CURSOR_SVG;
      document.documentElement.appendChild(cursor);
    }
    cursor.style.transform = `translate(${state.x - 3}px, ${state.y - 2}px)`;
  };
  const move = (x, y) => {
    state.x = x;
    state.y = y;
    const cursor = document.getElementById("__wt_cursor");
    if (cursor) cursor.style.transform = `translate(${x - 3}px, ${y - 2}px)`;
  };
  const ripple = (x, y) => {
    const ring = document.createElement("div");
    ring.className = "__wt_ring";
    ring.style.left = `${x}px`;
    ring.style.top = `${y}px`;
    document.documentElement.appendChild(ring);
    setTimeout(() => ring.remove(), 700);
  };
  const highlight = (rect, ms) => {
    const box = document.createElement("div");
    box.className = "__wt_hl";
    const pad = 6;
    Object.assign(box.style, {
      left: `${rect.x - pad}px`,
      top: `${rect.y - pad}px`,
      width: `${rect.width + pad * 2}px`,
      height: `${rect.height + pad * 2}px`,
    });
    document.documentElement.appendChild(box);
    requestAnimationFrame(() => (box.style.opacity = "1"));
    setTimeout(() => (box.style.opacity = "0"), ms || 700);
    setTimeout(() => box.remove(), (ms || 700) + 400);
  };
  window.__wt = { ensure, move, ripple, highlight };
  window.addEventListener("mousemove", (event) => move(event.clientX, event.clientY), true);
  window.addEventListener("mousedown", (event) => ripple(event.clientX, event.clientY), true);
  const boot = () => {
    ensure();
    setInterval(() => ensure(), 400);
  };
  if (document.readyState === "complete") setTimeout(boot, 300);
  else window.addEventListener("load", () => setTimeout(boot, 300));
};

/* ------------------------------------------------------------------------------------------------------------ */
/* Director: human-paced cursor moves, highlights, clicks, typing and smooth scrolling.                          */
/* ------------------------------------------------------------------------------------------------------------ */
class Director {
  constructor(page, { quick }) {
    this.page = page;
    this.quick = quick;
    this.pos = { x: 760, y: 470 };
    this.t0 = null;
    this.marks = [];
    this.current = null;
  }

  async overlay() {
    await this.page.evaluate((pos) => window.__wt && window.__wt.ensure(pos), this.pos).catch(() => {});
  }

  /** Seconds since the recording began. */
  elapsed() {
    return now() - this.t0;
  }

  mark(step) {
    const t = this.elapsed();
    this.current = { step, t, dur: durations[step] ?? 0 };
    this.marks.push(this.current);
    return this.current;
  }

  /** Waits until `fraction` of the current chapter's narration has been spoken (full mode only). */
  async narration(fraction) {
    if (this.quick || !this.current) return;
    await sleep((this.current.t + this.current.dur * fraction - this.elapsed()) * 1000);
  }

  /** Quick mode only: an extra screenshot in the middle of a chapter (selector_pass/NN_step_name.png). */
  async snap(name) {
    if (!this.quick || !this.snapPrefix) return;
    await this.overlay();
    await this.page.screenshot({ path: `${this.snapPrefix}_${name}.png` });
  }

  async pause(ms) {
    await sleep(this.quick ? Math.min(ms, 150) : ms);
  }

  async moveTo(x, y, ms) {
    const from = { ...this.pos };
    const dist = Math.hypot(x - from.x, y - from.y);
    if (this.quick || dist < 2) {
      await this.page.mouse.move(x, y);
      this.pos = { x, y };
      return;
    }
    const duration = ms ?? Math.min(950, Math.max(320, dist * 0.85));
    // ~30 moves per second: each move is a round trip to the browser, so finer steps only slow the cursor down.
    const steps = Math.max(8, Math.round(duration / 33));
    // A gentle arc instead of a ruler-straight line.
    const bend = Math.min(70, dist * 0.12) * (x > from.x ? 1 : -1);
    const cx = (from.x + x) / 2 + (-(y - from.y) / dist) * bend;
    const cy = (from.y + y) / 2 + ((x - from.x) / dist) * bend;
    const start = Date.now();
    for (let i = 1; i <= steps; i += 1) {
      const t = i / steps;
      const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      const px = (1 - e) * (1 - e) * from.x + 2 * (1 - e) * e * cx + e * e * x;
      const py = (1 - e) * (1 - e) * from.y + 2 * (1 - e) * e * cy + e * e * y;
      await this.page.mouse.move(px, py);
      await sleep(start + duration * t - Date.now());
    }
    this.pos = { x, y };
  }

  /** Smoothly scrolls the element's scroll container (a section, or the window) until the element is in view. */
  async reveal(locator, { block = 0.3, duration } = {}) {
    await locator.waitFor({ state: "visible", timeout: 30000 });
    const ms = this.quick ? 0 : duration ?? 900;
    await locator.evaluate(
      (el, { block, ms }) =>
        new Promise((resolve) => {
          const scrollable = (node) => {
            const style = getComputedStyle(node);
            return /(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 2;
          };
          let box = el.parentElement;
          while (box && box !== document.body && !scrollable(box)) box = box.parentElement;
          const useWindow = !box || box === document.body;
          const scroller = useWindow ? document.scrollingElement : box;
          const chrome = Array.from(document.querySelectorAll("header"))
            .map((h) => h.getBoundingClientRect())
            .filter((r) => r.height > 0)
            .reduce((max, r) => Math.max(max, r.bottom), 0);
          const area = useWindow ? { top: 0, bottom: innerHeight } : box.getBoundingClientRect();
          const top = Math.max(area.top, chrome);
          const bottom = Math.min(area.bottom, innerHeight) - 96; // keep clear of the floating Next arrow
          const rect = el.getBoundingClientRect();
          if (rect.top >= top + 8 && rect.bottom <= bottom) return resolve("visible");
          const max = scroller.scrollHeight - scroller.clientHeight;
          const from = scroller.scrollTop;
          const to = Math.max(0, Math.min(max, from + (rect.top - top) - (bottom - top) * block));
          if (Math.abs(to - from) < 2) return resolve("clamped");
          // The page sets `scroll-behavior: smooth` on <html>; window scrolls are driven frame by frame instead.
          const set = (y) => (useWindow ? window.scrollTo({ top: y, behavior: "instant" }) : (scroller.scrollTop = y));
          if (!ms) {
            set(to);
            return resolve("jumped");
          }
          const start = performance.now();
          const step = (t) => {
            const p = Math.min(1, (t - start) / ms);
            const e = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
            set(from + (to - from) * e);
            if (p < 1) requestAnimationFrame(step);
            else resolve("scrolled");
          };
          requestAnimationFrame(step);
        }),
      { block, ms }
    );
    await this.pause(120);
  }

  /** The element's box once it has stopped moving (reveal-on-scroll animations slide content into place). */
  async box(locator) {
    await locator.waitFor({ state: "visible", timeout: 30000 });
    let box = await locator.boundingBox();
    const until = Date.now() + 2000;
    while (Date.now() < until) {
      await sleep(80);
      const next = await locator.boundingBox();
      if (box && next && Math.abs(next.x - box.x) < 0.5 && Math.abs(next.y - box.y) < 0.5) break;
      box = next;
    }
    if (!box) throw new Error(`no bounding box for ${locator}`);
    return box;
  }

  /** Moves the cursor onto the element and highlights it. */
  async point(locator, { reveal = true, hold = 450, highlight = true, at = [0.5, 0.5], block } = {}) {
    if (reveal) await this.reveal(locator, { block });
    await this.overlay();
    const box = await this.box(locator);
    const x = box.x + box.width * at[0];
    const y = box.y + box.height * at[1];
    await this.moveTo(x, y);
    if (highlight && !this.quick) {
      await this.page.evaluate(
        ([rect, ms]) => window.__wt && window.__wt.highlight(rect, ms),
        [box, Math.max(500, hold + 250)]
      );
    }
    await this.pause(hold);
    return { x, y, box };
  }

  async click(locator, options = {}) {
    const { x, y } = await this.point(locator, { hold: 380, ...options });
    await this.page.mouse.down();
    await this.pause(90);
    await this.page.mouse.up();
    this.pos = { x, y };
    await this.pause(options.after ?? 450);
  }

  async type(text, delay = 55) {
    await this.page.keyboard.type(text, { delay: this.quick ? 0 : delay });
  }

  /** Waits until the window stops scrolling (after a header tab or a Continue button). */
  async settle() {
    await sleep(120);
    await this.page.evaluate(
      () =>
        new Promise((resolve) => {
          let last = window.scrollY;
          let same = 0;
          const started = performance.now();
          const tick = () => {
            if (Math.abs(window.scrollY - last) < 0.5) same += 1;
            else {
              same = 0;
              last = window.scrollY;
            }
            if (same > 10 || performance.now() - started > 4000) resolve();
            else requestAnimationFrame(tick);
          };
          requestAnimationFrame(tick);
        })
    );
    await this.overlay();
  }

  headerTab(label) {
    return this.page.locator("header nav").filter({ visible: true }).first().getByRole("button", { name: label, exact: true });
  }

  headerLink(label) {
    return this.page.locator("header nav").filter({ visible: true }).first().getByRole("link", { name: label, exact: true });
  }

  /** Uses the app's own header tab, as a viewer would. */
  async nav(label) {
    await this.click(this.headerTab(label), { reveal: false, hold: 300, after: 150 });
    await this.settle();
  }

  /**
   * Smoothly scrolls a section's own scroll container until the element sits just below the section's sticky
   * header panel (the Result Dashboard), instead of under it.
   */
  async underSticky(sectionId, locator, ms = 900) {
    await locator.waitFor({ state: "attached", timeout: 30000 });
    await locator.evaluate(
      (el, { sectionId, ms }) =>
        new Promise((resolve) => {
          const section = document.getElementById(sectionId);
          const box = section && section.querySelector(".fine-scrollbar");
          if (!box) return resolve();
          const sticky = box.querySelector('[class*="sticky"]');
          const stickyBottom = box.getBoundingClientRect().top + (sticky ? sticky.getBoundingClientRect().height : 0);
          const from = box.scrollTop;
          const max = box.scrollHeight - box.clientHeight;
          const to = Math.max(0, Math.min(max, from + el.getBoundingClientRect().top - (stickyBottom + 10)));
          if (!ms || Math.abs(to - from) < 2) {
            box.scrollTop = to;
            return resolve();
          }
          const start = performance.now();
          const step = (t) => {
            const p = Math.min(1, (t - start) / ms);
            const e = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
            box.scrollTop = from + (to - from) * e;
            if (p < 1) requestAnimationFrame(step);
            else resolve();
          };
          requestAnimationFrame(step);
        }),
      { sectionId, ms: this.quick ? 0 : ms }
    );
    await this.pause(120);
  }

  /** Waits for a backend response through the app's /api/backend proxy. */
  response(fragment, method = "POST", timeout = 120000) {
    return this.page.waitForResponse(
      (r) => r.url().includes("/api/backend/") && r.url().includes(fragment) && r.request().method() === method,
      { timeout }
    );
  }
}

/* ------------------------------------------------------------------------------------------------------------ */
/* Chapters. Each one starts at its mark; the narration for that step plays from the mark.                      */
/* ------------------------------------------------------------------------------------------------------------ */
const STUDENT_QUESTION = "How interested would you be in solar panels on the roof?";

const CHAPTERS = {
  async intro(d) {
    const { page } = d;
    await d.pause(900);
    await d.point(page.getByRole("heading", { level: 1 }), { reveal: false, at: [0.55, 0.55], hold: 900, highlight: false });
    await d.narration(0.32);
    await d.point(page.getByText("Quality checks", { exact: false }).first(), { reveal: false, hold: 700, highlight: false });
    await d.narration(0.66);
    await d.click(page.getByRole("switch"), { reveal: false, hold: 500 });
    await d.point(page.getByText("Demo (no AI)", { exact: true }), { reveal: false, hold: 900 });
    if (!(await page.getByRole("switch").isChecked())) throw new Error("Demo (no AI) switch did not turn on");
    // Off the switch label before the poster frame (taken just before the next chapter), onto empty hero space.
    await d.moveTo(650, 600, 700);
  },

  async setup(d) {
    const { page } = d;
    await d.nav("Set Up");
    const neo = page.getByRole("button", { name: /Neo Smart Living Demo/ });
    await d.point(neo, { reveal: false, at: [0.5, 0.25], hold: 500 });
    const bootstrap = d.response("/study-mode/bootstrap/neo");
    await d.click(neo, { reveal: false, at: [0.5, 0.25], after: 200 });
    await bootstrap;
    // The status line first says "...prepared", then settles on "Current mode: ..." once the study reloads.
    await page.locator('#study-mode button[aria-pressed="true"]').filter({ hasText: "Neo Smart Living Demo" }).waitFor();
    await d.point(page.locator("#study-mode").getByText("Current selection", { exact: true }), { reveal: false, hold: 700 });
    await d.point(page.locator("#study-mode").getByRole("button", { name: /Continue to Audience Setup/ }), { reveal: false, hold: 600, highlight: false });
    await d.narration(0.78);
    await d.point(page.getByRole("button", { name: /General Custom Study/ }), { reveal: false, at: [0.5, 0.25], hold: 700 });
  },

  async audience(d) {
    const { page } = d;
    const section = page.locator("#audience");
    await d.nav("Audience");
    await d.point(section.getByText("Age Min", { exact: true }), { hold: 500 });
    await d.point(section.getByText("Household Income Min", { exact: true }), { hold: 500 });
    await d.narration(0.3);
    await d.reveal(section.getByText("Lifestyle Tags", { exact: true }), { block: 0.25 });
    await d.point(section.locator("select").filter({ hasText: "Homeowner only" }).first(), { hold: 700 });
    await d.point(section.getByText("outdoor lifestyle", { exact: true }), { hold: 700 });
    await d.narration(0.6);
    await d.point(section.getByText("Lifestyle Tags", { exact: true }), { hold: 500, highlight: false });
  },

  async product(d) {
    const { page } = d;
    const section = page.locator("#product");
    await d.nav("Product");
    await d.reveal(section.getByText("Product Name", { exact: true }), { block: 0.15 });
    await d.point(section.getByText("Product Name", { exact: true }), { hold: 500 });
    await d.reveal(section.getByText("Key Features", { exact: true }), { block: 0.1 });
    await d.point(section.getByText("Flat-pack delivery and fast install", { exact: true }), { hold: 600 });
    await d.point(section.getByText("Home office", { exact: true }).first(), { hold: 500 });
    await d.narration(0.62);
    await d.reveal(section.getByText("Likely Concerns", { exact: true }), { block: 0.2 });
    await d.point(section.getByText("Permit uncertainty", { exact: true }), { hold: 700 });
  },

  async market(d) {
    const { page } = d;
    const section = page.locator("#market");
    await d.nav("Market");
    await d.reveal(section.getByText("Substitutes", { exact: true }), { block: 0.12 });
    await d.point(section.getByText("Traditional shed conversion", { exact: true }).first(), { hold: 500 });
    await d.point(section.getByText("Home addition / remodel", { exact: true }), { hold: 500 });
    await d.reveal(section.getByText("Common Objections", { exact: true }), { block: 0.25 });
    await d.point(section.getByText("Permit or HOA friction", { exact: true }), { hold: 600 });
  },

  async survey(d) {
    const { page } = d;
    const section = page.locator("#survey");
    await d.nav("Survey");
    await d.reveal(section.getByText(/^Survey Structure Preview$/i), { block: 0.05 });
    await d.point(section.getByText(/^Title$/i).first(), { hold: 400, highlight: false });
    await d.point(section.getByText(/Neo Smart Living — Tahoe Mini Survey/).first(), { hold: 600 });
    await d.narration(0.33);
    const heading = section.getByRole("heading", { name: "Add your own question" });
    await d.reveal(heading, { block: 0.05 });
    await d.click(section.getByLabel("Question text"), { hold: 250, after: 200 });
    await d.type(STUDENT_QUESTION, 35);
    await d.click(section.getByRole("button", { name: "1–5 scale" }), { hold: 300, after: 250 });
    const added = d.response("/survey/questions");
    await d.click(section.getByRole("button", { name: "Add question", exact: true }), { block: 0.6, hold: 300, after: 100 });
    await added;
    const listed = section.getByText(/^SQ\d+: How interested would you be in solar panels/);
    await listed.waitFor();
    await d.point(listed, { hold: 800, block: 0.6 });
  },

  async experiment(d) {
    const { page } = d;
    const section = page.locator("#experiment");
    await d.nav("Experiment");
    await d.reveal(section.getByText(/^Execution Inputs$/i), { block: 0.0 });
    const sample = section.locator('input[type="number"]').first();
    await d.point(sample, { hold: 600 });
    await d.narration(0.18);
    // Whatever models the saved plan selected: two OpenRouter models without the class key, Jev alone with it.
    // A selected model is a chip ending in its remove mark.
    const chips = section.locator("button").filter({ hasText: /×\s*$/ });
    await chips.first().waitFor();
    const chipCount = Math.min(2, await chips.count());
    for (let i = 0; i < chipCount; i += 1) await d.point(chips.nth(i), { reveal: false, hold: 500 });
    await d.point(section.locator("button", { hasText: /^Add Model$/ }).first(), { reveal: false, hold: 450 });
    await d.narration(0.34);
    // Split Sample divides the respondents between the models; Mirror Sample has each model answer the same ones.
    await d.point(section.locator("button", { hasText: "Split Sample" }).first(), { block: 0.35, hold: 900 });
    await d.narration(0.54);
    await d.point(section.locator("button", { hasText: "Mirror Sample" }).first(), { block: 0.35, hold: 900 });
    await d.narration(0.77);
    await d.click(sample, { hold: 200, after: 100 });
    await sample.click({ clickCount: 3 });
    await d.type("100", 140);
    await d.pause(250);
    await d.snap("before_save");
    const saved = d.response("/experiment", "PATCH");
    const preview = d.response("/personas/preview");
    await d.click(section.getByRole("button", { name: "Save Experiment Plan" }), { hold: 350, after: 100 });
    await saved;
    await preview;
    // After the persona preview the app moves on to the Run step by itself.
    await d.headerTab("Run").and(page.locator('[aria-current="page"]')).waitFor({ timeout: 60000 });
    await d.settle();
  },

  async run(d) {
    const { page } = d;
    const section = page.locator("#run-simulation");
    const inView = await section.evaluate((el) => Math.abs(el.getBoundingClientRect().top - 128) < 40).catch(() => false);
    if (!inView) await d.nav("Run");
    // "Run live", or "Run live (Jev)" when the plan is Jev-only (the class key is set).
    await d.point(section.getByRole("button", { name: /^Run live/ }).first(), { reveal: false, hold: 600 });
    await d.point(section.getByText(/Demo \(no AI\): read-only/).first(), { reveal: false, hold: 600, highlight: false });
    const run = d.response("/simulation-runs");
    await d.click(section.getByRole("button", { name: "Show preloaded demo (no AI)" }), { reveal: false, hold: 400, after: 100 });
    const response = await run;
    if (!response.ok()) throw new Error(`preloaded demo run failed: HTTP ${response.status()}`);
    const banner = section.getByText(/^Preloaded demo: answers saved from a run/);
    await banner.waitFor();
    await d.narration(0.3);
    await d.reveal(banner, { block: 0.05 });
    await d.point(banner, { hold: 900 });
    await d.point(section.getByText(/^\d+ personas · \d+ completed surveys/).first(), { hold: 800 });
    await d.point(section.getByText(/^Models used$/i).first(), { hold: 700, highlight: false });
    await d.narration(0.72);
    await d.point(section.getByText(/^Run live to answer these:/).first(), { hold: 900 });
  },

  async result(d) {
    const { page } = d;
    const section = page.locator("#analysis");
    await d.nav("Result");
    await section.locator("h3").first().waitFor();
    await d.pause(300);
    // Q2 has a one-line question, so the question, its five bars and their labels all fit below the sticky
    // Result Dashboard panel at 1280x800.
    const heading = section.locator("h3", { hasText: "How likely are you to purchase a Tahoe Mini" }).first();
    const card = heading.locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' min-w-0 ')][1]");
    await d.underSticky("analysis", heading, 1300);
    // Charts render as their cards come near, and a rendered chart is taller than its placeholder: wait for the
    // cards passed on the way, then settle the question under the panel again.
    await card.locator(".overflow-x-auto").first().waitFor({ timeout: 30000 });
    await d.pause(500);
    await d.underSticky("analysis", heading, 450);
    await d.point(heading, { reveal: false, at: [0.25, 0.5], hold: 700, highlight: false });
    const bar = card.getByText("Probably would", { exact: true }).filter({ visible: true }).first();
    await d.point(bar, { reveal: false, at: [0.5, -1.4], hold: 600, highlight: false });
    await d.narration(0.45);
    const filter = section.locator("select").first();
    const { x, y } = await d.point(filter, { reveal: false, hold: 300 });
    await page.evaluate(([x, y]) => window.__wt && window.__wt.ripple(x, y), [x, y]);
    const values = await filter.locator("option").evaluateAll((opts) => opts.map((o) => o.value));
    const pick = values.find((v) => /gpt/i.test(v)) || values[1];
    await filter.selectOption(pick);
    await d.pause(900);
  },

  async insights(d) {
    const { page } = d;
    const section = page.locator("#insights");
    await d.nav("Insights");
    await d.reveal(section.getByText(/^Top use case$/i).first(), { block: 0.04 });
    await d.point(section.getByText(/^Top use case$/i).first(), { hold: 600 });
    await d.narration(0.3);
    await d.reveal(section.getByText(/^Barrier severity$/i).first(), { block: 0.04 });
    await d.point(section.getByText(/is the heaviest objection signal/).first(), { hold: 700 });
    await d.narration(0.5);
    await d.reveal(section.getByText(/^Positioning performance$/i).first(), { block: 0.04 });
    await d.point(section.getByText(/looks strongest on purchase lift/).first(), { hold: 900 });
  },

  async jev_live(d) {
    const { page } = d;
    const toggle = page.getByRole("switch");
    // Go to Run first: turning Demo off reloads the page in view, and on Insights that shows a loading card.
    await d.nav("Run");
    await d.click(toggle, { reveal: false, hold: 300 });
    if (await toggle.isChecked()) throw new Error("Demo switch is still on");
    const section = page.locator("#run-simulation");
    // With the class key set, the guided demo's plan is Jev alone and the button says so.
    const live = section.getByRole("button", { name: /^Run live \(Jev\)/ }).first();
    await live.waitFor({ timeout: 30000 }).catch(() => {
      throw new Error("no 'Run live (Jev)' button: is TYPESAFE_API_KEY set in apps/api/.env and the API restarted?");
    });
    await d.point(live, { reveal: false, hold: 700 });
    await d.click(live, { reveal: false, hold: 300, after: 100 });
    // The run is done when the Run Result panel reports live answers from Jev.
    const liveAnswers = section.getByText(/^Live answers$/).filter({ visible: true }).first();
    await liveAnswers.waitFor({ timeout: 180000 });
    await section.getByRole("button", { name: /^Running live/ }).waitFor({ state: "hidden", timeout: 180000 });
    await d.snap("live_run");
    await d.narration(0.3);
    await d.reveal(liveAnswers, { block: 0.3 });
    await d.point(liveAnswers, { hold: 1100 });
    await d.narration(0.5);
    // Result: the student's own question, answered by the live run.
    await d.click(section.getByRole("button", { name: "Continue to Result" }).filter({ visible: true }).first(), { hold: 300, after: 150 });
    await d.settle();
    const analysis = page.locator("#analysis");
    const heading = analysis.locator("h3", { hasText: "solar panels on the roof" }).filter({ visible: true }).first();
    await d.underSticky("analysis", heading, 1300);
    // Charts render as their cards come near and change height, which moves the question under the sticky
    // Result Dashboard panel: re-align until the question no longer needs moving.
    for (let i = 0; i < 8; i += 1) {
      await d.pause(400);
      const before = (await heading.boundingBox())?.y ?? 0;
      await d.underSticky("analysis", heading, 250);
      const after = (await heading.boundingBox())?.y ?? 0;
      if (Math.abs(before - after) < 2) break;
    }
    await d.point(heading, { reveal: false, at: [0.25, 0.5], hold: 1200, highlight: false });
    await d.snap("live_result");
    await d.narration(0.9);
    await d.click(toggle, { reveal: false, hold: 300 });
    if (!(await toggle.isChecked())) throw new Error("Demo switch did not turn back on");
  },

  async interview(d) {
    const { page } = d;
    const section = page.locator("#interview-synthesis");
    await d.nav("Interview");
    await d.point(section.getByText("Seeded demo data — not a live interview run", { exact: true }), { hold: 900 });
    await d.narration(0.45);
    const pairs = section.getByRole("button", { name: /View transcript pairs/ });
    await d.click(pairs, { block: 0.5 });
    const first = section.locator("button", { hasText: /#1 — / }).first();
    await d.click(first, { block: 0.1, after: 400 });
    await d.reveal(first, { block: 0.02 });
  },

  async research_brief(d) {
    const { page } = d;
    const go = page.locator("#interview-synthesis").getByRole("button", { name: /Continue to Research Brief/ });
    await d.click(go, { block: 0.5, after: 100 });
    await d.settle();
    const section = page.locator("#research-brief");
    await d.point(section.locator("textarea").first(), { hold: 800 });
    await d.narration(0.4);
    await d.reveal(section.getByText(/^Decisions to inform$/i), { block: 0.1 });
    await d.point(section.locator("textarea").nth(1), { hold: 600 });
    await d.point(section.locator("textarea").nth(2), { hold: 700 });
  },

  async interview_insights(d) {
    const { page } = d;
    const go = page.locator("#research-brief").getByRole("button", { name: /View Interview Insights/ });
    await d.click(go, { block: 0.5, after: 100 });
    await d.settle();
    const section = page.locator("#interview-insights");
    await d.point(section.getByText("Dedicated Space Reduces Friction", { exact: true }), { hold: 700 });
    await d.point(section.getByText(/^“I mostly use the house today/).first(), { hold: 700, highlight: false });
    await d.narration(0.55);
    await d.reveal(section.getByText(/^Continue the interview$/i), { block: 0.05 });
    await d.point(section.locator("select").first(), { hold: 800 });
  },

  async interview_page(d) {
    const { page } = d;
    const batch = d.response("/interview/demo/batch");
    await d.click(d.headerLink("Student Interview"), { reveal: false, hold: 300, after: 100 });
    await page.waitForURL(/\/interview$/);
    await batch;
    await page.getByText(/completed: 6\/6 personas complete/).filter({ visible: true }).first().waitFor({ timeout: 60000 });
    await d.overlay();
    await d.point(page.getByText("Demo session - pre-recorded, no AI", { exact: true }).filter({ visible: true }).first(), { reveal: false, hold: 700 });
    await d.point(page.getByRole("heading", { name: "Interview a persona" }), { reveal: false, hold: 500, highlight: false });
    await d.narration(0.35);
    const summary = page.locator("summary").filter({ hasText: /^P001 · 8\/8 answers/ }).filter({ visible: true }).first();
    await d.click(summary, { block: 0.25, after: 500 });
    await d.reveal(summary, { block: 0.0 });
    await d.pause(600);
    await d.snap("transcript");
    await d.narration(0.7);
    await d.point(page.getByRole("button", { name: "Export Markdown" }).first(), { block: 0.6, hold: 800 });
  },

  async focus_group(d) {
    const { page } = d;
    // The header click ran in LEADS.focus_group, just before this mark.
    await page.waitForURL(/\/focus-group$/);
    await d.lead;
    await page.getByRole("heading", { name: "Simulated focus group" }).waitFor({ timeout: 60000 });
    await d.overlay();
    await d.point(page.getByText(/^You are the moderator\./).filter({ visible: true }).first(), { reveal: false, hold: 600 });
    await d.narration(0.3);
    for (const stage of ["1. Icebreaker", "4. Price reactions", "5. Close"]) {
      await d.point(page.getByText(stage, { exact: true }).filter({ visible: true }).first(), { reveal: false, hold: 450 });
    }
    await d.narration(0.56);
    const firstAnswer = page.getByText(/^Moderator: Who lives with you/).filter({ visible: true }).first();
    await d.reveal(firstAnswer, { block: 0.05 });
    await d.point(page.locator('select[aria-label^="Quote "]').filter({ visible: true }).first(), { hold: 800 });
    await d.narration(0.71);
    const memo = page.getByRole("heading", { name: /Your memo/ }).filter({ visible: true }).first();
    if (await memo.count()) {
      await d.reveal(memo, { block: 0.05, duration: 1400 });
      await d.point(memo, { hold: 900 });
    }
  },

  async close(d) {
    const { page } = d;
    // The logo click ran in LEADS.close, just before this mark. Arriving home, jump straight to the top rather
    // than scroll through every section on the way.
    await page.waitForURL((url) => url.pathname === "/");
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" })).catch(() => {});
    await page.getByRole("heading", { name: "Simulated focus group" }).waitFor({ state: "detached", timeout: 60000 });
    await page.locator("#main").getByRole("button", { name: /Start Setup/ }).waitFor({ timeout: 60000 });
    await d.settle();
    await d.pause(600);
    await d.point(page.getByRole("heading", { level: 1 }), { reveal: false, at: [0.5, 0.6], hold: 900, highlight: false });
    await d.narration(0.24);
    await d.point(page.getByText("Demo (no AI)", { exact: true }), { reveal: false, hold: 600, highlight: false });
    await d.narration(0.76);
    // The credits: rest on the app's name in the header.
    const name = page.locator("header").filter({ visible: true }).first().getByRole("button", { name: /Grounded Synthetic Respondent Lab/ });
    await d.point(name, { reveal: false, at: [0.6, 0.5], hold: 600, highlight: false });
  },
};

/*
 * Page changes that start just before a chapter's mark, in the previous chapter's closing pause: the click that
 * loads another route, so its page is on screen when the narration about it begins rather than a second later.
 * `seconds` is how long before the mark the cursor sets off; `run` stores what the chapter waits on in d.lead.
 */
const LEADS = {
  focus_group: {
    seconds: 1.3,
    async run(d) {
      d.lead = d.response("/interview/demo/focus-group");
      d.lead.catch(() => {});
      await d.click(d.headerLink("Focus Group"), { reveal: false, hold: 250, after: 0 });
    },
  },
  close: {
    seconds: 1.1,
    async run(d) {
      const logo = d.page.locator("header").filter({ visible: true }).first().getByRole("button", { name: /Grounded Synthetic Respondent Lab/ });
      d.lead = null;
      await d.click(logo, { reveal: false, hold: 250, after: 0 });
    },
  },
};

/* ------------------------------------------------------------------------------------------------------------ */

async function main() {
  const { chromium } = loadPlaywright();
  fs.mkdirSync(OUT_DIR, { recursive: true });
  if (!QUICK) {
    fs.rmSync(FRAMES_DIR, { recursive: true, force: true });
    fs.mkdirSync(FRAMES_DIR, { recursive: true });
  }
  const missing = script.chapters.filter((c) => !CHAPTERS[c.step]).map((c) => c.step);
  if (missing.length) throw new Error(`no actions for: ${missing.join(", ")}`);
  if (!QUICK) {
    const noAudio = script.chapters.filter((c) => !(c.step in durations)).map((c) => c.step);
    if (noAudio.length) throw new Error(`no narration duration for: ${noAudio.join(", ")} (run tts.sh)`);
  }

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1, colorScheme: "light", locale: "en-US" });
  await context.addInitScript(OVERLAY_INIT);
  const page = await context.newPage();
  page.setDefaultTimeout(45000);
  const backendLog = [];
  page.on("response", (r) => {
    if (r.url().includes("/api/backend/")) backendLog.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`);
  });
  page.on("pageerror", (err) => console.warn(`[page error] ${err.message.slice(0, 200)}`));
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame() && process.env.DEBUG_NAV) console.log(`[nav] ${new URL(frame.url()).pathname}`);
  });

  // A fresh browser profile creates a fresh study; wait until the hero can start one.
  await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded", timeout: 180000 });
  await page.getByRole("button", { name: "Start Setup" }).waitFor({ timeout: 180000 });
  await page.waitForFunction(() => {
    const b = Array.from(document.querySelectorAll("button")).find((x) => /Start Setup/.test(x.textContent || ""));
    return b && !b.disabled;
  });
  if (await page.getByRole("switch").isChecked()) throw new Error("Demo switch should start off in a fresh profile");
  // The dev server compiles a route on its first request. Ask for the standalone pages now (no cookies, nothing
  // saved), so they do not stall on camera when the walkthrough opens them.
  for (const route of ["/interview", "/focus-group"]) {
    await fetch(`${BASE_URL}${route}`).then((r) => r.text()).catch(() => {});
  }
  await sleep(1200);

  const d = new Director(page, { quick: QUICK });
  await page.mouse.move(d.pos.x, d.pos.y);
  await d.overlay();

  // Screencast: JPEG frames (quality 90) with their capture timestamps (seconds, wall clock). JPEG encodes fast
  // enough that the browser keeps sending frames through scrolls and page loads; PNG left gaps of 2 s or more.
  const frames = [];
  let writeChain = Promise.resolve();
  let cdp = null;
  if (!QUICK) {
    cdp = await context.newCDPSession(page);
    cdp.on("Page.screencastFrame", (frame) => {
      cdp.send("Page.screencastFrameAck", { sessionId: frame.sessionId }).catch(() => {});
      const index = frames.length;
      const file = `${String(index).padStart(6, "0")}.jpg`;
      frames.push({ file, ts: frame.metadata.timestamp });
      const data = Buffer.from(frame.data, "base64");
      writeChain = writeChain.then(() => fs.promises.writeFile(path.join(FRAMES_DIR, file), data));
    });
    await cdp.send("Page.startScreencast", {
      format: "jpeg",
      quality: 90,
      maxWidth: VIEWPORT.width,
      maxHeight: VIEWPORT.height,
      everyNthFrame: 2,
    });
    const firstFrame = Date.now();
    while (!frames.length && Date.now() - firstFrame < 10000) await sleep(50);
    if (!frames.length) throw new Error("screencast produced no frames");
  }

  d.t0 = now();
  const report = [];
  await sleep(200);
  for (const [index, chapter] of script.chapters.entries()) {
    const mark = d.mark(chapter.step);
    d.snapPrefix = !ONLY.size || ONLY.has(chapter.step) ? path.join(OUT_DIR, `${String(index + 1).padStart(2, "0")}_${chapter.step}`) : null;
    const started = Date.now();
    process.stdout.write(`${String(index + 1).padStart(2, "0")} ${chapter.step.padEnd(20)} t=${mark.t.toFixed(2)}s `);
    try {
      await CHAPTERS[chapter.step](d);
    } catch (error) {
      await page.screenshot({ path: path.join(OUT_DIR, `error_${chapter.step}.png`) }).catch(() => {});
      throw error;
    }
    const actions = (Date.now() - started) / 1000;
    const next = script.chapters[index + 1];
    const lead = next ? LEADS[next.step] : null;
    let overrun = 0;
    if (QUICK) {
      if (!ONLY.size || ONLY.has(chapter.step)) {
        await d.overlay();
        await page.screenshot({ path: path.join(OUT_DIR, `${String(index + 1).padStart(2, "0")}_${chapter.step}.png`) });
      }
      if (lead) await lead.run(d);
    } else {
      const end = mark.t + mark.dur + GAP_AFTER_NARRATION;
      overrun = Math.max(0, d.elapsed() - end);
      if (lead) {
        await sleep((end - lead.seconds - d.elapsed()) * 1000);
        await lead.run(d);
      }
      await sleep((end - d.elapsed()) * 1000);
    }
    report.push({ step: chapter.step, t: mark.t, actions, narration: mark.dur, overrun });
    console.log(`actions=${actions.toFixed(2)}s${QUICK ? "" : ` narration=${mark.dur.toFixed(2)}s overrun=${overrun.toFixed(2)}s`}`);
  }
  await sleep(QUICK ? 0 : 1000);
  const end = d.elapsed();

  if (cdp) {
    await cdp.send("Page.stopScreencast").catch(() => {});
    await sleep(300);
    await writeChain;
    const t0 = d.t0;
    const timeline = frames.map((f) => ({ file: f.file, t: Math.round((f.ts - t0) * 1000) / 1000 }));
    fs.writeFileSync(path.join(OUT_DIR, "frames.json"), JSON.stringify({ end, frames: timeline }) + "\n");
    console.log(`frames: ${frames.length} (${(frames.length / end).toFixed(1)} fps average) over ${end.toFixed(1)} s`);
  }

  const marks = {
    version: VERSION,
    mode: QUICK ? "quick" : "full",
    viewport: VIEWPORT,
    duration: Math.round(end * 1000) / 1000,
    gap_after_narration: GAP_AFTER_NARRATION,
    chapters: report.map((r) => {
      const chapter = script.chapters.find((c) => c.step === r.step);
      return {
        step: r.step,
        label: chapter.label,
        t: Math.round(r.t * 1000) / 1000,
        narration: r.narration,
        actions: Math.round(r.actions * 1000) / 1000,
        overrun: Math.round(r.overrun * 1000) / 1000,
        ...(LEADS[r.step] ? { lead: LEADS[r.step].seconds } : {}),
        ...(chapter.placeholder ? { placeholder: true } : {}),
      };
    }),
  };
  fs.writeFileSync(path.join(OUT_DIR, "marks.json"), JSON.stringify(marks, null, 2) + "\n");
  fs.writeFileSync(path.join(OUT_DIR, "backend_requests.log"), backendLog.join("\n") + "\n");
  console.log(`marks -> ${path.join(OUT_DIR, "marks.json")}`);
  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

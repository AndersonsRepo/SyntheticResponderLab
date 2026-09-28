"use client";

import { Button } from "@/components/ui/button";
import type { ManualMemo, ManualQuote } from "@/lib/focus-group";

const field = "w-full rounded-lg border border-app-border bg-transparent px-3 py-2 text-sm";

type Turn = { turn_id: string; persona_id: string; text: string };

/** The student's own PA3.5 memo. Works with no AI at all: saving is free and never calls a model. */
export function ManualMemoForm({
  memo,
  onChange,
  onSave,
  turns,
  check,
  busy,
}: {
  memo: ManualMemo;
  onChange: (memo: ManualMemo) => void;
  onSave: () => void;
  turns: Turn[];
  check?: { saved: boolean; complete: boolean; problems: string[] };
  busy: boolean;
}) {
  const setTheme = (index: number, patch: Partial<ManualMemo["themes"][number]>) =>
    onChange({ ...memo, themes: memo.themes.map((t, n) => (n === index ? { ...t, ...patch } : t)) });
  const setOption = (index: number, patch: Partial<ManualMemo["answer_options"][number]>) =>
    onChange({
      ...memo,
      answer_options: memo.answer_options.map((o, n) => (n === index ? { ...o, ...patch } : o)),
    });

  return (
    <section aria-label="Your memo" className="flex flex-col gap-4 rounded-xl border border-app-border p-4 text-sm">
      <h3 className="text-lg font-semibold">Your memo (you write it)</h3>
      <p className="text-app-muted">
        Pick quotes with the “Quote…” control beside any answer, then trim them to the words that
        matter. Every quote stays linked to its turn ID. Saving is free and needs no AI.
      </p>

      {memo.themes.map((theme, index) => (
        <fieldset key={index} className="flex flex-col gap-2 rounded-lg border border-app-border p-3">
          <legend className="px-1 font-semibold">Theme {index + 1}</legend>
          <input
            aria-label={`Theme ${index + 1} label`}
            value={theme.label}
            onChange={(event) => setTheme(index, { label: event.target.value })}
            placeholder="Short label"
            className={field}
          />
          <textarea
            aria-label={`Theme ${index + 1} summary`}
            value={theme.synthesis}
            onChange={(event) => setTheme(index, { synthesis: event.target.value })}
            placeholder="One sentence: what you saw"
            className={field}
          />
          {theme.quotes.map((quote, q) => (
            <QuoteEditor
              key={q}
              quote={quote}
              onChange={(next) =>
                setTheme(index, { quotes: theme.quotes.map((old, n) => (n === q ? next : old)) })
              }
              onRemove={() => setTheme(index, { quotes: theme.quotes.filter((_, n) => n !== q) })}
            />
          ))}
          {theme.quotes.length === 0 ? <p className="text-app-muted">No quote yet.</p> : null}
        </fieldset>
      ))}
      <Button
        variant="secondary"
        onClick={() =>
          onChange({ ...memo, themes: [...memo.themes, { label: "", synthesis: "", quotes: [] }] })
        }
        disabled={memo.themes.length >= 6}
      >
        Add a theme
      </Button>

      <fieldset className="flex flex-col gap-2 rounded-lg border border-app-border p-3">
        <legend className="px-1 font-semibold">One surprise</legend>
        <textarea
          aria-label="Surprise"
          value={memo.surprise.summary}
          onChange={(event) => onChange({ ...memo, surprise: { ...memo.surprise, summary: event.target.value } })}
          className={field}
        />
        {memo.surprise.quote.turn_id ? (
          <QuoteEditor
            quote={memo.surprise.quote}
            onChange={(quote) => onChange({ ...memo, surprise: { ...memo.surprise, quote } })}
            onRemove={() => onChange({ ...memo, surprise: { ...memo.surprise, quote: { turn_id: "", text: "" } } })}
          />
        ) : (
          <p className="text-app-muted">No quote yet.</p>
        )}
      </fieldset>

      <fieldset className="flex flex-col gap-2 rounded-lg border border-app-border p-3">
        <legend className="px-1 font-semibold">PA4 answer options (at least three)</legend>
        {memo.answer_options.map((option, index) => (
          <div key={index} className="flex flex-wrap gap-2">
            <input
              aria-label={`Answer option ${index + 1}`}
              value={option.text}
              onChange={(event) => setOption(index, { text: event.target.value })}
              placeholder="Answer option wording"
              className={`${field} flex-1`}
            />
            <input
              aria-label={`Answer option ${index + 1} question topic`}
              value={option.topic}
              onChange={(event) => setOption(index, { topic: event.target.value })}
              placeholder="Question topic (e.g. current space use)"
              className={`${field} w-56`}
            />
            <select
              aria-label={`Answer option ${index + 1} source turn`}
              value={option.turn_id}
              onChange={(event) => setOption(index, { turn_id: event.target.value })}
              className={`${field} w-40`}
            >
              <option value="">No source turn</option>
              {turns.map((turn) => (
                <option key={turn.turn_id} value={turn.turn_id}>
                  {turn.turn_id}
                </option>
              ))}
            </select>
          </div>
        ))}
        <Button
          variant="secondary"
          onClick={() =>
            onChange({ ...memo, answer_options: [...memo.answer_options, { text: "", topic: "", turn_id: "" }] })
          }
          disabled={memo.answer_options.length >= 12}
        >
          Add an answer option
        </Button>
      </fieldset>

      <label className="flex flex-col gap-2">
        <span className="font-semibold">One thing you would change about how you moderated</span>
        <textarea
          value={memo.moderation_improvement}
          onChange={(event) => onChange({ ...memo, moderation_improvement: event.target.value })}
          className={field}
        />
      </label>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={onSave} disabled={busy}>
          Save my memo
        </Button>
        {check?.saved ? (
          <span role="status">{check.complete ? "Complete — ready to export." : "Saved as a draft."}</span>
        ) : null}
      </div>
      {check?.saved && !check.complete ? (
        <ul className="list-disc pl-5 text-app-muted">
          {check.problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function QuoteEditor({
  quote,
  onChange,
  onRemove,
}: {
  quote: ManualQuote;
  onChange: (quote: ManualQuote) => void;
  onRemove: () => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-app-muted">Quote from {quote.turn_id} (trim to the words you need)</span>
      <div className="flex gap-2">
        <textarea
          aria-label={`Quote from ${quote.turn_id}`}
          value={quote.text}
          onChange={(event) => onChange({ ...quote, text: event.target.value })}
          className={`${field} flex-1`}
        />
        <Button variant="secondary" onClick={onRemove}>
          Remove
        </Button>
      </div>
    </div>
  );
}

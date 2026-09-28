"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  revealRefusal,
  sharedSummary,
  type ConceptCard,
  type FocusGroupRoom,
  type FocusGroupStage,
  type RevealKind,
} from "@/lib/focus-group";

/**
 * The stimulus, shown to the moderator above the question field. Participants receive
 * nothing from it until the moderator introduces the concept or reveals the price.
 */
export function ConceptCardPanel({
  card,
  room,
  stage,
  pendingReveal,
  onReveal,
  busy,
}: {
  card: ConceptCard;
  room: FocusGroupRoom;
  stage: FocusGroupStage;
  pendingReveal: RevealKind | null;
  onReveal: (kind: RevealKind | null, question?: string) => void;
  busy: boolean;
}) {
  const [introduction, setIntroduction] = useState(card.introduction);
  const [copied, setCopied] = useState(false);
  const conceptRefusal = revealRefusal(room, stage, "concept");
  const priceRefusal = revealRefusal(room, stage, "price");
  const shared = sharedSummary(room);

  return (
    <div className="grid gap-3 md:grid-cols-2">
      <section
        aria-label="Concept card"
        data-testid="concept-card"
        className="flex flex-col gap-2 rounded-xl border border-app-border p-4 text-sm"
      >
        <h3 className="font-semibold">Concept card: {card.name}</h3>
        <p>{card.description}</p>
        <ul className="list-disc pl-5">
          {card.specs.map((spec) => (
            <li key={spec}>{spec}</li>
          ))}
        </ul>
        <p className="text-app-muted">Intended for {card.intended_for}.</p>
        <p className="text-app-muted">
          Price (for you, the moderator): {card.price}. Participants do not know it until you use
          Reveal price.
        </p>
        <label className="flex flex-col gap-1">
          <span className="font-semibold">Introduction you read aloud (edit freely)</span>
          <textarea
            value={introduction}
            onChange={(event) => setIntroduction(event.target.value)}
            className="rounded-lg border border-app-border bg-transparent px-3 py-2"
            rows={4}
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            onClick={() => onReveal("concept", introduction)}
            disabled={busy || conceptRefusal !== null}
          >
            Introduce the concept with this question
          </Button>
          <Button
            variant="secondary"
            onClick={() =>
              onReveal(
                "price",
                `The price is ${card.price}. How does that compare with what you expected?`
              )
            }
            disabled={busy || priceRefusal !== null}
          >
            Reveal price
          </Button>
          <Button
            variant="secondary"
            onClick={() =>
              navigator.clipboard?.writeText(card.text).then(() => setCopied(true), () => setCopied(false))
            }
          >
            {copied ? "Copied" : "Copy card as text (for ChatGPT)"}
          </Button>
        </div>
        {conceptRefusal && !shared.shown.some((s) => s.kind === "concept") ? (
          <p className="text-xs text-app-muted">{conceptRefusal}</p>
        ) : null}
        {priceRefusal && shared.shown.some((s) => s.kind === "concept") ? (
          <p className="text-xs text-app-muted">{priceRefusal}</p>
        ) : null}
        {pendingReveal ? (
          <p role="status" className="font-semibold">
            Your next question will show participants the {pendingReveal === "concept" ? "concept card" : "price"}.{" "}
            <button type="button" className="underline" onClick={() => onReveal(null)}>
              Don&apos;t reveal it
            </button>
          </p>
        ) : null}
      </section>

      <section
        aria-label="Information shared with participants"
        className="flex flex-col gap-2 rounded-xl border border-app-border p-4 text-sm"
      >
        <h3 className="font-semibold">Information shared with participants</h3>
        <p className="text-app-muted">
          Participants hear every moderator question and each other&apos;s answers. Beyond that,
          they know only what is listed here.
        </p>
        {shared.shown.length === 0 ? <p>Nothing about the product yet.</p> : null}
        {shared.shown.map((entry) => (
          <details key={entry.kind}>
            <summary>{entry.line}</summary>
            <pre className="whitespace-pre-wrap text-xs">{entry.text}</pre>
          </details>
        ))}
        {shared.withheld.map((line) => (
          <p key={line} className="text-app-muted">
            {line}
          </p>
        ))}
      </section>
    </div>
  );
}

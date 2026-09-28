"use client";

import type { ReactNode } from "react";

import {
  CARD_SOURCE_LABELS,
  cardHeadline,
  SCREENER_VERDICT_LABELS,
  type PersonaCard,
} from "@/lib/focus-group";
import { cn } from "@/lib/utils";

/** Expandable persona card. Native <details>, so it opens with a keyboard and a screen reader. */
export function PersonaCardView({
  card,
  personaId,
  selected = false,
  children,
}: {
  card: PersonaCard | null | undefined;
  personaId: string;
  selected?: boolean;
  children?: ReactNode;
}) {
  if (!card) {
    return (
      <div className="rounded-xl border border-app-border p-3 text-sm">
        {personaId} — no profile card available. {children}
      </div>
    );
  }
  const studentMade = card.origin === "student_created";
  return (
    <details
      className={cn("rounded-xl border border-app-border p-3 text-sm", selected && "border-app-cyan")}
      data-testid={`persona-card-${card.persona_id}`}
    >
      <summary className="cursor-pointer">
        <span className="font-semibold">{cardHeadline(card)}</span>
        {studentMade ? (
          <span className="ml-2 rounded-full border border-app-border px-2 py-0.5 text-xs">
            Student-created fictional persona · v{card.version}
          </span>
        ) : null}
      </summary>
      <div className="mt-2 flex flex-col gap-2">
        <p className="text-xs text-app-muted">{card.origin_label}</p>
        <dl className="grid grid-cols-[auto_1fr_auto] gap-x-3 gap-y-1">
          {card.attributes.map((attribute) => (
            <div key={attribute.key} className="contents">
              <dt className="text-app-muted">{attribute.label}</dt>
              <dd>{attribute.value}</dd>
              <dd className="text-xs text-app-muted">{CARD_SOURCE_LABELS[attribute.source]}</dd>
            </div>
          ))}
        </dl>
        <h4 className="font-semibold">PA3.5 screener</h4>
        <ul className="flex flex-col gap-1">
          {card.screener.map((entry) => (
            <li key={entry.criterion}>
              <strong>{SCREENER_VERDICT_LABELS[entry.verdict]}:</strong> {entry.criterion} — {entry.why}
            </li>
          ))}
        </ul>
        <p className="text-xs text-app-muted">{card.source_note}</p>
        {children}
      </div>
    </details>
  );
}

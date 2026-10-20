"use client";

import { useWalkthrough } from "@/components/walkthrough/walkthrough-provider";
import { WALKTHROUGH, type WalkthroughStep } from "@/lib/walkthrough-chapters";
import { chapterLength, formatTime } from "@/lib/walkthrough";
import { cn } from "@/lib/utils";

/** "▶ Watch this step (0:13)": opens the video guide at this step's chapter. */
export function WatchStepButton({ step, className }: { step: WalkthroughStep; className?: string }) {
  const { open } = useWalkthrough();
  const length = chapterLength(WALKTHROUGH, step);
  const label = WALKTHROUGH.chapters.find((chapter) => chapter.step === step)?.label.replace(/^\d+\s+/, "") ?? step;

  return (
    <button
      type="button"
      onClick={() => open(step)}
      aria-label={`Watch the ${label} step in the video guide${length === null ? "" : ` (${formatTime(length)})`}`}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[0.72rem] font-medium text-app-muted transition hover:text-app-cyan [background:var(--button-secondary-bg)] [border-color:var(--button-secondary-border)] hover:[background:var(--button-secondary-bg-hover)]",
        className
      )}
    >
      <span aria-hidden="true">{"\u25B6\uFE0E"}</span>
      Watch this step
      {length === null ? null : <span className="tabular-nums">({formatTime(length)})</span>}
    </button>
  );
}

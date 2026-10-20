"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import { WalkthroughPlayer, type WalkthroughPlayerHandle } from "@/components/walkthrough/walkthrough-player";
import { AppLogoMark } from "@/components/ui/workflow-nav";
import { WALKTHROUGH } from "@/lib/walkthrough-chapters";
import { formatTime, parseVideoParam } from "@/lib/walkthrough";

/** The public walkthrough: the same video and chapters as the in-app guide, for anyone with the link. */
export function WalkthroughPage() {
  const player = useRef<WalkthroughPlayerHandle | null>(null);

  // /walkthrough?video=survey (or #v=survey) starts at that chapter.
  useEffect(() => {
    const linked = parseVideoParam(window.location.search, window.location.hash, WALKTHROUGH.chapters);
    if (linked) player.current?.start(linked.step, false);
  }, []);

  return (
    <div className="min-h-screen bg-app-bg text-app-text">
      <header className="border-b [background:var(--nav-bg)] [border-color:var(--nav-border)]">
        <div className="mx-auto flex w-full max-w-[76rem] items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <AppLogoMark className="h-10 w-10" />
            <div className="truncate font-display text-[0.86rem] font-semibold uppercase tracking-[0.08em] text-app-cyan">
              Grounded Synthetic Respondent Lab
            </div>
          </div>
          <Link
            href="/"
            className="inline-flex h-10 shrink-0 items-center rounded-full border px-4 text-[0.82rem] font-medium transition hover:text-app-cyan [background:var(--button-secondary-bg)] [border-color:var(--button-secondary-border)]"
          >
            Open the app
          </Link>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[76rem] px-4 py-8 sm:px-6">
        <h1 className="font-display text-[2rem] font-medium leading-tight tracking-[-0.04em] sm:text-[2.6rem]">
          Video walkthrough
        </h1>
        <p className="mt-3 max-w-3xl text-[0.98rem] leading-7 text-app-muted">
          A {formatTime(WALKTHROUGH.duration)} narrated tour of the app: setting up and running a survey study,
          reading the results, and the interview and focus-group tools. Apart from one live run with Jev, it was
          recorded in Demo (no AI) mode, so the answers shown are saved synthetic answers. Pick a chapter to jump to
          it; captions are on by default.
        </p>
        <WalkthroughPlayer ref={player} className="mt-6" />
      </main>
    </div>
  );
}

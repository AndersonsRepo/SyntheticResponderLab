"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { GlassPanel } from "@/components/ui/glass-panel";
import {
  getInterviewModelCatalog,
  getInterviewPersonas,
  type InterviewModelCatalogEntry,
  type InterviewPersona,
} from "@/lib/api";
import {
  canAskStage,
  collectedAnswers,
  estimateFocusGroupCost,
  FOCUS_GROUP_STAGES,
  FOCUS_GROUP_STAGE_LABELS,
  focusGroupPath,
  focusGroupSetupRefusal,
  formatFocusGroupCostEstimate,
  MAX_ROUNDS,
  MIN_PERSONAS,
  missingAnswers,
  selectableStages,
  type FocusGroupMemo,
  type FocusGroupRoom,
  type FocusGroupStage,
} from "@/lib/focus-group";
import {
  formatInterviewModelOption,
  isInterviewModelSelectable,
  resetExpensiveModelSelection,
} from "@/lib/interview-models";
import { InterviewOperationError, interviewOperation } from "@/lib/standalone-interview";
import { cn } from "@/lib/utils";
import { StudyProvider, useStudy } from "@/providers/study-provider";

const STAGE_PROMPTS: Record<FocusGroupStage, string> = {
  icebreaker: "Let's go around the room — who lives with you, and what does a weekday look like?",
  space_needs: "Where in your home do you run out of room, and what do you do about it today?",
  concept: "Here's the idea. What's your first reaction, and what would you use it for?",
  price_reactions: "What would you expect something like this to cost?",
  close: "Anything we should have asked about and didn't?",
};

export default function FocusGroupPage() {
  return (
    <StudyProvider>
      <FocusGroupPageContent />
    </StudyProvider>
  );
}

function FocusGroupPageContent() {
  const { studyId, studyBootstrapError } = useStudy();
  const [personas, setPersonas] = useState<InterviewPersona[]>([]);
  const [models, setModels] = useState<InterviewModelCatalogEntry[]>([]);
  const [defaultModelId, setDefaultModelId] = useState("");
  const [selectedPersonaIds, setSelectedPersonaIds] = useState<string[]>([]);
  const [modelId, setModelId] = useState("");
  const [expensiveOptIn, setExpensiveOptIn] = useState(false);
  const [plannedRounds, setPlannedRounds] = useState<number>(FOCUS_GROUP_STAGES.length);
  const [confirming, setConfirming] = useState(false);
  const [room, setRoom] = useState<FocusGroupRoom | null>(null);
  const [rooms, setRooms] = useState<FocusGroupRoom[]>([]);
  const [stage, setStage] = useState<FocusGroupStage>("icebreaker");
  const [question, setQuestion] = useState(STAGE_PROMPTS.icebreaker);
  const [memo, setMemo] = useState<FocusGroupMemo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const startRequest = useRef<string>("");

  const model = models.find((entry) => entry.id === modelId);
  const refusal = focusGroupSetupRefusal({
    personaIds: selectedPersonaIds,
    rounds: plannedRounds,
    model,
    expensiveOptIn,
  });
  // Recomputed from the live controls, so the number the student confirms is the
  // number for the room they actually configured.
  const estimate = useMemo(
    () => estimateFocusGroupCost(selectedPersonaIds.length, plannedRounds, model),
    [selectedPersonaIds.length, plannedRounds, model]
  );

  useEffect(() => {
    getInterviewPersonas()
      .then((result) => setPersonas(result.personas))
      .catch((err: Error) => setError(err.message));
    getInterviewModelCatalog()
      .then((catalog) => {
        setModels(catalog.models);
        setDefaultModelId(catalog.defaultModelId);
        setModelId((current) => current || catalog.defaultModelId);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!expensiveOptIn) {
      setModelId((current) => resetExpensiveModelSelection(models, current, defaultModelId));
    }
  }, [expensiveOptIn, models, defaultModelId]);

  useEffect(() => {
    if (!studyId) return;
    interviewOperation<{ rooms: FocusGroupRoom[] }>(studyId, focusGroupPath())
      .then((result) => setRooms(result.rooms))
      .catch(() => undefined);
  }, [studyId, room?.revision, room?.status]);

  function togglePersona(personaId: string) {
    setSelectedPersonaIds((current) =>
      current.includes(personaId)
        ? current.filter((id) => id !== personaId)
        : [...current, personaId]
    );
  }

  async function run<T>(work: () => Promise<T>) {
    if (busy) return undefined;
    setBusy(true);
    setError("");
    try {
      return await work();
    } catch (err) {
      setError(
        err instanceof InterviewOperationError ? err.message : (err as Error).message
      );
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function startRoom() {
    if (!studyId || refusal) return;
    // One request id per confirmation: a double-clicked Start resolves to one room.
    startRequest.current = startRequest.current || crypto.randomUUID();
    const result = await run(() =>
      interviewOperation<{ room: FocusGroupRoom }>(studyId, focusGroupPath(), {
        request_id: startRequest.current,
        persona_ids: selectedPersonaIds,
        model: modelId,
        max_rounds: plannedRounds,
        allow_expensive_models: expensiveOptIn,
      })
    );
    setConfirming(false);
    if (result) {
      setRoom(result.room);
      setStage(result.room.stage);
      startRequest.current = "";
    }
  }

  async function askRoom(extra: Record<string, unknown> = {}) {
    if (!studyId || !room) return;
    const result = await run(() =>
      interviewOperation<{ room: FocusGroupRoom }>(
        studyId,
        focusGroupPath(room.room_id, "ask"),
        { revision: room.revision, stage, question: question.trim(), ...extra }
      )
    );
    if (result) {
      setRoom(result.room);
      setMemo(null);
    }
  }

  async function openRoom(roomId: string) {
    if (!studyId) return;
    const result = await run(() =>
      interviewOperation<{ room: FocusGroupRoom }>(studyId, focusGroupPath(roomId))
    );
    if (result) {
      setRoom(result.room);
      setStage(result.room.stage);
      setMemo(null);
    }
  }

  async function deleteRoom(roomId: string) {
    if (!studyId) return;
    await run(() =>
      fetch(
        `/api/backend/api/v1/studies/${encodeURIComponent(studyId)}/interview/${focusGroupPath(roomId)}`,
        { method: "DELETE" }
      )
    );
    if (room?.room_id === roomId) setRoom(null);
    setRooms((current) => current.filter((entry) => entry.room_id !== roomId));
  }

  async function loadMemo(authorize = false) {
    if (!studyId || !room) return;
    const path = focusGroupPath(room.room_id, "memo");
    const result = await run(() =>
      authorize && memo
        ? interviewOperation<{ memo: FocusGroupMemo }>(studyId, path, {
            revision: memo.revision,
            authorize_charge: true,
            retry_attempt: memo.saved?.attempt,
          })
        : interviewOperation<{ memo: FocusGroupMemo }>(studyId, path)
    );
    if (result) setMemo(result.memo);
  }

  async function exportRoom(format: "markdown" | "csv") {
    if (!studyId || !room) return;
    const result = await run(() =>
      interviewOperation<{ export: { content: string; filename: string; media_type: string } }>(
        studyId,
        focusGroupPath(room.room_id, "export"),
        { format }
      )
    );
    if (!result) return;
    const url = URL.createObjectURL(
      new Blob([result.export.content], { type: result.export.media_type })
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = result.export.filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  const answered = collectedAnswers(room);
  const missing = missingAnswers(room);

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-12">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold">Simulated focus group</h1>
        <p className="text-sm text-app-muted">
          You are the moderator. The personas hear each other and react. Same funnel and same
          memo fields as PA3.5, so the rehearsal matches the real thing.
        </p>
      </header>

      {studyBootstrapError ? <p role="alert">{studyBootstrapError}</p> : null}
      {error ? (
        <p role="alert" className="rounded-xl border border-app-border p-4 text-sm">
          {error}
        </p>
      ) : null}

      {!room ? (
        <GlassPanel className="flex flex-col gap-5 p-6">
          <h2 className="text-xl font-semibold">Recruit the room</h2>
          <div className="flex flex-wrap gap-2">
            {personas.map((persona) => (
              <button
                key={persona.persona_id}
                type="button"
                onClick={() => togglePersona(persona.persona_id)}
                disabled={busy}
                aria-pressed={selectedPersonaIds.includes(persona.persona_id)}
                className={cn(
                  "rounded-full border px-4 py-2 text-xs",
                  selectedPersonaIds.includes(persona.persona_id) && "border-app-cyan"
                )}
              >
                {persona.persona_id}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-3 text-sm">
            Questions planned
            <input
              type="number"
              min={1}
              max={MAX_ROUNDS}
              value={plannedRounds}
              onChange={(event) => setPlannedRounds(Number(event.target.value))}
              className="w-20 rounded-lg border border-app-border bg-transparent px-3 py-2"
            />
          </label>

          <label className="flex items-center gap-3 text-sm">
            Model
            <select
              value={modelId}
              onChange={(event) => setModelId(event.target.value)}
              className="rounded-lg border border-app-border bg-transparent px-3 py-2"
            >
              {models
                .filter((entry) => isInterviewModelSelectable(entry, expensiveOptIn))
                .map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {formatInterviewModelOption(entry)}
                  </option>
                ))}
            </select>
          </label>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={expensiveOptIn}
              onChange={(event) => setExpensiveOptIn(event.target.checked)}
            />
            Allow expensive models for this room
          </label>

          <p className="text-sm" data-testid="focus-group-estimate">
            {selectedPersonaIds.length} personas × {plannedRounds} questions ={" "}
            <strong>{formatFocusGroupCostEstimate(estimate)}</strong> estimated
          </p>

          {refusal ? (
            <p role="alert" className="text-sm text-app-muted">
              {refusal}
            </p>
          ) : null}

          <Button onClick={() => setConfirming(true)} disabled={busy || refusal !== null}>
            Start the focus group
          </Button>

          {confirming ? (
            <div role="dialog" aria-label="Confirm focus group cost" className="rounded-xl border border-app-border p-4">
              <p className="text-sm">
                This room runs {selectedPersonaIds.length} personas across up to {plannedRounds}{" "}
                questions — that is {selectedPersonaIds.length * plannedRounds} paid answers, about{" "}
                <strong>{formatFocusGroupCostEstimate(estimate)}</strong>. Nothing is spent until
                you confirm.
              </p>
              <div className="mt-3 flex gap-3">
                <Button onClick={startRoom} disabled={busy}>
                  {busy ? "Starting…" : "Confirm and start"}
                </Button>
                <Button variant="secondary" onClick={() => setConfirming(false)} disabled={busy}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : null}
        </GlassPanel>
      ) : null}

      {room ? (
        <GlassPanel className="flex flex-col gap-5 p-6">
          <div className="flex flex-wrap items-center gap-2">
            {FOCUS_GROUP_STAGES.map((entry, index) => (
              <button
                key={entry}
                type="button"
                onClick={() => {
                  setStage(entry);
                  setQuestion(STAGE_PROMPTS[entry]);
                }}
                disabled={busy || !canAskStage(room, entry)}
                aria-current={stage === entry ? "step" : undefined}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs",
                  stage === entry && "border-app-cyan"
                )}
              >
                {index + 1}. {FOCUS_GROUP_STAGE_LABELS[entry]}
              </button>
            ))}
          </div>
          <p className="text-xs text-app-muted">
            Stage {FOCUS_GROUP_STAGES.indexOf(stage) + 1} of {FOCUS_GROUP_STAGES.length}:{" "}
            {FOCUS_GROUP_STAGE_LABELS[stage]}. You can go back to{" "}
            {selectableStages(room).length} stage(s) already opened; every answer already collected
            stays in the transcript.
          </p>

          <div className="flex gap-2">
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") askRoom();
              }}
              placeholder="Ask the room…"
              className="flex-1 rounded-lg border border-app-border bg-transparent px-3 py-2"
            />
            <Button onClick={() => askRoom()} disabled={busy || !question.trim()}>
              {busy ? "Asking…" : "Ask the room"}
            </Button>
          </div>

          {room.status === "budget_stopped" || room.status === "failed" ? (
            <div role="alert" className="rounded-xl border border-app-border p-4 text-sm">
              <p>{room.error?.message}</p>
              {/* A budget stop leaves the same holes a failure does, and the server's
                  retry path accepts them — so offer the same repair once the budget is
                  raised, rather than stranding the room. */}
              {missing.length > 0 ? (
                <Button variant="secondary" onClick={() => askRoom({ retry: true })} disabled={busy}>
                  Retry the {missing.length} missing answer(s)
                </Button>
              ) : null}
            </div>
          ) : null}

          <ol className="flex flex-col gap-4">
            {room.rounds.map((round) => (
              <li key={round.index} className="flex flex-col gap-2">
                <p className="text-xs uppercase tracking-wide text-app-muted">
                  {FOCUS_GROUP_STAGE_LABELS[round.stage]}
                </p>
                <p className="font-semibold">Moderator: {round.question}</p>
                {round.answers.map((answer) => (
                  <p key={`${round.index}-${answer.persona_id}`} className="text-sm">
                    <strong>{answer.persona_id}:</strong>{" "}
                    {answer.status === "answered" ? (
                      answer.text
                    ) : (
                      <em>no answer yet — {answer.error?.message ?? "not run"}</em>
                    )}
                  </p>
                ))}
              </li>
            ))}
          </ol>

          <p className="text-sm" data-testid="focus-group-actual">
            Estimated {formatFocusGroupCostEstimate(Number(room.estimated_cost_usd))} · actually
            spent ${Number(room.session_usage.cost_usd).toFixed(4)} across {answered.length} answers
          </p>

          <div className="flex flex-wrap gap-3">
            <Button variant="secondary" onClick={() => loadMemo()} disabled={busy}>
              Write the memo
            </Button>
            <Button variant="secondary" onClick={() => exportRoom("markdown")} disabled={busy}>
              Export transcript + memo
            </Button>
            <Button
              variant="secondary"
              onClick={() =>
                run(() =>
                  interviewOperation<{ room: FocusGroupRoom }>(
                    studyId!,
                    focusGroupPath(room.room_id, "cancel"),
                    {}
                  ).then((result) => setRoom(result.room))
                )
              }
              disabled={busy || room.status === "cancelled"}
            >
              End this room
            </Button>
          </div>

          {memo ? (
            <div className="rounded-xl border border-app-border p-4 text-sm">
              <p>{memo.message}</p>
              {memo.eligible && !memo.available ? (
                <Button onClick={() => loadMemo(true)} disabled={busy}>
                  Confirm {formatFocusGroupCostEstimate(Number(memo.estimated_cost_usd))} and write it
                </Button>
              ) : null}
              {memo.saved?.message ? <p role="alert">{memo.saved.message}</p> : null}
              {memo.saved?.themes ? (
                <div className="flex flex-col gap-2">
                  <h3 className="font-semibold">Themes</h3>
                  {memo.saved.themes.map((theme) => (
                    <p key={theme.label}>
                      <strong>{theme.label}</strong> ({theme.sentiment}) — {theme.synthesis}
                      <br />“{theme.quote}” — {theme.persona_id},{" "}
                      {FOCUS_GROUP_STAGE_LABELS[theme.located_at.stage]} round{" "}
                      {theme.located_at.round + 1}
                    </p>
                  ))}
                  <h3 className="font-semibold">One surprise</h3>
                  <p>
                    {memo.saved.surprise?.summary} — “{memo.saved.surprise?.quote}” (
                    {memo.saved.surprise?.persona_id})
                  </p>
                  <h3 className="font-semibold">Closed-ended answer options</h3>
                  <ul>
                    {memo.saved.answer_options?.map((option) => (
                      <li key={option.text}>
                        “{option.text}” — {option.located_at.persona_id}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
        </GlassPanel>
      ) : null}

      <GlassPanel className="flex flex-col gap-3 p-6">
        <h2 className="text-xl font-semibold">Your focus groups</h2>
        {rooms.length === 0 ? <p className="text-sm text-app-muted">No rooms yet.</p> : null}
        {rooms.map((entry) => (
          <div key={entry.room_id} className="flex flex-wrap items-center gap-3 text-sm">
            <span>
              {entry.room_id.slice(0, 12)} · {entry.status} · {entry.persona_ids.length} personas ·{" "}
              {entry.rounds.length} questions
            </span>
            <Button variant="secondary" onClick={() => openRoom(entry.room_id)} disabled={busy}>
              Re-open
            </Button>
            <Button variant="secondary" onClick={() => deleteRoom(entry.room_id)} disabled={busy}>
              Delete
            </Button>
          </div>
        ))}
        <p className="text-xs text-app-muted">
          Sharing a classroom machine? End your session before you hand it over — the next student
          gets a new room list, and cannot see yours.
        </p>
        <Button
          variant="secondary"
          onClick={async () => {
            await fetch("/api/classroom/end-session", { method: "POST" });
            window.location.reload();
          }}
        >
          End my session and hand off this device
        </Button>
      </GlassPanel>
    </main>
  );
}

import type { Batch } from "./standalone-interview";

/** The memo PA3.5 grades: themes, one surprise, and closed-ended options in participant words. */
export type BatchMemo = {
  themes?: { label: string; synthesis: string; representative_quote: string; quote_persona_id: string; sentiment: string }[] | null;
  surprise?: { summary: string; quote: string; quote_persona_id: string } | null;
  answer_options?: { text: string; quote_persona_id: string }[] | null;
};

/** The memo PA3.5 grades is the student's own writing; ours is what they check it against. */
export type StudentMemo = { themes: string; surprise: string; options: string[] };

export function studentMemoMarkdown(memo?: StudentMemo | null) {
  const options = (memo?.options ?? []).map((option) => option.trim()).filter(Boolean);
  const themes = memo?.themes.trim() ?? "";
  const surprise = memo?.surprise.trim() ?? "";
  if (!themes && !surprise && !options.length) return "";
  return `\n# Memo\n\n## Themes\n\n${themes}\n\n## One surprise\n\n${surprise}\n\n`
    + `## Closed-ended answer options (participant language)\n\n${options.map((option) => `- ${option}`).join("\n")}\n\n---\n`;
}

/** The extraction, kept clearly separate: it is the student's check, not their submission. */
export function memoMarkdown(memo: BatchMemo | null | undefined) {
  if (!memo?.themes?.length) return "";
  const themes = memo.themes.map((theme, index) =>
    `### ${index + 1}. ${theme.label} (${theme.sentiment})\n\n${theme.synthesis}\n\n> ${theme.representative_quote}\n> — ${theme.quote_persona_id}\n`).join("\n");
  const surprise = memo.surprise
    ? `\n## One surprise\n\n${memo.surprise.summary}\n\n> ${memo.surprise.quote}\n> — ${memo.surprise.quote_persona_id}\n`
    : "";
  const options = memo.answer_options?.length
    ? `\n## Closed-ended answer options (participant language)\n\n${memo.answer_options
        .map((option) => `- ${option.text} — ${option.quote_persona_id}`).join("\n")}\n`
    : "";
  return `\n# AI reference — not the memo you hand in\n\n## Themes\n\n${themes}${surprise}${options}\n---\n`;
}

export function batchExport(batch: Batch, format: "csv" | "md", memo?: BatchMemo | null, student?: StudentMemo | null) {
  const rows = batch.transcripts.flatMap(transcript => transcript.messages.map((message, index) => [
    transcript.persona_id, batch.interviewer_model, batch.interviewee_model,
    String(Math.floor(index / 2) + 1), message.role === "user" ? "Question" : "Answer", message.content,
  ]));
  // Model output lands in a spreadsheet cell. A leading = + - @ (or the tab/CR that
  // Excel strips before deciding) makes the cell a formula, so neutralise it with a
  // leading apostrophe — the importer shows the original text and never evaluates it.
  const quote = (value: string) =>
    `"${(/^[=+\-@\t\r]/.test(value) ? `'${value}` : value).replace(/"/g, '""')}"`;
  const text = format === "csv"
    ? [["Persona", "Interviewer model", "Interviewee model", "Turn", "Role", "Text"], ...rows].map(row => row.map(quote).join(",")).join("\r\n")
    : `# Batch ${batch.job_id}\n\nStatus: ${batch.status}\nMeasured cost: $${batch.session_usage.cost_usd}\n${studentMemoMarkdown(student)}${memoMarkdown(memo)}\n` + rows.map(([persona, interviewer, interviewee, turn, role, content]) =>
      `## ${persona} — Turn ${turn}: ${role}\n\nInterviewer: ${interviewer} · Interviewee: ${interviewee}\n\n${content}\n`).join("\n");
  return { filename: `${batch.job_id}.${format}`, blob: new Blob([text], { type: format === "csv" ? "text/csv;charset=utf-8" : "text/markdown;charset=utf-8" }) };
}

"use client";

import { Button } from "@/components/ui/button";
import { PersonaCardView } from "@/components/focus-group/persona-card";
import { personaFormRefusal, type PersonaCard, type PersonaFields } from "@/lib/focus-group";

const field = "w-full rounded-lg border border-app-border bg-transparent px-3 py-2 text-sm";

/** Create persona / Duplicate and edit. Preview first; nothing is stored until Save. */
export function PersonaForm({
  fields,
  onChange,
  onPreview,
  onSave,
  onCancel,
  preview,
  editing,
  basedOn,
  busy,
}: {
  fields: PersonaFields;
  onChange: (fields: PersonaFields) => void;
  onPreview: () => void;
  onSave: () => void;
  onCancel: () => void;
  preview: { card: PersonaCard; description: string } | null;
  editing: boolean;
  basedOn: string | null;
  busy: boolean;
}) {
  const set = <K extends keyof PersonaFields>(key: K, value: PersonaFields[K]) => onChange({ ...fields, [key]: value });
  const refusal = personaFormRefusal(fields);
  return (
    <section aria-label="Practice persona form" className="flex flex-col gap-3 rounded-xl border border-app-border p-4 text-sm">
      <h3 className="text-lg font-semibold">
        {editing ? "Edit practice persona" : basedOn ? `Duplicate ${basedOn} and edit` : "Create persona"}
      </h3>
      <p className="text-app-muted">
        This becomes a Student-created fictional persona. It is practice only and never counts as
        recruiting a real PA3.5 participant. Describe the person, not what you hope they will say.
        Rooms already started keep the version they seated; edits apply to rooms you start next.
      </p>
      <label className="flex flex-col gap-1">
        Name (optional)
        <input value={fields.name} onChange={(e) => set("name", e.target.value)} className={field} />
      </label>
      <label className="flex flex-col gap-1">
        Household and living situation
        <textarea value={fields.household} onChange={(e) => set("household", e.target.value)} className={field} />
      </label>
      <label className="flex flex-col gap-1">
        Tenure
        <select
          value={fields.tenure}
          onChange={(e) => set("tenure", e.target.value as PersonaFields["tenure"])}
          className={field}
        >
          <option value="unknown">Unknown</option>
          <option value="owner">Owns their home</option>
          <option value="landowner">Owns land</option>
          <option value="renter">Rents</option>
          <option value="lives_with_family">Lives in a relative&apos;s home</option>
        </select>
      </label>
      <div className="flex flex-wrap gap-2">
        <label className="flex flex-col gap-1">
          Usable outdoor space
          <select
            value={fields.outdoor_space}
            onChange={(e) => set("outdoor_space", e.target.value as PersonaFields["outdoor_space"])}
            className={field}
          >
            <option value="unknown">Unknown</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </label>
        <label className="flex flex-1 flex-col gap-1">
          Outdoor space details
          <input value={fields.outdoor_note} onChange={(e) => set("outdoor_note", e.target.value)} className={field} />
        </label>
      </div>
      <label className="flex flex-col gap-1">
        How they use their space today
        <input
          value={fields.current_space_use}
          onChange={(e) => set("current_space_use", e.target.value)}
          className={field}
        />
      </label>
      <label className="flex flex-col gap-1">
        Willing to consider additional living or work space
        <select
          value={fields.willing_more_space}
          onChange={(e) => set("willing_more_space", e.target.value as PersonaFields["willing_more_space"])}
          className={field}
        >
          <option value="unknown">Unknown</option>
          <option value="yes">Yes</option>
          <option value="maybe">Maybe</option>
          <option value="no">No</option>
        </select>
      </label>
      <label className="flex flex-col gap-1">
        Relevant constraints (budget, HOA, time, family…)
        <input value={fields.constraints} onChange={(e) => set("constraints", e.target.value)} className={field} />
      </label>
      <label className="flex flex-col gap-1">
        Conversation style (optional)
        <select
          value={fields.style}
          onChange={(e) => set("style", e.target.value as PersonaFields["style"])}
          className={field}
        >
          <option value="">No preference</option>
          <option value="brief">Brief</option>
          <option value="talkative">Talkative</option>
        </select>
      </label>
      <label className="flex flex-col gap-1">
        How does this profile relate to your research question? (for you and your instructor; not
        shown to the persona)
        <textarea value={fields.research_link} onChange={(e) => set("research_link", e.target.value)} className={field} />
      </label>
      {refusal ? <p className="text-app-muted">{refusal}</p> : null}
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={onPreview} disabled={busy || refusal !== null}>
          Preview card
        </Button>
        <Button onClick={onSave} disabled={busy || refusal !== null || !preview}>
          {editing ? "Save new version" : "Save persona"}
        </Button>
        <Button variant="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
      {preview ? (
        <div className="flex flex-col gap-2">
          <h4 className="font-semibold">Preview</h4>
          <PersonaCardView card={preview.card} personaId={preview.card.persona_id} />
          <p className="text-xs text-app-muted">What the persona is told: {preview.description}</p>
        </div>
      ) : null}
    </section>
  );
}

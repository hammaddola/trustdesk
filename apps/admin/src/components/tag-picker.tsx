export const TAGS = ["case-study", "founder", "pricing", "faq"];

export function TagPicker({ selected = [] }: { selected?: string[] }) {
  return (
    <fieldset className="flex flex-wrap gap-3">
      <legend className="mb-1 text-sm font-medium text-heading">Tags</legend>
      {TAGS.map((t) => (
        <label key={t} className="flex items-center gap-1.5 text-sm">
          <input type="checkbox" name="tags" value={t} defaultChecked={selected.includes(t)} />
          {t}
        </label>
      ))}
    </fieldset>
  );
}

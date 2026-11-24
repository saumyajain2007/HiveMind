import type { RunRecord } from "@/lib/api/client";
import { formatRelative } from "@/lib/format";

export function RunPicker({
  value,
  candidates,
  onChange,
  label = "Run",
}: {
  value: string | null;
  candidates: RunRecord[];
  onChange: (id: string) => void;
  label?: string;
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      {label}
      <select
        className="h-8 max-w-80 rounded-md border bg-surface-2 px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      >
        {!value && <option value="">No run yet</option>}
        {candidates.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name} · {r.status} · {formatRelative(r.created_at)}
          </option>
        ))}
      </select>
    </label>
  );
}

import type { Schemas } from "@/lib/api/client";

import type { Parameters } from "./store";

export function get(p: Parameters | null, key: string): unknown {
  const [sec, field] = key.split(".");
  return (p as unknown as Record<string, Record<string, unknown>> | null)?.[sec!]?.[field!];
}

export const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Every parameter that differs from its default, as rows (for the diff view). */
export function parameterDiff(schema: Schemas["ConfigSchema"], params: Parameters | null) {
  const rows: { key: string; from: unknown; to: unknown }[] = [];
  for (const s of schema.sections)
    for (const f of s.fields) {
      const v = get(params, f.key);
      if (!same(v, f.default)) rows.push({ key: f.key, from: f.default, to: v });
    }
  return rows;
}

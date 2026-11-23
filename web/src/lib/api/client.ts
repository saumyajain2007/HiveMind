import createClient from "openapi-fetch";

import type { components, paths } from "./types";

export type Schemas = components["schemas"];
export type RunRecord = Schemas["RunRecord"];
export type RunDetail = Schemas["RunDetail"];
export type RunStatus = Schemas["RunStatus"];
export type ScenarioSpec = Schemas["ScenarioSpec"];
export type ConfigSchema = Schemas["ConfigSchema"];

/** Typed client generated from api/openapi.json (`pnpm gen:api`). Same-origin; Vite proxies /api. */
export const api = createClient<paths>({
  baseUrl: typeof window !== "undefined" ? window.location.origin : "",
  // Look fetch up per call: tools that patch it later (MSW in tests) must still be seen.
  fetch: (request) => globalThis.fetch(request),
});

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(message);
  }
}

/** Unwrap an openapi-fetch result or throw `ApiError`. */
export function unwrap<T>(res: { data?: T; error?: unknown; response: Response }): T {
  if (res.error !== undefined || res.data === undefined) {
    const detail = res.error;
    const msg =
      detail && typeof detail === "object" && "detail" in detail
        ? JSON.stringify((detail as { detail: unknown }).detail)
        : `${res.response.status} ${res.response.statusText}`;
    throw new ApiError(msg, res.response.status, detail);
  }
  return res.data;
}

import type { Schemas } from "@/lib/api/client";

import rawDefaults from "./fixtures/config-defaults.json";
import rawSchema from "./fixtures/config-schema.json";

/** Exported from the real API (`python -m marketsim_api.export_openapi`); JSON imports are widened, so re-type them. */
export const configDefaults = rawDefaults as unknown as Schemas["ConfigDefaults"];
export const configSchema = rawSchema as unknown as Schemas["ConfigSchema"];

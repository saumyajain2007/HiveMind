import { Building2, EyeOff, Megaphone, Newspaper, User } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Schemas } from "@/lib/api/client";

type EventSpec = Schemas["EventSpec"];

export const NARRATIVE = new Set(["rumour", "leak"]);
export const eventColor = (e: Pick<EventSpec, "kind">) =>
  NARRATIVE.has(e.kind) ? "var(--narrative)" : "var(--official)";

export const SEEDING_ICON: Record<string, LucideIcon> = {
  official: Building2,
  outlet: Newspaper,
  influencer: Megaphone,
  insider: User,
  anonymous: EyeOff,
};

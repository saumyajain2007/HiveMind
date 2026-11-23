import { AtSign, Camera, Handshake, MessagesSquare, Music, Play } from "lucide-react";
import type { LucideIcon } from "lucide-react";

/** Words for a sentiment in [-1, 1]. */
export function sentimentLabel(s: number): string {
  if (s <= -0.6) return "Very bearish";
  if (s <= -0.2) return "Bearish";
  if (s < 0.2) return "Neutral";
  if (s < 0.6) return "Bullish";
  return "Very bullish";
}

/** Platforms in ALL_PLATFORMS order, each with its fixed (validated) colour token. */
export const PLATFORMS = {
  twitter: { label: "Twitter", icon: AtSign, color: "var(--twitter)" },
  reddit: { label: "Reddit", icon: MessagesSquare, color: "var(--reddit)" },
  friendship: { label: "Friendship", icon: Handshake, color: "var(--friendship)" },
  instagram: { label: "Instagram", icon: Camera, color: "var(--instagram)" },
  tiktok: { label: "TikTok", icon: Music, color: "var(--tiktok)" },
  youtube: { label: "YouTube", icon: Play, color: "var(--youtube)" },
} as const satisfies Record<string, { label: string; icon: LucideIcon; color: string }>;

export type PlatformName = keyof typeof PLATFORMS;

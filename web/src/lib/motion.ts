import { useReducedMotion } from "motion/react";
import type { Transition } from "motion/react";

/**
 * The given transition, or an instant one under prefers-reduced-motion. Motion's own
 * reducedMotion="user" still runs opacity animations; this turns those off too.
 */
export function useMotionTransition(t: Transition): Transition {
  return useReducedMotion() ? { duration: 0, delay: 0 } : t;
}

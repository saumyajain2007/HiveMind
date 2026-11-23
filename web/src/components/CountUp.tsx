import { animate, useMotionValue, useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";

/**
 * Animates a number to its new value by writing straight into the DOM node, so the count-up
 * never re-renders React. Jumps directly under prefers-reduced-motion.
 */
export function CountUp({
  value,
  format,
  duration = 0.5,
  className,
}: {
  value: number | null | undefined;
  format: (n: number) => string;
  duration?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const mv = useMotionValue(value ?? 0);
  const reduce = useReducedMotion();
  const formatRef = useRef(format);

  useEffect(() => {
    formatRef.current = format;
  }, [format]);

  useEffect(() => {
    const unsub = mv.on("change", (v) => {
      if (ref.current) ref.current.textContent = formatRef.current(v);
    });
    return unsub;
  }, [mv]);

  useEffect(() => {
    if (value == null || !Number.isFinite(value)) {
      if (ref.current) ref.current.textContent = "—";
      return;
    }
    if (reduce || duration === 0) {
      mv.jump(value);
      if (ref.current) ref.current.textContent = formatRef.current(value);
      return;
    }
    const controls = animate(mv, value, { duration, ease: [0.22, 1, 0.36, 1] });
    return () => controls.stop();
  }, [value, duration, reduce, mv]);

  return (
    <span ref={ref} className={className}>
      {value == null || !Number.isFinite(value) ? "—" : format(value)}
    </span>
  );
}

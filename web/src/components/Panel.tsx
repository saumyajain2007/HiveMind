import { motion } from "motion/react";
import type { LucideIcon } from "lucide-react";
import { useId } from "react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { useMotionTransition } from "@/lib/motion";

export interface PanelProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  icon?: LucideIcon;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** Stagger index for the entry animation. */
  index?: number;
  as?: "section" | "div" | "article";
}

/** The basic surface: rounded card with a hairline border, an inner top highlight and a header. */
export function Panel({
  title,
  subtitle,
  icon: Icon,
  actions,
  children,
  className,
  bodyClassName,
  index = 0,
  as = "section",
}: PanelProps) {
  const Comp = motion[as];
  const autoId = useId();
  const transition = useMotionTransition({
    duration: 0.35,
    delay: Math.min(index, 8) * 0.05,
    ease: [0.22, 1, 0.36, 1],
  });
  const headingId = title ? `${autoId}-title` : undefined;
  return (
    <Comp
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={transition}
      aria-labelledby={headingId}
      className={cn(
        "panel-highlight flex min-w-0 flex-col rounded-xl border bg-card text-card-foreground",
        className,
      )}
    >
      {(title || actions) && (
        <header className="flex items-center gap-3 border-b px-4 py-3">
          {Icon && (
            <span className="grid size-7 shrink-0 place-items-center rounded-md bg-primary/10 text-primary">
              <Icon className="size-4" aria-hidden />
            </span>
          )}
          <div className="min-w-0 flex-1">
            {title && (
              <h2 id={headingId} className="truncate text-sm font-semibold tracking-tight">
                {title}
              </h2>
            )}
            {subtitle && <p className="truncate text-xs text-muted-foreground">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className={cn("min-h-0 flex-1 p-4", bodyClassName)}>{children}</div>
    </Comp>
  );
}

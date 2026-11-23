import { motion } from "motion/react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Tag } from "@/components/badges";
import { cn } from "@/lib/utils";

/** Centered empty / not-yet-built state: glowing icon, title, one line of context, actions. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  actions,
  issue,
  children,
  className,
}: {
  icon: LucideIcon;
  title: string;
  description: ReactNode;
  actions?: ReactNode;
  /** e.g. "#21": shows which issue builds this out. */
  issue?: string;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className={cn("flex flex-col items-center justify-center px-6 py-12 text-center", className)}
    >
      <div className="relative mb-5">
        <div aria-hidden className="absolute inset-0 -m-6 rounded-full bg-primary/15 blur-2xl" />
        <div className="relative grid size-14 place-items-center rounded-2xl border border-primary/30 bg-gradient-to-b from-primary/15 to-transparent text-primary shadow-[0_0_0_6px_var(--glow)]">
          <Icon className="size-6" aria-hidden />
        </div>
      </div>
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <p className="mt-1.5 max-w-md text-sm leading-relaxed text-muted-foreground">{description}</p>
      {issue && (
        <p className="mt-3 text-xs text-muted-foreground">
          Built in <Tag>{issue}</Tag>
        </p>
      )}
      {actions && (
        <div className="mt-6 flex flex-wrap items-center justify-center gap-2">{actions}</div>
      )}
      {children}
    </motion.div>
  );
}

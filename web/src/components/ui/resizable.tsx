import { GripVertical } from "lucide-react";
import * as React from "react";
import { Group, Panel, Separator } from "react-resizable-panels";

import { cn } from "@/lib/utils";

function ResizableGroup({ className, ...props }: React.ComponentProps<typeof Group>) {
  return (
    <Group
      className={cn("flex h-full w-full data-[orientation=vertical]:flex-col", className)}
      {...props}
    />
  );
}

const ResizablePanel = Panel;

/** Drag handle between panels; keyboard-resizable (arrow keys) when focused. */
function ResizableHandle({ className, ...props }: React.ComponentProps<typeof Separator>) {
  return (
    <Separator
      className={cn(
        "group relative flex w-3 shrink-0 items-center justify-center outline-none",
        "focus-visible:[&>div]:border-ring",
        className,
      )}
      {...props}
    >
      <div className="z-10 flex h-8 w-2.5 items-center justify-center rounded-sm border bg-card opacity-60 transition-opacity group-hover:opacity-100">
        <GripVertical className="size-3 text-muted-foreground" aria-hidden />
      </div>
    </Separator>
  );
}

export { ResizableGroup, ResizableHandle, ResizablePanel };

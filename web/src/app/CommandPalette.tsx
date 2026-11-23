import { Moon, Play, Square, Sun } from "lucide-react";
import { useEffect } from "react";
import { useNavigate } from "react-router";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import { disconnectRun, useLive } from "@/lib/live/store";
import { useTheme } from "@/lib/theme";

import { DESIGN_NAV, NAV } from "./nav";
import { useDemoReplay } from "./useDemoReplay";

/** ⌘K / Ctrl+K: jump to a page, toggle the theme, start or stop the demo run. */
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const demo = useDemoReplay();
  const status = useLive((s) => s.status);
  const streaming = status === "live" || status === "connecting" || status === "reconnecting";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  const run = (fn: () => void) => () => {
    onOpenChange(false);
    fn();
  };

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Go to a page or run an action…" />
      <CommandList>
        <CommandEmpty>Nothing matches.</CommandEmpty>
        <CommandGroup heading="Pages">
          {[...NAV, DESIGN_NAV].map((item) => (
            <CommandItem
              key={item.path}
              value={`${item.label} ${item.description}`}
              onSelect={run(() => navigate(item.path))}
            >
              <item.icon aria-hidden />
              <span>{item.label}</span>
              <span className="truncate text-xs text-muted-foreground">{item.description}</span>
              {item.shortcut && <CommandShortcut>{item.shortcut}</CommandShortcut>}
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandGroup heading="Actions">
          <CommandItem value="run demo replay start" onSelect={run(() => void demo.start())}>
            <Play aria-hidden />
            Run the demo scenario
          </CommandItem>
          {streaming && (
            <CommandItem value="stop live run disconnect" onSelect={run(disconnectRun)}>
              <Square aria-hidden />
              Stop watching the live run
            </CommandItem>
          )}
          <CommandItem value="toggle theme dark light" onSelect={run(toggleTheme)}>
            {theme === "dark" ? <Sun aria-hidden /> : <Moon aria-hidden />}
            Switch to {theme === "dark" ? "light" : "dark"} theme
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}

import { Toaster as Sonner } from "sonner";

import { useTheme } from "@/lib/theme";

/** App-wide toasts, themed with the design tokens. */
function Toaster() {
  const { theme } = useTheme();
  return (
    <Sonner
      theme={theme}
      position="bottom-right"
      toastOptions={{
        classNames: {
          toast:
            "!rounded-xl !border-border-strong !bg-popover !text-popover-foreground !shadow-xl",
          description: "!text-muted-foreground",
        },
      }}
    />
  );
}

export { Toaster };

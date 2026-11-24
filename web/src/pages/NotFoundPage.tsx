import { Compass } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";

export function NotFoundPage() {
  return (
    <div className="grid min-h-full place-items-center p-6">
      <EmptyState
        icon={Compass}
        title="Page not found"
        description="That address does not match any page."
      />
    </div>
  );
}

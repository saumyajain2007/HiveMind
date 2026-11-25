import { Check, ClipboardCopy, Wand2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { SentimentChip, Tag } from "@/components/badges";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import type { Schemas } from "@/lib/api/client";
import { useParseHeadlines } from "@/lib/api/queries";
import { simClock, TICKS_PER_DAY } from "@/lib/format";

import { parseLine } from "./parseLine";
import { builderStore, nextEventId, useBuilder } from "./store";

type EventSpec = Schemas["EventSpec"];

export function ImportHeadlines({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const events = useBuilder((s) => s.scenario.events);
  const days = useBuilder((s) => s.scenario.days ?? 5);
  const parse = useParseHeadlines();
  const [text, setText] = useState(
    "1 11:00 | Forum post: Acme in takeover talks\n3 10:00 | Acme denies any talks\n4 07:30 | Acme misses Q3 earnings estimates",
  );
  const [prompts, setPrompts] = useState<string[]>([]);
  const [replies, setReplies] = useState<string[]>([]);
  const [parsed, setParsed] = useState<EventSpec[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [keep, setKeep] = useState<Set<number>>(new Set());

  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map(parseLine);
  const headlines = lines.map((l) => ({
    text: l.text,
    tick: Math.min(l.tick, days * TICKS_PER_DAY - 1),
  }));
  const firstId = nextEventId(events);

  const accept = (res: Schemas["ParseResponse"]) => {
    setParsed(res.events ?? []);
    setErrors(res.errors ?? []);
    setKeep(new Set((res.events ?? []).map((e) => e.id)));
  };

  async function start() {
    try {
      const res = await parse.mutateAsync({ headlines, first_id: firstId, ticker: 0 });
      if (res.provider === "none") {
        setPrompts(res.prompts ?? []);
        setReplies((res.prompts ?? []).map(() => ""));
        setParsed([]);
      } else accept(res);
    } catch (e) {
      toast.error("Could not parse headlines", { description: (e as Error).message });
    }
  }

  async function submitReplies() {
    try {
      accept(
        await parse.mutateAsync({ headlines, responses: replies, first_id: firstId, ticker: 0 }),
      );
    } catch (e) {
      toast.error("Could not read the replies", { description: (e as Error).message });
    }
  }

  function add() {
    const chosen = parsed.filter((e) => keep.has(e.id));
    const valid = new Set(chosen.map((e) => e.id));
    builderStore
      .getState()
      .addEvents(chosen.map((e) => (valid.has(e.parent) ? e : { ...e, parent: -1 })));
    toast.success(`Added ${chosen.length} event${chosen.length === 1 ? "" : "s"} to the timeline`);
    setPrompts([]);
    setParsed([]);
    onOpenChange(false);
  }

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title="Import headlines"
      description="Turn real or made-up headlines into events with an LLM, review them, then add them to the timeline."
    >
      <div className="flex flex-col gap-5">
        <section className="flex flex-col gap-2">
          <label htmlFor="headlines" className="text-sm font-medium">
            1 · Headlines, one per line
          </label>
          <p className="text-xs text-muted-foreground">
            Optional time prefix: <code className="font-mono">day HH:MM | headline</code>. Earlier
            headlines are given to the LLM as context, so a denial can point at the rumour it
            denies.
          </p>
          <textarea
            id="headlines"
            rows={5}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="w-full rounded-md border bg-surface-2 p-2.5 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          />
          <Button
            onClick={() => void start()}
            disabled={!lines.length || parse.isPending}
            className="self-start"
          >
            <Wand2 />
            Parse {lines.length} headline{lines.length === 1 ? "" : "s"}
          </Button>
        </section>

        {prompts.length > 0 && parsed.length === 0 && (
          <section className="flex flex-col gap-3">
            <h3 className="text-sm font-medium">
              2 · Paste each prompt into any LLM, then paste its reply
            </h3>
            <p className="text-xs text-muted-foreground">
              No LLM provider is configured on the server, so nothing is sent anywhere. Set
              <code className="mx-1 font-mono">MARKETSIM_LLM_PROVIDER=anthropic</code>on the API to
              skip this step.
            </p>
            {prompts.map((p, i) => (
              <div key={i} className="flex flex-col gap-1.5 rounded-lg border p-3">
                <div className="flex items-center gap-2">
                  <Tag>#{i + 1}</Tag>
                  <span className="truncate text-sm">{headlines[i]?.text}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    onClick={() =>
                      void navigator.clipboard
                        ?.writeText(p)
                        .then(() => toast.success("Prompt copied"))
                    }
                  >
                    <ClipboardCopy />
                    Copy prompt
                  </Button>
                </div>
                <textarea
                  aria-label={`Reply for headline ${i + 1}`}
                  rows={3}
                  placeholder='{"kind": "rumour", "sentiment": 0.8, …}'
                  value={replies[i] ?? ""}
                  onChange={(e) =>
                    setReplies((r) => r.map((x, j) => (j === i ? e.target.value : x)))
                  }
                  className="w-full rounded-md border bg-surface-2 p-2 font-mono text-[11px] outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                />
              </div>
            ))}
            <Button
              onClick={() => void submitReplies()}
              disabled={parse.isPending || replies.some((r) => !r.trim())}
              className="self-start"
            >
              Read the replies
            </Button>
          </section>
        )}

        {(parsed.length > 0 || errors.length > 0) && (
          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">3 · Review</h3>
            {errors.map((e) => (
              <p
                key={e}
                role="alert"
                className="rounded-md border border-status-critical/40 bg-status-critical/10 px-2.5 py-1.5 text-xs text-bear-text"
              >
                {e}
              </p>
            ))}
            <ul className="flex flex-col divide-y rounded-lg border">
              {parsed.map((e) => (
                <li key={e.id} className="flex items-center gap-3 px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label={`Add “${e.label}”`}
                    checked={keep.has(e.id)}
                    onChange={() =>
                      setKeep((k) => {
                        const n = new Set(k);
                        if (n.has(e.id)) n.delete(e.id);
                        else n.add(e.id);
                        return n;
                      })
                    }
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm">{e.label}</p>
                    <p className="font-mono text-[11px] text-muted-foreground">
                      {simClock(e.tick).label} · {e.kind} · {e.seeding} · credibility{" "}
                      {e.credibility.toFixed(2)}
                      {e.parent >= 0 ? ` · follows #${e.parent}` : ""}
                    </p>
                  </div>
                  <SentimentChip value={e.sentiment} compact />
                </li>
              ))}
            </ul>
            <Button onClick={add} disabled={keep.size === 0} className="self-start">
              <Check />
              Add {keep.size} to the timeline
            </Button>
          </section>
        )}
      </div>
    </Sheet>
  );
}

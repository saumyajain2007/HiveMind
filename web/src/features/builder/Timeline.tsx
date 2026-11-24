import { useRef, useState } from "react";

import { useSize } from "@/components/charts/useSize";
import type { Schemas } from "@/lib/api/client";
import { MARKET_CLOSE_TICK, MARKET_OPEN_TICK, simClock, TICKS_PER_DAY } from "@/lib/format";

import { builderStore, nextEventId, useBuilder } from "./store";
import { eventColor, NARRATIVE } from "./vocab";
import { newEvent } from "./presets";

type EventSpec = Schemas["EventSpec"];

const H = 150;
const M = { left: 12, right: 12, top: 26, bottom: 20 };
const LANES = 4;

/**
 * Horizontal day / hour timeline with shaded market hours. Drag an event to move it, click to
 * edit it, double-click empty space to add one. Keyboard: focus an event, ← → move 15 min
 * (Shift: 1 hour), Delete removes it. Follow-ups are linked to their parent by an arc.
 */
export function Timeline() {
  const scenario = useBuilder((s) => s.scenario);
  const selected = useBuilder((s) => s.selected);
  const [ref, w] = useSize<HTMLDivElement>();
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ id: number; tick: number } | null>(null);
  const days = scenario.days ?? 5;
  const nTicks = days * TICKS_PER_DAY;
  const width = Math.max(w, 300);
  const plotW = width - M.left - M.right;
  const sx = (t: number) => M.left + (t / nTicks) * plotW;
  const tickAt = (clientX: number) => {
    const r = svgRef.current!.getBoundingClientRect();
    return Math.max(
      0,
      Math.min(nTicks - 1, Math.round(((clientX - r.left - M.left) / plotW) * nTicks)),
    );
  };
  const events = (scenario.events ?? []).map((e) =>
    drag?.id === e.id ? { ...e, tick: drag.tick } : e,
  );
  const lane = new Map<number, number>();
  const lastX: number[] = Array(LANES).fill(-Infinity);
  for (const e of [...events].sort((a, b) => a.tick - b.tick)) {
    const x = sx(e.tick);
    let l = lastX.findIndex((lx) => x - lx > 18);
    if (l < 0) l = 0;
    lane.set(e.id, l);
    lastX[l] = x;
  }
  const y = (id: number) => M.top + 18 + (lane.get(id) ?? 0) * 24;
  const byId = new Map(events.map((e) => [e.id, e]));
  const st = builderStore.getState;

  const move = (e: EventSpec, d: number) =>
    st().upsertEvent({ ...e, tick: Math.max(0, Math.min(nTicks - 1, e.tick + d)) });

  return (
    <div ref={ref} className="w-full select-none">
      {w > 0 && (
        <svg
          ref={svgRef}
          width={width}
          height={H}
          className="block touch-none"
          role="group"
          aria-label={`Event timeline, ${days} days, ${events.length} events`}
          onDoubleClick={(ev) => {
            if ((ev.target as Element).closest("[data-event]")) return;
            const id = nextEventId(scenario.events);
            st().upsertEvent(newEvent(id, tickAt(ev.clientX)));
            st().select(id);
          }}
          onPointerMove={(ev) => drag && setDrag({ ...drag, tick: tickAt(ev.clientX) })}
          onPointerUp={() => {
            if (!drag) return;
            const e = scenario.events?.find((x) => x.id === drag.id);
            if (e && e.tick !== drag.tick) st().upsertEvent({ ...e, tick: drag.tick });
            setDrag(null);
          }}
        >
          {Array.from({ length: days }, (_, d) => (
            <g key={d}>
              <rect
                x={sx(d * TICKS_PER_DAY + MARKET_OPEN_TICK)}
                y={M.top}
                width={sx(MARKET_CLOSE_TICK) - sx(MARKET_OPEN_TICK)}
                height={H - M.top - M.bottom}
                fill="var(--primary)"
                opacity={0.07}
              />
              <line
                x1={sx(d * TICKS_PER_DAY)}
                x2={sx(d * TICKS_PER_DAY)}
                y1={12}
                y2={H - M.bottom}
                stroke="var(--border-strong)"
              />
              <text
                x={sx(d * TICKS_PER_DAY) + 4}
                y={14}
                className="fill-foreground text-[11px] font-semibold"
              >
                Day {d + 1}
              </text>
              {[6, 12, 18].map((h) => (
                <text
                  key={h}
                  x={sx(d * TICKS_PER_DAY + h * 4)}
                  y={H - 6}
                  textAnchor="middle"
                  className="fill-muted-foreground font-mono text-[9px]"
                >
                  {String(h).padStart(2, "0")}:00
                </text>
              ))}
            </g>
          ))}
          <text
            x={sx(MARKET_OPEN_TICK) + 3}
            y={M.top + 10}
            className="fill-muted-foreground text-[9px]"
          >
            market open
          </text>
          {events
            .filter((e) => e.parent >= 0 && byId.has(e.parent))
            .map((e) => {
              const p = byId.get(e.parent)!;
              const x0 = sx(p.tick);
              const x1 = sx(e.tick);
              const mid = (x0 + x1) / 2;
              return (
                <path
                  key={`link-${e.id}`}
                  d={`M${x0},${y(p.id)} Q${mid},${Math.min(y(p.id), y(e.id)) - 30} ${x1},${y(e.id)}`}
                  fill="none"
                  stroke="var(--muted-foreground)"
                  strokeDasharray="3 3"
                  strokeWidth={1.2}
                />
              );
            })}
          {events.map((e) => {
            const cx = sx(e.tick);
            const cy = y(e.id);
            const on = selected === e.id;
            const name = e.label || `${e.kind} event`;
            return (
              <g
                key={e.id}
                data-event
                role="button"
                tabIndex={0}
                aria-pressed={on}
                aria-label={`${name}, ${e.kind}, ${simClock(e.tick).label}. Arrow keys move it, Delete removes it.`}
                className="cursor-grab outline-none [&:focus-visible>circle:first-child]:stroke-[var(--ring)]"
                onPointerDown={(ev) => {
                  (ev.currentTarget.ownerSVGElement as SVGSVGElement).setPointerCapture(
                    ev.pointerId,
                  );
                  st().select(e.id);
                  setDrag({ id: e.id, tick: e.tick });
                }}
                onKeyDown={(ev) => {
                  if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") {
                    ev.preventDefault();
                    move(e, (ev.key === "ArrowLeft" ? -1 : 1) * (ev.shiftKey ? 4 : 1));
                  } else if (ev.key === "Delete" || ev.key === "Backspace") {
                    ev.preventDefault();
                    st().removeEvent(e.id);
                  } else if (ev.key === "Enter" || ev.key === " ") {
                    ev.preventDefault();
                    st().select(e.id);
                  }
                }}
              >
                <circle
                  cx={cx}
                  cy={cy}
                  r={on ? 11 : 9}
                  fill="var(--card)"
                  stroke={on ? "var(--foreground)" : "transparent"}
                  strokeWidth={2}
                />
                <rect
                  x={cx - 6}
                  y={cy - 6}
                  width={12}
                  height={12}
                  rx={NARRATIVE.has(e.kind) ? 6 : 2}
                  transform={NARRATIVE.has(e.kind) ? undefined : `rotate(45 ${cx} ${cy})`}
                  fill={eventColor(e)}
                />
                <title>{`${name} · ${simClock(e.tick).label}`}</title>
              </g>
            );
          })}
          {drag && (
            <text
              x={sx(drag.tick)}
              y={M.top - 4}
              textAnchor="middle"
              className="fill-foreground font-mono text-[10px]"
            >
              {simClock(drag.tick).label}
            </text>
          )}
        </svg>
      )}
    </div>
  );
}

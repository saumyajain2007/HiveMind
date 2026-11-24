import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, vi } from "vitest";

import { handlers, resetMockDb } from "@/mocks/handlers";

// jsdom lacks these browser APIs; the components only need harmless stand-ins.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
if (!("ResizeObserver" in window)) {
  class RO {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (window as unknown as { ResizeObserver: unknown }).ResizeObserver = RO;
}
Element.prototype.scrollIntoView ??= () => {};

// lightweight-charts draws on a real canvas, which jsdom lacks: a no-op stand-in for unit tests
// (the e2e suite runs the real chart in Chromium).
vi.mock("lightweight-charts", () => {
  const series = () => ({
    setData: () => {},
    applyOptions: () => {},
    priceScale: () => ({ applyOptions: () => {} }),
  });
  return {
    CandlestickSeries: {},
    HistogramSeries: {},
    LineSeries: {},
    ColorType: { Solid: "solid" },
    CrosshairMode: { Normal: 0 },
    LineStyle: { Dashed: 2 },
    createSeriesMarkers: () => ({ setMarkers: () => {} }),
    createChart: () => ({
      addSeries: series,
      applyOptions: () => {},
      subscribeCrosshairMove: () => {},
      unsubscribeCrosshairMove: () => {},
      timeScale: () => ({ fitContent: () => {} }),
      remove: () => {},
    }),
  };
});

/** The same mock API the dev server uses, so tests exercise real request code. */
export const server = setupServer(...handlers);

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMockDb();
  localStorage.clear();
});
afterAll(() => server.close());

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { connectRun, resetLive } from "@/lib/live/store";

import { Providers } from "./Providers";
import { routes } from "./routes";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <Providers>
      <RouterProvider router={router} />
    </Providers>,
  );
  return router;
}

describe("app shell", () => {
  afterEach(() => resetLive());

  it("renders navigation, the ticker and the runs from the API", async () => {
    renderAt("/");
    const nav = screen.getByRole("navigation", { name: "Primary" });
    for (const label of [
      "Runs",
      "Builder",
      "Cockpit",
      "Monte Carlo",
      "Network",
      "Narratives",
      "Analysis",
    ]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(within(nav).getByRole("link", { name: "Runs" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByLabelText("Market ticker")).toHaveTextContent("IDLE");
    expect(await screen.findByText("Quiet market (no events)")).toBeInTheDocument();
    expect(screen.getAllByText("Done").length).toBeGreaterThan(0);
    expect(await screen.findByRole("status", { name: "API online" })).toBeInTheDocument();
  });

  it("toggles the theme on <html> and remembers it", () => {
    renderAt("/");
    expect(document.documentElement).toHaveClass("dark");
    fireEvent.click(screen.getByRole("button", { name: "Toggle theme" }));
    expect(document.documentElement).toHaveClass("light");
    expect(localStorage.getItem("marketsim-theme")).toBe("light");
  });

  it("opens the command palette with Ctrl+K", async () => {
    renderAt("/");
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Go to a page or run an action…")).toBeInTheDocument();
  });

  it("shows planned pages with their issue number", async () => {
    renderAt("/network");
    expect(await screen.findByText(/WebGL graph of a sampled subgraph/)).toBeInTheDocument();
    expect(screen.getAllByText("#23").length).toBeGreaterThan(0);
  });

  it("cockpit streams the mock run into the ticker", async () => {
    renderAt("/cockpit");
    expect(await screen.findByText("No live run")).toBeInTheDocument();
    act(() => connectRun("demo-test"));
    const ticker = screen.getByLabelText("Market ticker");
    expect(
      await within(ticker).findByText(/Day 1 · 0\d:\d\d/, {}, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/agents · 5 days/)).toBeInTheDocument();
  });
});

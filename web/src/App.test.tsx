import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App skeleton", () => {
  it("renders the shell and reports the API as online", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ status: "ok", api_version: "0.1.0", engine_version: "0.1.0" }),
      ),
    );
    render(<App />);
    expect(screen.getByRole("heading", { name: "HiveMind" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(await screen.findByText(/API online/)).toBeInTheDocument();
  });

  it("shows the API as offline when the health check fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network");
      }),
    );
    render(<App />);
    expect(await screen.findByText("API offline")).toBeInTheDocument();
  });
});

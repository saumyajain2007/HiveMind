import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { Providers } from "@/app/Providers";
import { DesignPage } from "@/pages/DesignPage";

import { PlaceholderBadge, SentimentChip, StatusPill } from "./badges";
import { Delta } from "./Delta";
import { Sparkline } from "./Sparkline";
import { Stat } from "./Stat";

function wrap(ui: React.ReactNode) {
  return render(<Providers>{ui}</Providers>);
}

describe("shared components", () => {
  it("Stat shows label, value and a delta with a non-colour cue", () => {
    wrap(
      <Stat
        label="Price"
        value={101.5}
        format={(v) => v.toFixed(2)}
        delta={-0.031}
        period="vs open"
      />,
    );
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.getByText("101.50")).toBeInTheDocument();
    expect(screen.getByText("down")).toHaveClass("sr-only");
    expect(screen.getByText("−3.10%")).toBeInTheDocument();
    expect(screen.getByText("vs open")).toBeInTheDocument();
  });

  it("Delta treats 'up is bad' correctly", () => {
    const { container } = wrap(<Delta value={0.02} upIsGood={false} />);
    expect(container.querySelector(".text-bear-text")).not.toBeNull();
  });

  it("SentimentChip names the sentiment in words", () => {
    wrap(<SentimentChip value={-0.7} />);
    expect(screen.getByLabelText("Sentiment Very bearish (−0.70)")).toBeInTheDocument();
    expect(screen.getByText("Very bearish")).toBeInTheDocument();
  });

  it("StatusPill and PlaceholderBadge carry text labels", () => {
    wrap(
      <>
        <StatusPill status="failed" />
        <PlaceholderBadge />
      </>,
    );
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("Placeholder")).toBeInTheDocument();
  });

  it("Sparkline has a summarising accessible name", () => {
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 200 });
    wrap(<Sparkline values={[1, 3, 2]} label="Test series" format={(v) => v.toFixed(1)} />);
    expect(
      screen.getByRole("img", {
        name: "Test series: 3 points, from 1.0 to 2.0, low 1.0, high 3.0",
      }),
    ).toBeInTheDocument();
  });
});

describe("design system page", () => {
  it("renders both themes with no axe violations (structure; colour contrast is checked in e2e)", async () => {
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 300 });
    const { container } = wrap(<DesignPage />);
    expect(screen.getByRole("region", { name: "dark theme" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "light theme" })).toBeInTheDocument();
    const res = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(
      res.violations.map(
        (v) => `${v.id}: ${v.help} :: ${v.nodes.map((n) => n.html.slice(0, 160)).join(" | ")}`,
      ),
    ).toEqual([]);
  });
});

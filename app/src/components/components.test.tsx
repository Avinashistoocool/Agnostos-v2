import { describe, expect, it } from "vitest";
import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ChipInput } from "./ui";
import { BarChart } from "../screens/Dashboard";
import { RunDialog } from "../screens/Pipeline";
import { SessionProvider } from "../lib/session";
import { JobsProvider } from "../lib/jobs";
import { ToastProvider } from "./Toast";
import { createMockEngine } from "../lib/engine";
import type { CommandSpec } from "../lib/types";
import App from "../App";

function ChipHarness() {
  const [v, setV] = useState<string[]>(["ML"]);
  return (
    <>
      <ChipInput label="Add interest" value={v} onChange={setV} suggestions={["robotics", "ML"]} />
      <output data-testid="val">{v.join("|")}</output>
    </>
  );
}

describe("ChipInput", () => {
  it("adds on Enter, dedupes, adds suggestions and removes", async () => {
    const u = userEvent.setup();
    render(<ChipHarness />);
    const input = screen.getByLabelText("Add interest");
    await u.type(input, "physics{Enter}");
    await u.type(input, "ml{Enter}");
    expect(screen.getByTestId("val")).toHaveTextContent("ML|physics");
    await u.click(screen.getByRole("button", { name: "+ robotics" }));
    expect(screen.getByTestId("val")).toHaveTextContent("ML|physics|robotics");
    await u.click(screen.getByRole("button", { name: "Remove physics" }));
    expect(screen.getByTestId("val")).toHaveTextContent("ML|robotics");
  });
});

describe("BarChart", () => {
  it("renders one bar per day with an accessible label", () => {
    const { container } = render(
      <BarChart
        data={[
          { date: "2026-11-01", count: 1 },
          { date: "2026-11-02", count: 0 },
          { date: "2026-11-03", count: 4 },
        ]}
      />,
    );
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", "Emails sent per day, last 3 days");
    expect(container.querySelectorAll(".group").length).toBe(3);
  });
});

const sendSpec: CommandSpec = {
  name: "send",
  title: "Send emails",
  group: "Send",
  description: "d",
  fields: [
    { name: "limit", type: "int", label: "Max emails", default: 5 },
    { name: "live", type: "bool", label: "Send for real", default: false },
  ],
  live_field: "live",
  confirmation: "SEND LIVE",
};

describe("RunDialog", () => {
  it("requires the exact confirmation text before a live run can start", async () => {
    const u = userEvent.setup();
    const { engine } = createMockEngine({ latency: 0, signedIn: true });
    render(
      <ToastProvider>
        <SessionProvider engine={engine}>
          <MemoryRouter>
            <JobsProvider>
              <RunDialog spec={sendSpec} onClose={() => {}} />
            </JobsProvider>
          </MemoryRouter>
        </SessionProvider>
      </ToastProvider>,
    );
    const start = await screen.findByTestId("start-job");
    expect(start).toHaveTextContent("Start dry run");
    expect(start).toBeEnabled();
    await u.click(screen.getByRole("switch", { name: /send for real/i }));
    expect(start).toHaveTextContent("Start live run");
    expect(start).toBeDisabled();
    const box = screen.getByLabelText(/to confirm/i);
    await u.type(box, "send live");
    expect(start).toBeDisabled();
    await u.clear(box);
    await u.type(box, "SEND LIVE");
    expect(start).toBeEnabled();
  });
});

describe("App", () => {
  it("shows sign-in, then onboarding after guest sign-in", async () => {
    const u = userEvent.setup();
    const { engine } = createMockEngine({ latency: 0 });
    render(<App engine={engine} />);
    await u.click(await screen.findByRole("button", { name: /continue as guest/i }));
    expect(await screen.findByText("Start with your resume")).toBeInTheDocument();
  });

  it("shows the engine error screen and recovers on restart", async () => {
    const u = userEvent.setup();
    const { engine, mock } = createMockEngine({ latency: 0, signedIn: true });
    mock.down = true;
    render(<App engine={engine} />);
    expect(await screen.findByText(/engine isn't responding/i)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: /restart engine/i }));
    await waitFor(() => expect(screen.getAllByText(/Dashboard/).length).toBeGreaterThan(0));
  });

  it("disables a provider that reports unavailable", async () => {
    const u = userEvent.setup();
    const { engine } = createMockEngine({ latency: 0, unavailable: ["github"] });
    render(<App engine={engine} />);
    const gh = await screen.findByTestId("github");
    await u.click(gh);
    await waitFor(() => expect(screen.getByTestId("github")).toBeDisabled());
    expect(screen.getAllByText(/not configured/i).length).toBeGreaterThan(0);
  });
});

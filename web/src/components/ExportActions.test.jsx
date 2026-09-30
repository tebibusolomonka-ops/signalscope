import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { investigation, page, researchSession, source, turn } from "../test/content.js";
import { captureDownloads } from "../test/downloads.js";
import { signedIn } from "../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../test/organizations.js";
import { renderApp } from "../test/renderApp.jsx";

const SESSION_MARKDOWN = "# Closure questions\n\n## Turn 1\n\nThe harbour closed [E1].\n";
const INVESTIGATION_MARKDOWN = "# Harbour closure\n\n## Entities\n\n- Harbour Authority\n";

function routes(extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /sources": page([source()]),
    "GET /research/sessions/rs-1": { body: researchSession() },
    "GET /research/sessions/rs-1/turns": page([turn(1)]),
    "GET /research/sessions/rs-1/export": ({ query }) =>
      query.get("format") === "markdown"
        ? { body: SESSION_MARKDOWN, type: "text" }
        : { body: { session: researchSession(), turns: [{ sequence: 1 }] } },
    "GET /investigations/inv-1": { body: investigation() },
    "GET /investigations/inv-1/items": { body: [] },
    "GET /investigations/inv-1/members": { body: [] },
    "GET /organizations/org-a/members": { body: [] },
    "GET /investigations/inv-1/export": ({ query }) =>
      query.get("format") === "markdown"
        ? { body: INVESTIGATION_MARKDOWN, type: "text" }
        : { body: { investigation: investigation(), groups: [] } },
    ...extra,
  };
}

let downloads;
afterEach(() => downloads?.restore());

async function exportGroup() {
  return screen.findByRole("group", { name: "Export" });
}

describe("exports", () => {
  it("downloads a research session as JSON and as the backend's Markdown", async () => {
    downloads = captureDownloads();
    const { calls } = renderApp({ path: "/research/rs-1", routes: routes() });
    const user = userEvent.setup();

    const group = await exportGroup();
    await user.click(within(group).getByRole("button", { name: "Export JSON" }));
    await waitFor(() => expect(downloads.files).toHaveLength(1));
    await user.click(within(group).getByRole("button", { name: "Export Markdown" }));
    await waitFor(() => expect(downloads.files).toHaveLength(2));

    const [json, markdown] = downloads.files;
    expect(json.name).toBe("signalscope-research-session-rs-1.json");
    expect(JSON.parse(await json.blob.text())).toEqual({
      session: researchSession(),
      turns: [{ sequence: 1 }],
    });
    expect(markdown.name).toBe("signalscope-research-session-rs-1.md");
    expect(await markdown.blob.text()).toBe(SESSION_MARKDOWN);
    const exportCalls = calls.filter((call) => call.path.endsWith("/export"));
    expect(exportCalls.map((call) => call.query.get("format"))).toEqual(["json", "markdown"]);
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("downloads and copies an investigation export", async () => {
    downloads = captureDownloads();
    renderApp({ path: "/investigations/inv-1", routes: routes() });
    const user = userEvent.setup();

    const group = await exportGroup();
    await user.click(within(group).getByRole("button", { name: "Export Markdown" }));
    await waitFor(() => expect(downloads.files).toHaveLength(1));
    await user.click(within(group).getByRole("button", { name: "Copy Markdown" }));

    expect(await within(group).findByText("Markdown copied.")).toBeInTheDocument();
    expect(await navigator.clipboard.readText()).toBe(INVESTIGATION_MARKDOWN);
    expect(downloads.files[0].name).toBe("signalscope-investigation-inv-1.md");
    expect(await downloads.files[0].blob.text()).toBe(INVESTIGATION_MARKDOWN);
  });

  it("names files by ID, never by title", async () => {
    downloads = captureDownloads();
    renderApp({
      path: "/investigations/inv-1",
      routes: routes({
        "GET /investigations/inv-1": { body: investigation({ title: "../../secret plans" }) },
      }),
    });
    const user = userEvent.setup();

    const group = await exportGroup();
    await user.click(within(group).getByRole("button", { name: "Export JSON" }));

    await waitFor(() => expect(downloads.files).toHaveLength(1));
    expect(downloads.files[0].name).toBe("signalscope-investigation-inv-1.json");
  });

  it("shows a failed export", async () => {
    downloads = captureDownloads();
    renderApp({
      path: "/research/rs-1",
      routes: routes({
        "GET /research/sessions/rs-1/export": {
          status: 404,
          body: { error: { code: "not_found", message: "Research session was not found." } },
        },
      }),
    });
    const user = userEvent.setup();

    const group = await exportGroup();
    await user.click(within(group).getByRole("button", { name: "Export JSON" }));

    expect(await within(group).findByRole("alert")).toHaveTextContent(
      "Research session was not found.",
    );
    expect(downloads.files).toHaveLength(0);
  });
});

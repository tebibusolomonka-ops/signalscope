import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { eventDetail, page, source } from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

const CLUSTER = {
  cluster_id: "cl-1",
  event_type: "storm",
  title: "Storm cluster",
  occurred_at: null,
  event_count: 1,
  source_count: 1,
  evidence_count: 1,
  members: [
    {
      event_id: "ev-1",
      title: "Storm closes the harbour",
      summary: null,
      occurred_at: null,
      created_at: "2026-09-05T07:00:00Z",
      evidence: [],
    },
  ],
};

it("opens an event page from a cluster member", async () => {
  renderApp({
    path: "/event-clusters/cl-1",
    routes: {
      ...signedIn(),
      ...organizations([HARBOUR, RIVER]),
      "GET /sources": page([source()]),
      "GET /investigations": page([]),
      "GET /event-clusters/cl-1": { body: CLUSTER },
      "GET /events/ev-1": { body: eventDetail() },
    },
  });
  const user = userEvent.setup();

  const article = await screen.findByRole("article", { name: "Storm closes the harbour" });
  await user.click(within(article).getByRole("link", { name: "Storm closes the harbour" }));

  expect(await screen.findByRole("region", { name: "Evidence" })).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { level: 1, name: "Storm closes the harbour" }),
  ).toBeInTheDocument();
});

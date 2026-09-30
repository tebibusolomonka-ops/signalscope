import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  doc,
  entity,
  evidence,
  investigation,
  page,
  provenance,
  savedItem,
  source,
} from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

const CLUSTER = {
  cluster_id: "cl-1",
  event_type: "storm",
  title: "Storm closes the harbour",
  occurred_at: null,
  event_count: 1,
  source_count: 1,
  evidence_count: 0,
  members: [
    {
      event_id: "ev-1",
      title: "Harbour storm",
      summary: null,
      occurred_at: null,
      created_at: "2026-09-05T07:00:00Z",
      evidence: [],
    },
  ],
};

function routes(saved, extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /investigations": ({ query }) =>
      page(
        query.get("organization_id") === "org-a"
          ? [investigation(), investigation({ id: "inv-2", title: "Fuel prices" })]
          : [],
      ),
    "POST /investigations/inv-1/items": ({ body }) => {
      saved.push(body);
      return { status: 201, body: savedItem(body.item_type, {}) };
    },
    "POST /investigations/inv-2/items": ({ body }) => {
      saved.push({ ...body, investigation: "inv-2" });
      return { status: 201, body: savedItem(body.item_type, {}) };
    },
    "GET /sources/s-1": { body: source() },
    "GET /sources/s-1/provenance": { body: provenance() },
    "GET /ingestion-runs": page([]),
    "GET /documents/d-1": { body: doc() },
    "GET /documents/d-1/revisions": { body: { items: [] } },
    "GET /entities/e-1": { body: { entity: entity(), mention_count: 1, mentions: [evidence()] } },
    "GET /claims/k-1": {
      body: {
        claim: {
          id: "k-1",
          text: "Traffic fell",
          normalized_text: "traffic fell",
          claim_type: "statistic",
          evidence_count: 1,
          created_at: "2026-09-05T07:00:00Z",
        },
        evidence_count: 1,
        evidence: [evidence()],
      },
    },
    "GET /event-clusters/cl-1": { body: CLUSTER },
    ...extra,
  };
}

async function saveFrom(user, container = screen) {
  const [open] = await container.findAllByRole("button", { name: "Save to investigation" });
  await user.click(open);
  const form = await screen.findByRole("form", { name: "Save to investigation" });
  await within(form).findByRole("option", { name: "Harbour closure" });
  return form;
}

describe("save to investigation", () => {
  it.each([
    ["/sources/s-1", "source", "s-1"],
    ["/documents/d-1", "document", "d-1"],
    ["/entities/e-1", "entity", "e-1"],
    ["/claims/k-1", "claim", "k-1"],
    ["/event-clusters/cl-1", "event_cluster", "cl-1"],
  ])("saves from %s", async (path, itemType, referenceId) => {
    const saved = [];
    renderApp({ path, routes: routes(saved) });
    const user = userEvent.setup();

    const form = await saveFrom(user);
    await user.type(within(form).getByLabelText("Note (optional)"), "Worth a look");
    await user.click(within(form).getByRole("button", { name: "Save" }));

    expect(await within(form).findByRole("status")).toHaveTextContent(
      'Saved in "Harbour closure".',
    );
    expect(saved).toEqual([
      { item_type: itemType, reference_id: referenceId, label: "Worth a look" },
    ]);
  });

  it("offers investigations from beyond the first page", async () => {
    const requested = [];
    renderApp({
      path: "/sources/s-1",
      routes: routes([], {
        "GET /investigations": ({ query }) => {
          requested.push(query.get("offset"));
          return query.get("offset") === "0"
            ? page([investigation()], { total: 2, limit: 100 })
            : page([investigation({ id: "inv-2", title: "Fuel prices" })], {
                total: 2,
                limit: 100,
                offset: 1,
              });
        },
      }),
    });
    const user = userEvent.setup();

    const form = await saveFrom(user);
    expect(within(form).getByRole("option", { name: "Fuel prices" })).toBeInTheDocument();
    // Both pages were fetched, scoped to the active organization.
    expect(requested).toEqual(["0", "1"]);
  });

  it("saves a member event of a cluster into the chosen investigation", async () => {
    const saved = [];
    renderApp({ path: "/event-clusters/cl-1", routes: routes(saved) });
    const user = userEvent.setup();

    const member = await screen.findByRole("article", { name: "Harbour storm" });
    const form = await saveFrom(user, within(member));
    await user.selectOptions(within(form).getByLabelText("Investigation"), "inv-2");
    await user.click(within(form).getByRole("button", { name: "Save" }));

    await within(form).findByRole("status");
    expect(saved).toEqual([{ item_type: "event", reference_id: "ev-1", investigation: "inv-2" }]);
  });

  it("offers only open investigations of the active organization", async () => {
    const { calls } = renderApp({ path: "/entities/e-1", routes: routes([]) });
    const user = userEvent.setup();

    await saveFrom(user);
    const call = calls.find((item) => item.path === "/investigations");
    expect(call.query.get("status")).toBe("open");
    expect(call.query.get("organization_id")).toBe("org-a");
  });

  it("says when there is no open investigation", async () => {
    renderApp({ path: "/entities/e-1", routes: routes([], { "GET /investigations": page([]) }) });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Save to investigation" }));
    expect(await screen.findByText(/There is no open investigation/)).toBeInTheDocument();
  });

  it("treats an item that is already saved as saved", async () => {
    renderApp({
      path: "/entities/e-1",
      routes: routes([], {
        "POST /investigations/inv-1/items": {
          status: 409,
          body: {
            error: {
              code: "conflict",
              message: "This item is already saved in the investigation.",
            },
          },
        },
      }),
    });
    const user = userEvent.setup();

    const form = await saveFrom(user);
    await user.click(within(form).getByRole("button", { name: "Save" }));

    expect(await within(form).findByRole("status")).toHaveTextContent(
      'Already saved in "Harbour closure".',
    );
    expect(within(form).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows other refusals, such as a closed investigation", async () => {
    renderApp({
      path: "/entities/e-1",
      routes: routes([], {
        "POST /investigations/inv-1/items": {
          status: 409,
          body: { error: { code: "conflict", message: "Investigation is closed." } },
        },
      }),
    });
    const user = userEvent.setup();

    const form = await saveFrom(user);
    await user.click(within(form).getByRole("button", { name: "Save" }));

    expect(await within(form).findByRole("alert")).toHaveTextContent("Investigation is closed.");
  });

  it("removes an item after confirmation, and not from a closed investigation", async () => {
    const removed = [];
    let items = [
      savedItem("entity", { canonical_name: "Harbour Authority", entity_type: "organization" }),
    ];
    renderApp({
      path: "/investigations/inv-1",
      routes: routes([], {
        "GET /investigations/inv-1": { body: investigation() },
        "GET /investigations/inv-1/items": () => ({ body: items }),
        "DELETE /investigations/inv-1/items/item-entity": () => {
          removed.push("item-entity");
          items = [];
          return { status: 204 };
        },
      }),
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Remove Harbour Authority" }));
    await user.click(screen.getByRole("button", { name: "Yes, remove" }));

    expect(await screen.findByText("Nothing is saved yet.")).toBeInTheDocument();
    expect(removed).toEqual(["item-entity"]);
  });

  it("hides remove on a closed investigation", async () => {
    renderApp({
      path: "/investigations/inv-1",
      routes: routes([], {
        "GET /investigations/inv-1": { body: investigation({ status: "closed" }) },
        "GET /investigations/inv-1/items": {
          body: [
            savedItem("entity", {
              canonical_name: "Harbour Authority",
              entity_type: "organization",
            }),
          ],
        },
      }),
    });

    await screen.findByText("Harbour Authority");
    expect(screen.queryByRole("button", { name: /^Remove/ })).not.toBeInTheDocument();
  });

  it("offers nothing of the old organization after switching", async () => {
    renderApp({ path: "/entities/e-1", routes: routes([]) });
    const user = userEvent.setup();

    await saveFrom(user);
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() => expect(screen.queryByText("Harbour closure")).not.toBeInTheDocument());
    await user.click(await screen.findByRole("button", { name: "Save to investigation" }));
    expect(await screen.findByText(/There is no open investigation/)).toBeInTheDocument();
  });
});

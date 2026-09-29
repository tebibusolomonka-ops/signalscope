import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { doc, held, page, source } from "../../test/content.js";
import { USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

const LIMITS = {
  body: { content_types: ["application/pdf", "text/plain"], max_bytes: 50 * 1024 * 1024 },
};
const UPLOADS = source({ id: "s-up", name: "Harbour Files", type: "upload", url: null });

function routes(extra = {}, role = "member", user = USER) {
  return {
    ...signedIn(user),
    ...organizations([HARBOUR, RIVER], role),
    "GET /documents/files/limits": LIMITS,
    "GET /sources": page([source(), UPLOADS]),
    ...extra,
  };
}

function textFile(name = "notes.txt", text = "Harbour notes", type = "text/plain") {
  return new File([text], name, { type });
}

async function form() {
  return screen.findByRole("region", { name: "File" });
}

describe("file import", () => {
  it("uploads the selected file to an upload source of the active organization", async () => {
    const uploads = [];
    renderApp({
      path: "/documents/import",
      routes: routes({
        "POST /documents/files": (request) => {
          uploads.push(request);
          return {
            status: 201,
            body: {
              document: doc({ id: "d-new", title: "notes" }),
              filename: "notes.txt",
              content_type: "text/plain",
              size_bytes: 13,
              processing_job_id: "j-1",
            },
          };
        },
      }),
    });
    const user = userEvent.setup();

    const section = await form();
    const picker = await within(section).findByLabelText("Upload source");
    expect(
      within(picker)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Harbour Files"]);
    await user.upload(within(section).getByLabelText("File"), textFile());
    expect(within(section).getByText("Selected: notes.txt (13 bytes)")).toBeInTheDocument();
    await user.click(within(section).getByRole("button", { name: "Import file" }));

    const done = await within(section).findByRole("status");
    expect(done).toHaveTextContent("notes.txt was stored and queued for processing.");
    expect(within(done).getByRole("link", { name: "Open the document" })).toHaveAttribute(
      "href",
      "/documents/d-new",
    );
    expect(uploads).toHaveLength(1);
    const [upload] = uploads;
    expect(upload.query.get("organization_id")).toBe("org-a");
    expect(upload.query.get("source_id")).toBe("s-up");
    expect(upload.query.get("filename")).toBe("notes.txt");
    expect(upload.options.headers["Content-Type"]).toBe("text/plain");
    expect(upload.body).toBeInstanceOf(File);
  });

  it("names the type from the extension when the browser gives none", async () => {
    const uploads = [];
    renderApp({
      path: "/documents/import",
      routes: routes({
        "POST /documents/files": (request) => {
          uploads.push(request);
          return { status: 400, body: { error: { code: "x", message: "Stop." } } };
        },
      }),
    });
    const user = userEvent.setup({ applyAccept: false });

    const section = await form();
    await within(section).findByLabelText("Upload source");
    await user.upload(within(section).getByLabelText("File"), textFile("report.pdf", "%PDF", ""));
    await user.click(within(section).getByRole("button", { name: "Import file" }));

    await within(section).findByRole("alert");
    expect(uploads[0].options.headers["Content-Type"]).toBe("application/pdf");
  });

  it("refuses a type the API does not list before uploading", async () => {
    const { calls } = renderApp({ path: "/documents/import", routes: routes() });
    const user = userEvent.setup({ applyAccept: false });

    const section = await form();
    await within(section).findByLabelText("Upload source");
    await user.upload(
      within(section).getByLabelText("File"),
      textFile("photo.png", "png", "image/png"),
    );

    expect(within(section).getByRole("alert")).toHaveTextContent(
      "photo.png is not a supported file type.",
    );
    expect(within(section).getByRole("button", { name: "Import file" })).toBeDisabled();
    expect(calls.some((call) => call.path === "/documents/files")).toBe(false);
  });

  it("shows the API's refusal", async () => {
    renderApp({
      path: "/documents/import",
      routes: routes({
        "POST /documents/files": {
          status: 422,
          body: { error: { code: "invalid_input", message: "File is larger than 50 MB." } },
        },
      }),
    });
    const user = userEvent.setup();

    const section = await form();
    await within(section).findByLabelText("Upload source");
    await user.upload(within(section).getByLabelText("File"), textFile());
    await user.click(within(section).getByRole("button", { name: "Import file" }));

    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "File is larger than 50 MB.",
    );
  });

  it("explains when there is no upload source", async () => {
    renderApp({ path: "/documents/import", routes: routes({ "GET /sources": page([source()]) }) });

    expect(
      await screen.findByText(/this organization has none/, { exact: false }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("File", { selector: "input" })).not.toBeInTheDocument();
  });

  it("tells viewers they cannot import", async () => {
    renderApp({ path: "/documents/import", routes: routes({}, "viewer") });

    expect(
      await screen.findByText("Your role in this organization cannot add documents."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("File", { selector: "input" })).not.toBeInTheDocument();
  });

  it("clears the selected file and result when switching organization", async () => {
    const river = held();
    renderApp({
      path: "/documents/import",
      routes: routes({
        "GET /sources": async ({ query }) => {
          if (query.get("organization_id") === "org-b") {
            await river.ready;
            return page([source({ id: "s-rup", name: "River Files", type: "upload" })]);
          }
          return page([UPLOADS]);
        },
      }),
    });
    const user = userEvent.setup();

    const section = await form();
    await within(section).findByLabelText("Upload source");
    await user.upload(within(section).getByLabelText("File"), textFile());
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() => expect(screen.queryByText(/Selected: notes.txt/)).not.toBeInTheDocument());
    expect(screen.queryByText("Harbour Files")).not.toBeInTheDocument();
    river.release();
    expect(await screen.findByRole("option", { name: "River Files" })).toBeInTheDocument();
    expect(screen.queryByText(/Selected:/)).not.toBeInTheDocument();
  });
});

import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { EvidenceReference } from "./EvidenceReference.jsx";

function show(props) {
  return render(
    <MemoryRouter>
      <EvidenceReference {...props} />
    </MemoryRouter>,
  );
}

const FULL = {
  documentId: "d-1",
  documentTitle: "Storm report",
  sourceId: "s-1",
  sourceName: "Harbour Feed",
  metadata: { page_number: 2 },
};

describe("EvidenceReference", () => {
  it("links the document and the source and shows the location", () => {
    show(FULL);

    expect(screen.getByRole("link", { name: "Storm report" })).toHaveAttribute(
      "href",
      "/documents/d-1",
    );
    expect(screen.getByRole("link", { name: "Harbour Feed" })).toHaveAttribute(
      "href",
      "/sources/s-1",
    );
    expect(screen.getByText("Page 2")).toBeInTheDocument();
  });

  it("shows a citation id and a cited marker when given", () => {
    show({ ...FULL, citationId: "E1", cited: true });

    expect(screen.getByText("E1", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("cited")).toBeInTheDocument();
  });

  it("falls back when the title is missing", () => {
    show({ ...FULL, documentTitle: null });

    expect(screen.getByRole("link", { name: "Open document" })).toHaveAttribute(
      "href",
      "/documents/d-1",
    );
  });

  it("says the source is unknown when there is no source", () => {
    show({ ...FULL, sourceId: null, sourceName: null });

    expect(screen.getByText("Source unknown")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Harbour Feed" })).not.toBeInTheDocument();
  });

  it("focuses a chunk in the document link when chunkId is given", () => {
    show({ ...FULL, chunkId: "c-9" });

    expect(screen.getByRole("link", { name: "Storm report" })).toHaveAttribute(
      "href",
      "/documents/d-1?chunk=c-9",
    );
  });

  it("shows the title as plain text when there is no document", () => {
    show({ ...FULL, documentId: null });

    expect(screen.queryByRole("link", { name: "Storm report" })).not.toBeInTheDocument();
    expect(screen.getByText("Storm report")).toBeInTheDocument();
  });

  it("omits the document link when a heading already shows it", () => {
    const { container } = show({ ...FULL, showDocument: false });

    expect(screen.queryByRole("link", { name: "Storm report" })).not.toBeInTheDocument();
    expect(within(container).getByRole("link", { name: "Harbour Feed" })).toBeInTheDocument();
  });
});

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { DocumentLink, EvidenceReference, SourceLink } from "./references.jsx";

function draw(node) {
  return render(<MemoryRouter>{node}</MemoryRouter>);
}

describe("references", () => {
  it("links to a document by its title, with a fallback", () => {
    const { rerender } = draw(<DocumentLink documentId="d-1" title="Storm" />);
    expect(screen.getByRole("link", { name: "Storm" })).toHaveAttribute("href", "/documents/d-1");

    rerender(
      <MemoryRouter>
        <DocumentLink documentId="d-1" title={null} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Untitled document" })).toBeInTheDocument();
  });

  it("links to a source by its name", () => {
    draw(<SourceLink sourceId="s-1" name="Harbour Feed" />);
    expect(screen.getByRole("link", { name: "Harbour Feed" })).toHaveAttribute(
      "href",
      "/sources/s-1",
    );
  });

  it("shows the document, source and location together", () => {
    draw(
      <EvidenceReference
        documentId="d-1"
        documentTitle="Storm"
        sourceId="s-1"
        sourceName="Harbour Feed"
        chunkMetadata={{ page_number: 3 }}
      />,
    );
    expect(screen.getByRole("link", { name: "Storm" })).toHaveAttribute("href", "/documents/d-1");
    expect(screen.getByRole("link", { name: "Harbour Feed" })).toHaveAttribute(
      "href",
      "/sources/s-1",
    );
    expect(screen.getByText(/Page 3/)).toBeInTheDocument();
  });
});

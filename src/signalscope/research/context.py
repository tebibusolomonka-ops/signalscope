from collections.abc import Sequence

from signalscope.research.evidence import ResearchEvidence


def context_text(evidence: Sequence[ResearchEvidence]) -> str:
    """Write the evidence as numbered blocks that a model can cite by ID.

    The output only depends on the evidence, so the same evidence always gives
    the same text:

        [E1]
        Title: Harbour flooding
        URL: https://example.com/flood
        Page: 2
        Text: Heavy rain flooded the harbour district.
    """
    blocks = []
    for item in evidence:
        lines = [f"[{item.evidence_id}]", f"Title: {item.title or '(no title)'}"]
        if item.url:
            lines.append(f"URL: {item.url}")
        page = item.chunk_metadata.get("page_number")
        if page is not None:
            lines.append(f"Page: {page}")
        lines.append(f"Text: {item.text.strip()}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)

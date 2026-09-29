# Project Overview

SignalScope is a media intelligence and research platform. It collects content
from sources, turns it into structured, searchable information, and answers
research questions with citations to that content.

This vault is project memory for maintainers and coding agents. The code and
migrations are the source of truth. When a note disagrees with the code,
follow the code and fix the note.

## Main use cases

- Collect articles from RSS feeds and web pages, and import local files
  (text, JSON, HTML, PDF, DOCX).
- Search the collected text by words, by meaning, or both, with optional
  reranking.
- Find entities, events and claims in the text, and see which chunks back them.
- Link reports of the same event across documents and read them as a timeline.
- See what has been observed about a source, as counts and dates.
- Ask a research question and get an answer that cites the evidence it used,
  also as a multi-turn session.
- Save sources, events, claims and research sessions into investigations,
  and export sessions and investigations as JSON or Markdown.
- Read factual dashboard aggregates: counts and daily activity.
- With authentication on: sign in, organizations with roles and invitations,
  investigations shared with collaborators, user administration for system
  admins, and a security audit log.
- Administer users, organizations, invitations, sessions and the audit log in
  the web app, and do the research work there too: sources, documents, file
  import, search, entities, claims, events, source comparison,
  investigations and research sessions, one organization at a time.

## Data flow

1. A source is ingested (network) or a file is imported. Raw files go to the
   blob store.
2. A processing job parses the file into document text and section-aware
   chunks. Changed content keeps the earlier state as a revision.
3. Chunks are queued for embedding, entity, event and claim extraction. Each
   kind has its own job table and worker.
4. Search and research read chunks, embeddings and extracted data from
   PostgreSQL.

See [[01 Architecture]] for the layers and [[05 Workers and Queues]] for the jobs.

## Maturity

Early development. There is an HTTP API, a command line and an internal web
app (`web/`) for research and administration. Optional authentication (off by default) adds accounts,
organizations and shared investigations, and splits all content by
organization. Local models are optional and off
by default. Real model quality has not been measured yet; see
[[08 Known Issues]].

Current details: [[02 Current State]]. Planned work: [[10 Next Work]].

# Known Issues

Open problems as of commit 239. Remove an item when it is fixed.

## Events

- Empty-cluster cleanup can race with linking: if an empty cluster is deleted
  while a linker is adding an event to it, that link fails. The event stays
  unclustered and `link-events` repairs it.
- The linker only ever joins exact matches; near-duplicate titles stay in
  separate clusters. Semantic suggestions show them but do not merge them.
- Event date parsing is deliberately conservative: ISO dates and English month
  names only. Other dates are kept as text in evidence metadata.

## Models

- Real extraction quality (GLiNER, GLiNER2) has not been measured. Event and
  claim evaluation code exists, but there is no command to run it on a real
  model yet, and no reference dataset.
- GLiNER2 relation extraction has not been evaluated.
- Real local models do not run in normal CI; only fakes do. The smoke check
  commands are the way to try a real model.
- GLiNER2 extracts spans, so a claim's `text` usually repeats its quote.

## Code

- The entity, event and claim queues, repositories, workers and coverage
  services are close copies of each other.

See [[10 Next Work]] for what is planned.

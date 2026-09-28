# Known Issues

Open problems as of commit 230. Remove an item when it is fixed.

## Events

- Nothing runs `EventLinkingService` automatically. Events stay unclustered,
  and the timeline stays empty, until code calls it.
- Event clusters whose member events are all deleted stay behind. The timeline
  hides them because it joins on members.
- Event date parsing is deliberately conservative: ISO dates and English month
  names only. Other dates are kept as text in evidence metadata.

## Models

- Real extraction quality (GLiNER, GLiNER2) has not been measured.
- GLiNER2 relation extraction has not been evaluated.
- Real local models do not run in normal CI; only fakes do. The smoke check
  commands are the way to try a real model.
- GLiNER2 extracts spans, so a claim's `text` usually repeats its quote.

## Code

- The entity, event and claim queues, repositories, workers and coverage
  services are close copies of each other.

See [[10 Next Work]] for what is planned.

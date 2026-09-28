# Next Work

Planned for the current batch (commits 230 to 249). None of this is done
unless [[02 Current State]] says so. Done so far: the vault, the loader check,
event and claim scoring, automatic linking with a repair command and cluster
cleanup, suggestion and comparison services. Still to do: the comparison
route, research sessions, relation extraction and the extraction benchmark
command.

1. Keep this vault as project memory, updated at each checkpoint.
2. Check the GLiNER2 loader arguments against the library.
3. Extraction evaluation: datasets and precision, recall and F1 for events,
   claims and later relations. No quality targets.
4. Run exact event linking after event extraction, add a repair command, and
   delete empty event clusters.
5. Semantic event link suggestions with embeddings. Suggestions only; they
   never change clusters.
6. Factual side-by-side source comparison. No scores or rankings.
7. Multi-turn research sessions. Earlier answers are conversation context,
   not evidence; each answer cites current evidence.
8. Relation extraction interface, an experimental GLiNER2 relation provider
   and its evaluation. No relations are stored.

Rules for this work: [[07 Decisions]].

# Agent rules

Rules for anyone, human or coding agent, working on this repository.

## Project

SignalScope is a media intelligence and research platform. Over time it will
process articles, websites, RSS feeds, documents, audio and video.

The project is built step by step. Only build what the current task asks for.
Do not add future features, services or dependencies early.

## Writing

- Use simple, plain English in code, comments, docstrings, docs, error
  messages and commit messages.
- No emojis.
- Only add a comment when the reason behind the code is not obvious. Keep it
  short.
- Add docstrings only when the behavior needs explaining.

## Code

- Python 3.12 or newer.
- The package lives in `src/signalscope`.
- Use type hints.
- Use pytest. Tests go in `tests/unit` and `tests/integration`.
- Prefer clear code over clever code.
- No filler code, placeholder features or abstractions that nothing uses yet.

## Git

- One real unit of work per commit. Do not mix unrelated changes.
- Short commit messages in simple English, for example `Add application settings`.
- No AI attribution anywhere. No `Co-Authored-By` lines for AI tools and no
  "Generated with" notes in commits, pull requests or files.
- Use the Git identity that is already configured. Do not change `user.name`
  or `user.email`.
- Do not push unless asked.
- Before each commit, read the diff and run the checks below. Commit only when
  they pass.

## Checks

Install with `pip install -e ".[dev]"`, then run:

```bash
pytest
ruff check .
ruff format --check .
mypy src
```

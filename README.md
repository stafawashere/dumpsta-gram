# Dumpstagram

Two products in one repository.

| Path | Product | Language | Role |
|---|---|---|---|
| `engine/` | Dumpsta-Engine | Python 3.12+ | The engine. All Instagram capability lives here. |
| `client-app/` | Dumpsta-App | Swift (macOS) | Open-source client built on the engine. |

Dumpsta-Engine is a library with a stable, high-level public API for talking to Instagram.
Dumpsta-App is a macOS client that embeds it and serves as the reference implementation.

## Status

Early. The documentation and the architecture decisions are written, the product code is not.
The engine is built first and the app follows once the engine's public API stops changing.

## Requirements

- [uv](https://docs.astral.sh/uv/) for everything Python. No pip, no venv, no bare python3.
- CPython 3.12 or newer, which uv installs and pins for you.
- macOS for the app. The engine itself is not macOS specific.

## Getting started

```
cd engine
uv sync
uv run python -c "import dumpstagram"
```

Copy `.env.example` to `.env` and fill it in with cookie material from a browser session you
own. `.env` is ignored by git and must never be committed.

## Documentation

- `docs/` for cross-cutting material, the glossary, measured findings, and known risks.
- `engine/docs/` for the engine: public API, sessions and auth, pacing, events.
- `client-app/docs/` for the client: architecture, Python integration, build and packaging.

## Warning

This project targets an undocumented, unofficial API. Using it is against Instagram's terms of
service and can get an account restricted or banned. Endpoints change without notice. Pacing
defaults are deliberately conservative for that reason. Use it on accounts you own and accept
the risk yourself.

## License

MIT. See [LICENSE](LICENSE).

## Note

This README is a placeholder. A fuller one replaces it once there is working code to describe.

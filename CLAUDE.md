# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant add-on, **Wine Tracker** — a Flask web app (server-rendered Jinja templates + vanilla JS) to track a wine cellar, with AI wine-label recognition and an AI "sommelier" chat across 6 pluggable providers. It is installed as an HA add-on directly from this Git repository and built locally on the user's Home Assistant machine. This repo is a fork of `xenofex7/ha-wine-tracker`.

## Commands

- **Dev server** (needs a repo-root `.venv`):
  ```
  python3.12 -m venv .venv && .venv/bin/pip install -r wine-tracker/requirements.txt
  scripts/run-dev.sh          # serves http://localhost:5050
  ```
- **Standalone via Docker:** `docker compose up --build` (root `docker-compose.yaml`, port 5050; configure with env vars / `.env` — `AI_PROVIDER`, `OPENAI_API_KEY`, `LANGUAGE`, `CURRENCY`, `AUTH_ENABLED`).
- **Tests** (run from repo root; `conftest.py` gives each test a fresh temp DB and default options, so no real data is touched):
  ```
  .venv/bin/python -m pytest wine-tracker/tests/
  ```
  Single test: `pytest wine-tracker/tests/test_routes.py::TestApiSummary -k test_name`
- **Python 3.12** is the supported version (Dockerfile + CI). `Pillow` is pinned `<11` and has no wheel for 3.13/3.14 — on a newer local Python, build the venv with 3.12, or override Pillow (`pip install 'Pillow>=11'`) for test runs only.
- **CI** (`.github/workflows/docker-publish.yml`) runs pytest then builds/pushes the GHCR image — it triggers **only on `v*` tags**, not on branch pushes.

## Architecture

- **Almost everything lives in `wine-tracker/app/app.py`** (~3150 lines): the Flask app is created at the top and every route is inline (no blueprints). Helper modules beside it: `translations.py` (i18n) and `export_import.py` (zip backup/restore).
- **Startup config flow:** `load_options()` builds the `HA_OPTIONS` dict from `/data/options.json` (which HA generates from the `options:` in `config.yaml`), with environment-variable overrides for standalone Docker. The globals `LANG`, `T` (active translation map) and currency are derived from it once at boot. `init_db()` creates the SQLite schema **and applies in-place column migrations on every boot** — add new columns there.
- **Data:** SQLite at `$DATA_DIR/wine.db` (`/data/wine-tracker` in Docker, `/share/wine-tracker` under HA). Per-request connection via `get_db()`. Tables: `wines`, `timeline` (audit log of every add/consume/restock/remove/chat action), `chat_sessions` + `chat_messages`, `filter_presets`. Rich fields (`maturity_data`, `taste_profile`, `food_pairings`) are JSON stored in text columns.
- **AI providers** (`anthropic`, `openai`, `openrouter`, `ollama`, `minimax`, `mistral`): each is a vision call + a chat call, dispatched by `ai_provider` through `_call_chat()`. Only the `anthropic` and `openai` SDKs are dependencies — the others use HTTP / OpenAI-compatible endpoints. Label recognition (`/api/analyze-wine`) prompts the model to return structured JSON about a bottle photo; the sommelier chat (`/api/chat`) injects current-cellar context and, when "edit wines via chat" is enabled, lets the model emit `[ADD_WINE]{...}` action blocks that are parsed and applied after the response.
- **i18n:** the `TRANSLATIONS` dict in `translations.py` covers **7 languages** (de/en/fr/it/es/pt/nl), default `de`. Any new user-facing string must be added to **all** languages. The `wine_type` template filter maps the German DB labels to the active UI language.
- **HA ingress:** the app is proxied under a per-session token path. `g.ingress` is read from the `X-Ingress-Path` header and **every template URL must be prefixed with `{{ ingress }}`** — never hardcode absolute URLs.
- **`/api/summary`** feeds HA REST sensors and deliberately returns **English** wine-type labels regardless of UI language, so sensor values stay stable.

## Versioning & releases

- The add-on version is `version:` in `wine-tracker/config.yaml` — **this is the only field Home Assistant uses to decide an update is available.** Changing code without bumping it ships nothing to users.
- That version string is duplicated in several files that must stay in sync: `wine-tracker/config.yaml`, `wine-tracker/app/app.py` (`APP_VERSION`), `wine-tracker/tests/test_routes.py` (assertion), the version badges in `README.md`, `wine-tracker/README.md`, `wine-tracker/DOCS.md`, and `docs/llms.txt`.
- Cut releases with `scripts/deploy.sh vX.Y.Z`. It runs tests, bumps every version file, reads a **pre-written** `## X.Y.Z` section from `CHANGELOG.md` (add it first — the script will not generate it), mirrors `CHANGELOG.md` → `wine-tracker/CHANGELOG.md`, commits `Release vX.Y.Z`, tags, pushes, and creates a GitHub Release. The `v*` tag is what triggers the CI image build.
- The version bump must land on the repository's **default branch** (currently `master`) — that is the branch Home Assistant tracks.

## Home Assistant update flow

- `config.yaml` has **no `image:` key**, so HA builds the add-on locally from `docker/Dockerfile` on the user's machine. The GHCR image produced by CI is used only by `docker-compose`, **not** by the add-on — so a missing/failed image build does not affect HA updates.
- An update only surfaces when `config.yaml` `version:` on the tracked branch is greater than the installed version. To make HA notice a fresh release immediately: **Add-on Store → ⋮ → Check for updates** (the Supervisor otherwise polls roughly daily).
- HA's frontend caches the add-on detail page aggressively: if the add-on list shows "Update available" but the detail page still says up-to-date, hard-refresh the browser or restart the Companion app.

## Conventions

- Use plain hyphens, not em/en-dashes, in user-facing text (see `STYLE_GUIDE.md`).
- This is a fork — keep the upstream `LICENSE` copyright notice intact.

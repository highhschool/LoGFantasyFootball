# NGFL Drafter — Web App Plan

Status: v3 (2026-08-27). P0 and P1 shipped. Working document — we edit as we go.

## Locked decisions

| Question | Call |
|---|---|
| Modes in v1 | Mock Sandbox (vs AI) **and** Live Draft Assistant |
| Multi-user shared session | Phase 4, not v1 |
| Hosting | Home machine (Windows box), Docker, Cloudflare named tunnel |
| Domain | **`ngfldrafter.com`**, registered on Cloudflare Registrar. App serves from the apex. |
| Keepers | **Optional everywhere.** No keepers is the default and a fully valid draft. |
| Relationship to `FantasyDrafterAI/` | **None at runtime.** Fresh port, and ADP now comes from the same public API the tool uses. |

**Hard constraint:** `FantasyDrafterAI/` is owned by another session. Read-only. All new code lives in `DrafterWeb/`.

---

## Data source (revised)

**Originally** the webapp read the CSVs `build_rankings.py` produces, treating
that directory as the contract between the two projects.

**Now** the webapp calls the ADP API directly -- the same public Fantasy
Football Calculator endpoint `build_rankings.py` itself calls. The CSV seam is
gone.

Why the change:

- **The webapp is deployable on its own.** Before, a standalone checkout had no
  rankings and booted degraded with 0 players, which quietly made the
  "rent a VPS for draft week" plan impossible.
- **No drift.** Both projects derive from the same upstream rather than one
  depending on the other's output format, so the schema guard's whole failure
  mode disappears.
- **Provenance survives.** `build_rankings.py` logs the draft count and date
  range, then discards them when writing CSVs, so a four-month-old file looks
  identical to a fresh one. Fetching directly keeps them, and the UI shows
  "ADP 2 minutes ago, 7,986 drafts".

The cost is a runtime network dependency, contained by caching every successful
fetch to `data/adp-cache/`. A cache inside its TTL is served without a request;
a failed fetch falls back to the last good cache and flags it **stale** in both
the UI and `/api/health`. A third party being down cannot take the site out.

`RANKINGS_DIR` remains as an explicit CSV override for hand-curated rankings.
`build_rankings.py` is unaffected and still required by `DrafterAI.py`.

## Core architecture: picks are events, state is derived

    DraftState = reduce(config, picks[])

Nothing mutates a player pool in place. This one decision buys almost everything else:

- **Undo is free** — drop the last pick. Someone always misheard a name on draft night.
- **Both v1 modes are the same engine**, differing only in each pick's *source*:
  `user | bot | keeper | sleeper | manual | remote`
  - Mock sandbox: your slot is `user`, the other 11 are `bot`
  - Live assistant: all slots are `sleeper`, with `manual` as fallback
  - Phase 4: other slots become `remote` — broadcast the event, every client re-derives
- **Replay and export** — a session is just config plus an ordered pick list, which is a JSON file you can save, reload, or hand me for debugging.

This is the main departure from the current tool, where `update_dataframes_with_pick()` destructively drops rows from seven DataFrames — so there is no undo, no replay, and no way to have two drafts in flight.

---

## Layout

    DrafterWeb/
      backend/
        app/
          main.py              FastAPI entry
          api/                 sessions, picks, players, sleeper routes
          core/
            models.py          Player, DraftConfig, Pick, DraftState
            adp.py             ADP fetch + disk cache + provenance
            rankings.py        pool building; CSV override loader
            engine.py          pure reducer (config, picks) -> state
            order.py           snake order + keeper slotting
            bots.py            AI pick strategies
            advisor.py         recommendation scoring
            names.py           Sleeper <-> FFC name resolution
          integrations/sleeper.py
          db.py                SQLite
        tests/
      frontend/                React + TS + Vite + Tailwind
      data/                    sqlite volume
      docker-compose.yml
      Caddyfile

---

## Feature design

### Keepers are optional

Since the 2026 keepers are not settled, and since that code is being reworked on the other session, keepers are an **optional overlay** rather than a precondition:

- **The default is an empty keeper list**, which produces a plain snake draft. Every screen, every mode, and every test works in that state. Nothing is gated behind configuring keepers.
- Keeper support lives in the data model from day one — `DraftConfig.keepers: list[Keeper] = []` — so turning it on later is data, not a refactor.
- A keeper is `(team_slot, round, player_name)`. The engine pre-fills those cells before the draft runs and skips them in the pick loop.
- **Unresolvable keeper names warn, never crash.** The current `validate_keepers()` raises a `ValueError` that kills the whole run when a name does not match. In a webapp that would take down everyone's session over one typo, so it becomes a warning surfaced in the UI next to the offending name, with the draft still fully usable.
- **In assistant mode, keepers need no configuration at all.** Sleeper's picks feed already carries an `is_keeper` flag per pick, so the live board learns them from the draft itself.

Net effect: keeper config UI drops out of P1's critical path and lands in P2, but nothing about the model has to change when it does.

### Mock sandbox

Config screen: year, teams, rounds, your slot, position limits, and optionally keepers. All the things currently hardcoded as class constants and a literal dict in `initialize_keeper_assignments()`.

**Bots need ADP randomization.** Today's `select_best_available_player()` takes `iloc[0]` of the ADP-sorted pool, so every mock draft is byte-identical and worthless for prep. Fix: sample each bot pick from a normal distribution around ADP using the `HIGH`, `LOW`, and `STDEV` columns — already in your CSVs, currently unused. Every sim becomes a different, plausible draft.

Controls: step one pick, sim to my next pick, sim to end. Results screen with roster grid, positional strength, bye conflicts.

Later: bot personalities (zero-RB, QB reacher, homer).

### Live assistant — Sleeper auto-sync

Verified working against league `1261437958930563072`:

- `GET /v1/league/<id>/drafts` returns `draft_id`, type `snake`, 15 rounds, 12 teams — matches the tool's constants exactly
- `GET /v1/draft/<id>/picks` returns 180 picks with `round`, `pick_no`, `draft_slot`, player name/position/team, and `is_keeper`

Paste the draft URL, poll every ~3s, the board fills itself. **No typing during the draft.** Manual entry stays as the fallback path.

*Name-join risk:* Sleeper says "Patrick Mahomes II", FFC says "Patrick Mahomes" — the exact mismatch `validate_keepers()` already documents. Mitigation: match on a normalized `(name, position, team)` triple with suffixes and punctuation stripped. Anything unresolved surfaces in the UI for a one-click manual mapping, cached to SQLite so each name is fixed once, permanently.

### The advisor

All computable from columns already in the CSVs — no new data source needed:

1. **Survival probability** — P(player is still available at your next pick), from ADP and STDEV via the normal CDF. The single most useful number on draft night: *"Chase 4% to last, McBride 71% — take Chase now."*
2. **Tier breaks** — cluster ADP gaps within a position. *"Last RB in tier 2; next tier is a 14-pick drop-off."*
3. **Value vs ADP** — how far past their ADP a player has fallen.
4. **Roster need** — position limits plus real starter slots, pulled live from your Sleeper league settings (QB/2RB/2WR/TE/2FLEX/K/DEF plus 5 BN).
5. **Bye stacking** — warn when 3 or more starters share a bye week.

Composite score with each factor displayed, so it is explainable rather than a black box. If you later add a projections feed, this upgrades cleanly to true VOR/VBD.

---

## Stack

- **Backend:** FastAPI + Pydantic + SQLModel/SQLite. No pandas in the webapp — 267 rows does not need it, and the stdlib `csv` module keeps the image small and startup instant. (`build_rankings.py` keeps pandas; it lives on the other side of the seam.)
- **Frontend:** React + TypeScript + Vite + Tailwind. Justified by board density, keyboard-driven player search, the timer, and phase-4 websockets.
  - *Lighter alternative if you would rather stay all-Python:* FastAPI + Jinja + HTMX. One container, no build step. Perfectly workable for v1 — but phase 4 gets meaningfully harder.
- **Storage:** SQLite on a mounted volume. Nightly copy out for backup.
- **Auth:** Cloudflare Access in front (Google login, free under 50 users, **zero auth code in the app**) plus a display-name cookie inside. Do not build password auth.
- **Deploy:** `docker compose` — api, static web via Caddy, cloudflared. Lands on `draft.<yourdomain>`.

---

## Hosting: resolved

**Cloudflare will not host this well.** Their Containers product can run a FastAPI process, but it requires the Workers Paid plan at $5/mo, and containers sleep with ephemeral disk — so SQLite would have to be rewritten onto D1 or R2. That is $60/yr plus a storage rewrite to solve a problem your desktop already solves for free.

**A named tunnel needs a domain**, because the hostname has to live in a Cloudflare zone. Without one, `cloudflared` only offers *quick tunnels*: a random `*.trycloudflare.com` URL that changes on every restart, which Cloudflare explicitly documents as unsuitable for production. Fine for development, useless for handing eleven friends a link.

So:

| | Cost | Verdict |
|---|---|---|
| Cloudflare Containers | $5/mo + storage rewrite | Rejected |
| Quick tunnel, no domain | Free, but the URL changes every restart | Dev only |
| **Domain + named tunnel, home host** | **~$10.44/yr** | **Chosen** |

The domain also unlocks **Cloudflare Access**, which is what saves us from writing any authentication code at all. One purchase covers hosting, a stable URL, HTTPS, and auth.

*Buy any TLD you like — a `.com` is $10.44/yr at cost. Cheaper TLDs exist. Note that Cloudflare Registrar requires the domain to use Cloudflare nameservers, which is what we want anyway.*

**Windows host notes:** Docker Desktop with the WSL2 backend; set the containers to restart automatically; and disable sleep and hibernate in the power plan, because a sleeping PC during the draft is the single most likely way this falls over.

**Development path:** P0 uses a quick tunnel so nothing is blocked on the domain purchase. Swapping to a named tunnel is one config file.

---

## Phases

**P0 — Foundation.** Scaffold, `docker compose up` serving a page over the tunnel, rankings loader + schema guard, core models, snake-order and keeper-slotting with unit tests.
→ *Deliverable: a URL your friends can load.*

**P1 — Mock sandbox.** Engine reducer, bots with ADP randomization, config screen, draft board, results.
→ *Deliverable: a playable mock draft.*

**P2 — Live assistant.** Sleeper polling, name resolution, manual fallback, advisor panel, roster/needs sidebar, undo.
→ *Deliverable: usable on draft night.*

**P3 — Harden.** Cloudflare Access, backups, session resume, mobile layout (everyone will be on phones during the draft), graceful handling of Sleeper being down.

**P4 — Multi-user room.** Websocket broadcast, lobby, identity, pick timer, chat. The event model already supports it.

---

## Risks

1. **Rankings churn** while the other session edits the tool — schema guard at the seam.
2. **Name mismatches** between Sleeper and FFC — `(name, pos, team)` matching plus a cached manual mapping table.
3. **Home hosting on draft night** — PC sleeping, ISP hiccup. Disable sleep; ship session export/import early so a crash never loses a draft. Consider renting a $5 VPS for draft week only.
4. **Scope drift into P4.** The live room is a genuinely different product. Resist.
5. **2026 ADP is thin right now** — 267 players, preseason. Real data lands in August.

### The 2025 fixture (corrected)

The original plan said to test against `2025_Rankings/`. **That folder cannot be used.** It predates `build_rankings.py` and carries the old FantasyPros export schema:

    "RK",TIERS,"PLAYER NAME",TEAM,"POS","BYE WEEK","SOS SEASON","ECR VS. ADP"

No ADP, no STDEV, no HIGH/LOW — so nothing the advisor needs — and `POS` values are position and rank fused together (`RB1`, `WR2`). It is a different format wearing the same directory naming convention.

The fix is better than the original idea anyway: **DrafterWeb builds its own fixture** by asking the FFC API for 2025 directly, which returns the modern schema. That call comes back with 249 players drawn from 8,470 drafts between 25 Aug and 1 Sep 2025 — the exact ADP landscape the league drafted into on 25 Aug 2025. Paired with the real 180-pick Sleeper board, that is a true end-to-end regression test.

Both fixtures are cached as JSON under `backend/tests/fixtures/`, so the suite runs offline and deterministically. Refresh them with `python -m tests.fixtures.refresh`.

*This also means the loader's schema guard is not hypothetical — there is already an incompatible file in the tree named exactly like a compatible one.*

---

## Answered

- **Domain:** none yet — buy one through Cloudflare Registrar (~$10.44/yr). Not blocking; P0 develops on a quick tunnel.
- **Host:** the Windows desktop, via Docker Desktop.
- **Keepers:** not settled for 2026, and therefore optional throughout. See the keepers section above.

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

**P0 — Foundation. DONE.** Rankings loading, core models, snake order with
optional keeper slotting, FastAPI service, Docker and tunnel config.

**P1 — Mock sandbox. DONE.** Event-log engine, ADP-jittered bots, React UI,
session persistence, pick clock, keeper editor, slot picker, rename. Drafts are
fixed at 15 rounds, matching the league and the 15-spot default roster. Live at
<https://ngfldrafter.com>.

**P2 — Live assistant. DONE.** Sleeper sync and the advisor, in a tool of
its own. See the status below.

**P3 — Harden.** Boot-time auto-start (the tunnel restarts itself, the app does
not), session export/import, mobile layout, Cloudflare Access if wanted.

**P4 — Multi-user room.** Websocket broadcast, lobby, identity, shared clock.
The event model already supports it: other slots become pick source `remote`.

---

## P2 status

**Done.**

1. **`integrations/sleeper.py`** — discovers a league's latest draft, parses
   picks into our vocabulary, caches every success and falls back on failure.
2. **The assistant as its own tool** — `/api/assistant`, its own sessions, its
   own list, its own screens. Each tool 404s the other's sessions.
3. **`core/advisor.py`** — conditional survival probability, ADP tiers, value
   against ADP, roster need and bye clashes, with the reasons stated. Exposed
   by both tools at `/advice`.

Three things real data corrected along the way, all worth remembering:

- Sleeper labels defenses `DEF`; passing that through raw produced keys that
  matched nothing. Fixed at the boundary *and* inside `player_key`.
- A positional log cannot skip a pick, but the real 2025 board contained a
  round-15 back the ADP feed does not carry. Unranked players are now logged
  with their own details rather than stalling the sync at pick 173 of 180.
- The reported ADP spread is tight, two to five picks early, so nearly
  everyone is gone by your next turn. Survival is stated only when it is
  actionable — who you can wait on.

### Revisiting the advisor

Good enough to draft with, not tuned. Everything adjustable sits at the top of
`core/advisor.py`:

| Knob | Now | What it does |
|---|---|---|
| `WEIGHT_DROPOFF` | 1.0 | how much the cost of waiting drives the score |
| `WEIGHT_VALUE` | 0.6 | how much falling past his own ADP counts |
| `VALUE_CAP` | 25 | beyond this, early or late stops meaning anything |
| `FILLED_POSITION_WEIGHT` | 0.25 | a position already filled, divided again per pick over |
| `SLOT_WEIGHT` | 1.0 / 0.8 / 0.3 | starter, flex, bench |
| `DEPTH_AT_TOP` | 2 | names offered at the leading position |
| `TIER_GAP_FRACTION` / `MIN_TIER_GAP` | 0.35 / 4 | what counts as a tier break |
| `BYE_PENALTY` | 2.0 | a third starter on one bye |

Known limits, in the order they are worth attacking:

1. ~~**Starters and bench are not distinguished.**~~ **Done.** `core/lineup.py`
   models the starting slots, flex eligibility and bench, read from Sleeper's
   own draft settings for a live board and defaulting to the league's shape
   otherwise. A pick is weighted by where it would actually go, so a first back
   fills a starting slot at full weight, a third takes a flex at 0.8, and a
   fifth is bench depth at 0.3. Draft three quarterbacks and the position stops
   being offered rather than merely sinking.
2. **No projections, so no true value over replacement.** Everything derives
   from ADP, which measures what drafters *do* rather than what a player is
   worth. A projections feed would let the score answer "how many points does
   waiting cost" instead of "how many ADP picks".
3. **The weights were never fitted to anything.** There is no ground truth for
   whether a pick was good, so they are judgement. Replaying past drafts
   against final standings would give something to tune against.
4. **Survival assumes a normal spread around ADP.** Reasonable, but the
   reported spread is tight enough that nearly everyone reads as gone, which
   is why survival is shown only when it argues for waiting.

### Still open

- **Manual entry fallback** for an offline or paper draft. The engine already
  supports it (pick source `manual`); it needs a UI.
- **A name-mapping escape hatch.** Unranked picks are reported but cannot be
  mapped by hand to a ranked player. Only matters if a *ranked* player is ever
  misspelled by Sleeper, which has not happened on real data.
- **P3 hardening:** boot-time auto-start, session export/import, mobile layout.

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

---

# P5 — Contracts: a prediction market for the league

Status: **design agreed 2026-08-28, nothing built.** A fourth tool, separate
from the other three in the same way they are separate from each other: its own
routes, its own screens, its own storage. It borrows the manager codes for
identity and the Sleeper client for resolution, and it changes nothing about
mock drafts, the live assistant or keepers.

## Locked decisions

| Question | Call |
|---|---|
| Model | Kalshi-style binary contracts. $1 payout, price is the implied probability, YES + NO = $1. |
| Pricing | **LMSR** automated market maker, `b = 10` |
| Stakes | **Real money**, per contract. Settled offline; the app keeps the ledger and handles no payments. |
| Counterparty | **The house is Brayden.** Loss per market is hard-capped at `b · ln 2` = **$6.93**. |
| Position cap | **5 contracts** per manager per market — $5 maximum payout, under $5 maximum spend |
| Friction | A **small spread**: buys quoted a cent or two above the model price, sells a cent or two below |
| First slate | **Draft night**, pre-built by the commissioner from templates |
| Identity | The existing per-manager keeper codes |

**Parked, not rejected:** the ante-pot structure — contracts trade in play
money, everyone antes $20, top three on the season leaderboard split the pot.
It removes the house's exposure entirely and caps everyone's downside at their
ante, and it is the obvious upgrade if per-contract real money turns out to
generate arguments rather than fun. Worth keeping the ledger denominated so
that switching is a config change rather than a rewrite.

## Why an order book cannot work here

Kalshi's 30¢ is 30¢ because someone will sell at 30¢. With twelve people an
order book never fills: you post, nobody takes it, the market prices nothing
and everyone stops looking. An automated market maker always quotes both sides,
so a market works even with one participant awake.

LMSR gives exactly the properties described: pairs summing to $1, price as
probability, and a genuine early exit — selling is just buying the other side.

    C(q) = b · ln( e^(q_yes/b) + e^(q_no/b) )
    price_yes = e^(q_yes/b) / ( e^(q_yes/b) + e^(q_no/b) )
    cost of a trade = C(q after) − C(q before)

### What it costs the house

At `b = 10`, opening at 50¢, twelve managers each buying their maximum five:

| | House collects | House pays | P&L |
|---|---|---|---|
| All 12 buy YES, YES wins | $53.09 | $60.00 | **−$6.91** |
| All 12 buy YES, YES loses | $53.09 | $0 | **+$53.09** |
| Six a side | $30.00 | $30.00 | **$0.00** |

Note the first row lands a cent under `b · ln 2`: unanimous buying is what
drives the loss to its ceiling, and the ceiling holds regardless of volume or
how wrong the opening price was. Downside capped, upside not — the same flow
that loses $6.91 wins $53.09 when the league is wrong, and balanced flow is
exactly flat. Across a ten-market slate the worst case is about **$70**.

For comparison, and because `b` is the only dial:

| `b` | max loss / market | one max buy moves 50¢ to | line at saturation |
|---|---|---|---|
| 5 | $3.47 | 73¢ | 100.0¢ |
| **10** | **$6.93** | **62¢** | **99.8¢** |
| 20 | $13.86 | 56¢ | 95.3¢ |

`b = 5` is rejected on that last column as much as the third: a line pinned at
100¢ means late buyers pay a dollar to win a dollar, which is not a market.

The house loses only to the extent the league beats the opening line — which on
draft night is a real risk, because the opening price comes from static ADP and
the room is watching the board.

## Markets are templates, not free text

A templated market can be priced and resolved by the app. Free text cannot, and
every market needing a human ruling is a real-money argument with the
commissioner, who is also drafting.

| Template | Opens at | Resolves from |
|---|---|---|
| `PLAYER drafted by pick N` | advisor survival curve | picks feed |
| `A QB taken in round 1` | ADP distribution | scan round 1 |
| `Any K before round N` | ADP distribution | first `position == K` |
| `MANAGER takes POSITION at their first pick` | ADP + slot | that manager's first pick |
| `N or more QBs gone by round R` | ADP distribution | count through R |

**Opening prices come free.** `advisor.survival_probability` already computes
P(player available at pick N) from ADP and stdev via a normal CDF. That is
literally an opening line, and it means the market opens honest without anyone
setting it by hand.

## Lifecycle runs on draft state, not the clock

Three moments, each expressed against the draft rather than a time:

- **Opens** — days before, at the ADP-derived price.
- **Closes** — at the pick that could decide it. *"Chase in the first three"*
  must stop trading before pick 1 or it is a free bet on a known answer.
- **Resolves** — the moment the picks feed proves it either way.

The middle is where the fun is: a market on pick 24 stays open through two
rounds and re-prices live as the board falls. The live assistant already polls
the draft, so the machinery exists.

## Architecture

The same shape as everything else here. A market is its trade log:

    replay(market, trades) -> MarketState   # price, positions, P&L, exposure

Nothing derived is stored. Undo is `trades[:-1]`, the audit trail is free, and
a disputed settlement can be replayed pick by pick. Consistent with
`replay(config, pool, log)` in the draft engine.

Storage: `markets`, `trades`, and a derived-on-read ledger. No new identity
system — the keeper codes already map a browser to a Sleeper user id.

## Open questions

- **Cap scope.** Five per market is agreed. Per *week* or per *season* as well?
  And after selling three of five, can you buy three more — is the cap on
  position or on lifetime volume? (Assumption: position.)
- **Holding both sides.** Buying 5 YES and 5 NO should net to zero rather than
  being allowed to stand.
- **Spread size.** One cent or two, and whether it widens near the extremes
  where a cent is a large fraction of the price.
- **Settlement view.** Everyone settles with the house, so twelve bilateral
  numbers. Needs a screen that says who owes whom and marks them paid.
- ~~**Draft-night failure mode.**~~ Resolved by closing the whole slate at the
  first pick instead of market by market, so nothing is tradeable once any
  answer is knowable and a stalled poller cannot change that.
- **Closing an in-season market that spans games.** "Does BigJedd beat
  Cashmoneycar this week" involves eighteen players across a dozen games, so
  its honest close is the earliest kickoff among them. Leaning towards
  **deriving it from a schedule feed** rather than closing the whole slate on
  Thursday or having the commissioner pick per market; Sleeper has no
  documented schedule endpoint, so that needs a source. Revisit once in-season
  markets are designed -- the draft slate does not depend on it.

## Explicitly not in v1

Multi-outcome markets ("who wins the championship"), limit orders, manager-created
markets, in-app payments, and any market that needs a human to rule on it.

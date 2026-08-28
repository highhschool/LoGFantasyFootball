# NGFL Drafter — web app

Self-hosted draft tool for the National Goon Fantasy League. See [PLAN.md](PLAN.md)
for the architecture and phase plan.

**Status: P1 complete.** The mock draft sandbox is playable: pick against eleven
bots, undo, autopick, or simulate the rest of the draft. 133 backend tests pass.

Live at <https://ngfldrafter.com>.

---

## Relationship to `FantasyDrafterAI/`

This app **never imports `DrafterAI.py`**. It reads the ranking CSVs that
`build_rankings.py` produces, and that directory is the only contract between the
two projects:

    FantasyDrafterAI/<YEAR>_Rankings/OVR_Rankings.csv

The loader checks for all twelve expected columns at startup and fails with a
readable message if they drift. That guard is not theoretical — `2025_Rankings/`
predates `build_rankings.py`, carries the old FantasyPros schema, and is
correctly rejected (there is a test for exactly this).

The rankings mount is **read-only**, so this app cannot write into a directory
the other session owns.

---

## Running locally

The host is Windows, so these are PowerShell. Run each line separately —
Windows PowerShell 5.1 has no `&&` operator and will throw a parser error on it.

```powershell
Set-Location D:\NGFL_FantasyFootball\DrafterWeb\backend
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m uvicorn app.main:app --reload --port 8000
```

Then open <http://localhost:8000>.

Use `python -m uvicorn`, not bare `uvicorn`. Pip installs its shim into a
Scripts directory that is not on PATH in this environment, so the bare command
is not found.

### The frontend

React + TypeScript + Vite + Tailwind, in `frontend/`. The built bundle is
**not** committed — build it once and FastAPI serves it from `backend/app/static`:

```powershell
Set-Location D:\NGFL_FantasyFootball\DrafterWeb\frontend
npm install
npm run build
```

For UI work, run the dev server instead. It hot-reloads on 5173 and proxies
`/api` through to the backend on 8000, so both environments call same-origin
paths and there is no CORS special case:

```powershell
npm run dev
```

Docker builds the frontend itself in a first stage, so a container needs no
prior `npm run build`.

To change season or rankings directory, set the environment variable first —
PowerShell has no inline `VAR=x cmd` prefix:

```powershell
$env:SEASON = "2025"
python -m uvicorn app.main:app --reload --port 8000
```

### Endpoints

| Route | Purpose |
|---|---|
| `GET /api/health` | Season, player count, and any rankings load error |
| `GET /api/players` | `?position=RB`, `?search=jamarr`, `?limit=50` |
| `GET /api/board` | The empty snake board for a config |
| `POST /api/rankings/reload` | Re-read the CSVs after regenerating them |

A bad rankings file degrades rather than crashes: the container stays up, health
reports `degraded` with the error, and the status page shows it.

---

## Running in Docker

> **Not yet verified.** Docker Desktop is not installed on this machine, so
> `Dockerfile` and `docker-compose.yml` are written but have never been built.
> Expect to shake out a wrinkle or two on first run. The local path above is the
> tested one.

Install Docker Desktop with the WSL2 backend, then:

```powershell
Set-Location D:\NGFL_FantasyFootball\DrafterWeb
docker compose up --build api
```

Serves on `127.0.0.1:8000` — loopback only, so nothing is exposed to the LAN or
the internet until a tunnel is attached.

---

## Publishing it to the league

Two tunnel modes, and they differ in one important way.

### Quick tunnel — for development, no domain needed

```powershell
Set-Location D:\NGFL_FantasyFootball\DrafterWeb
docker compose up -d api
docker run --rm --network drafterweb_default cloudflare/cloudflared:latest tunnel --url http://api:8000
```

Prints a random `https://<words>.trycloudflare.com` URL. Free, instant, and
requires no Cloudflare account at all — but **the URL changes every restart**,
and Cloudflare documents it as unsuitable for production. Fine for showing
someone a work in progress.

Join the compose network rather than using `--network host`, which is
unreliable on Docker Desktop for Windows. Confirm the network's real name with
`docker network ls` if `drafterweb_default` does not resolve — Compose derives
it from the directory name.

Without Docker at all, run the app locally as above and point a downloaded
`cloudflared.exe` at it:

```powershell
.\cloudflared.exe tunnel --url http://localhost:8000
```

### Named tunnel — for draft night

**Domain: `ngfldrafter.com`**, registered through Cloudflare Registrar.

DNS is already done. Registrar delegates the zone to Cloudflare automatically —
the nameservers are `norm.ns.cloudflare.com` and `heather.ns.cloudflare.com`.
There is no nameserver change to make, and no DNS record to add by hand: the
tunnel creates its own CNAME when you map the hostname.

`cloudflared` is installed (`C:\Program Files (x86)\cloudflared\cloudflared.exe`,
version 2026.8.2). It lands on the machine PATH, so open a **new** terminal
before calling it.

Serve the app on the **apex**, `https://ngfldrafter.com` — the whole domain
exists for this one app, so a `draft.` prefix only makes it longer to say out
loud on draft night.

1. Start the app locally: `python -m uvicorn app.main:app --port 8000`
2. Cloudflare **Zero Trust** dashboard → **Networks → Tunnels → Create a tunnel**
   → **Cloudflared** → name it `ngfl-drafter`.
3. Choose **Windows / 64-bit**. Copy the token out of the install command it
   shows you (the long string after `--token`).
4. Install it as a service, from an **Administrator** PowerShell:

   ```powershell
   cloudflared service install <PASTE_TOKEN_HERE>
   ```

5. Back in the dashboard, on the tunnel's **Public Hostname** tab → **Add a
   public hostname**:
   - Subdomain: *(leave empty)*
   - Domain: `ngfldrafter.com`
   - Service type: `HTTP`, URL: `localhost:8000`
6. Paste the same token into `.env` as `TUNNEL_TOKEN=...` so the Docker path
   works later without repeating step 3.

The service starts at boot and the URL is stable across restarts. Verify with:

```powershell
Resolve-DnsName ngfldrafter.com -Type CNAME
Invoke-WebRequest https://ngfldrafter.com/api/health -UseBasicParsing
```

### Privacy stance

**The site is deliberately public.** It is a draft tool for friends, and login
friction is not worth it for data that is not sensitive.

What that does and does not mean:

- The ADP rankings it serves are public data from Fantasy Football Calculator.
  Nothing is protected by hiding them.
- **The league's Sleeper data is already public at the source.** `api.sleeper.app`
  serves the league's users, rosters and full draft board to anyone with the
  league ID, no authentication at all. This app cannot make that more private.
- So the goal is not secrecy but **discoverability**: the app should never hand a
  visitor the league ID or manager names, because that is the one thing that
  turns "public in principle" into "trivially findable".

**P2 design rule:** `SLEEPER_LEAGUE_ID` stays server-side in `.env`. The backend
proxies Sleeper and returns only what the board needs. No response ever contains
the league ID, and managers appear under their team names.

### Optional: locking it down later (Cloudflare Access)

Not currently applied. Worth knowing that Access can protect a **path** rather
than the whole site — so the mock sandbox could stay public at `/` while a
private assistant lives behind `/assistant/*`. Set the Path field below instead
of leaving it empty.

Go to the **Zero Trust** dashboard at <https://one.dash.cloudflare.com>. First
time through, it asks you to pick a team name (this becomes
`<team>.cloudflareaccess.com`) and a plan; **Free covers up to 50 users**.

**Access → Applications → Add an application → Self-hosted**

| Field | Value |
|---|---|
| Application name | `NGFL Drafter` |
| Session duration | `1 month` — so nobody is re-authenticating mid-draft |
| Subdomain | *(leave empty)* |
| Domain | `ngfldrafter.com` |
| Path | *(leave empty — this protects the whole site, API included)* |
| Identity providers | **One-time PIN** (on by default, needs no setup) |

Then **Add a policy**:

- Policy name: `League managers`
- Action: **Allow**
- Include → **Emails** → the managers' addresses

**Add your own address first and save with only that.** Verify you can still get
in, then add the other eleven. A policy that omits you locks you out of your own
site.

#### Verifying it

Open the site in a **private/incognito window** — your normal browser may already
hold a session and appear to prove nothing. You should land on a Cloudflare login
page, enter your email, receive a PIN, and only then reach the app.

Then re-run `.\start.ps1`; step 4 should now read *"up and behind Cloudflare
Access"* rather than warning that the site is open.

#### If you lock yourself out

Zero Trust → **Access → Applications** → delete the application. The site
immediately becomes public again, and you can redo the policy.

#### Notes

- There is no bypass. The origin is reachable only through the tunnel, so
  requests cannot skip the Access check by going around Cloudflare.
- Access applies to `/api/*` too, so scripted calls get a login page instead of
  JSON. That is intended. If something ever needs programmatic access, issue a
  **service token** rather than loosening the policy.
- P2's Sleeper polling is unaffected: it is an outbound call made by the server,
  not an inbound request through Access.

### Still manual: the app itself

The tunnel runs as a service, but `uvicorn` does not — if the machine reboots,
the tunnel comes back up and finds nothing behind it. Until that is fixed the
app must be started by hand.

Closing that gap is a P3 task, either by running the API under Docker with
`restart: unless-stopped`, or by registering it as a Windows service.

---

## Windows host notes

The desktop is the host, so two settings decide whether this survives draft night:

- **Disable sleep and hibernate** in the power plan. A sleeping PC is the single
  most likely way this falls over mid-draft.
- Docker Desktop → **Start Docker Desktop when you log in**, and the compose
  services already use `restart: unless-stopped`.

Session export/import lands in P2 specifically so a crash never loses a draft.

---

## Tests

```powershell
Set-Location D:\NGFL_FantasyFootball\DrafterWeb\backend
python -m pytest -q
```

The suite runs offline against cached fixtures in `tests/fixtures/`:

- `ffc_adp_2025.json` — 249 players from 8,470 drafts run 25 Aug–1 Sep 2025,
  which is the ADP landscape that existed when the league actually drafted.
- `sleeper_draft_2025.json` — the real, completed 180-pick board.

Together they drive `test_sleeper_replay.py`, which replays the league's own 2025
draft through the engine and asserts our snake geometry matches Sleeper's pick
for pick, and that every drafted player's name resolves across the two feeds.

Refresh the fixtures only when you want newer data:

```powershell
Set-Location D:\NGFL_FantasyFootball\DrafterWeb\backend
python -m tests.fixtures.refresh
```

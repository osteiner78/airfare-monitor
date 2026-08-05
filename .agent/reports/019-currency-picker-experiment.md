# Plan 019 — Currency forcing: the picker experiment

**Result: SOLVED.** Driving Kayak's currency picker once, and answering its
"save for future?" prompt, persists EUR into the browser profile. Every
subsequent render — in separate browser processes — is served in EUR.
`search()` now returns rows again, with no change to `_build_url`.

## Why this was the remaining path

Phase 1 falsified every cheaper mechanism empirically. Not retried here:

- `?currency=EUR` is not honoured by the rendered page
- a fresh, cookie-less, profile-less render still serves USD
- there is no plain currency cookie to imitate
- `CurrencyPickerStateProviderAction` returns the picker's full candidate
  list, not the active selection

The untried path was the picker UI itself, which the bundle can reach because
it runs headful with a persistent profile at `data/kayak-profile`.

Phase 1's parting lead pointed the same way: a plain `urllib` fetch *does*
embed `"currency":"EUR"` in the initial state while the browser ends up USD —
consistent with client-side JS applying a **stored preference** over the URL
param. That is exactly what this experiment found.

## What actually happens

Three things had to be discovered; the first two are why the naive attempt
failed.

**1. `www.kayak.com` force-redirects by egress geography.** From this
residential IP (Brazil) the homepage lands on `www.kayak.com.br`, in
Portuguese, priced in `R$`/BRL:

```
url=https://www.kayak.com.br/?ispredir=true
Você foi redirecionado ao kayak.com.br com base na sua localização.
Go to kayak.com instead.
```

Preferences are stored **per origin**, and searches run against
`www.kayak.com` — so setting the currency on the `.com.br` origin would not
have applied to the page we render. The script clicks Kayak's own
"Go to kayak.com instead." escape first.

**2. The currency control is in the footer, not the header.** On the homepage
it renders as language + symbol + **ISO code**:

```
English
$
USD
```

The results page uses symbol + **full name** (`$` / `United States dollar`) —
the form `_page_currency` already matches. The two vocabularies differ, so the
script tries both.

**3. Selecting a currency is one-time until you confirm it.** This is what
made the first attempt fail. After clicking `€ Euro`, Kayak asks:

```
Save currency for future?
The Euro is now set – do you want to use this for future visits, too?
Save for future        One time only
```

The first run closed the browser without answering, and the preference did not
survive:

```
attempt 1 (no answer given)  ->  _page_currency() -> 'USD'   RESULT: FAIL
```

Clicking **"Save for future"** is the actual forcing mechanism:

```
attempt 2 (Save for future)  ->  _page_currency() -> 'EUR'   RESULT: PASS
     '€' occurrences: 104     '$' occurrences: 0
```

## Verification

A *separate process*, fresh browser session, same persistent profile, against
the results URL **with no `currency=` parameter at all**:

```
navigating to https://www.kayak.com/flights/GRU-LIS/2026-10-04?sort=price_a
  body_len=20126
  _page_currency() -> 'EUR'   (want 'EUR')
  '€' occurrences: 104   '$' occurrences: 0
RESULT: PASS
```

Header chrome now reads exactly the pair `_page_currency` keys on:

```
English
€
Euro
```

Fares are €-prefixed: `€648  €490  €550  €559  €637  €498  €570`.

End-to-end through the real source, unmodified:

```
rows returned : 5
last_error    : None
    490.00 EUR  'Royal Air Maroc'        fn=''  royal air maroc|2026-10-04T00:30:00|2026-10-04T17:40:00
    498.00 EUR  'GOL'                    fn=''  gol|2026-10-04T22:10:00|2026-10-05T21:45:00
    550.00 EUR  'Azul, easyJet'          fn=''  azul, easyjet|2026-10-04T14:10:00|2026-10-05T10:20:00
    554.00 EUR  'Azul, TAP AIR PORTUGAL' fn=''  azul, tap air portugal|2026-10-04T14:10:00|2026-10-05T11:30:00
    554.00 EUR  'Azul, TAP AIR PORTUGAL' fn=''  azul, tap air portugal|2026-10-04T14:10:00|2026-10-05T14:10:00
```

Persistence held across **4 consecutive renders in 4 separate browser
processes**. Every one was EUR.

## `_page_currency` verification is kept regardless

As instructed, and as Decision 1 frames it: forcing is the attempt,
verification is the guarantee. Nothing about the refuse-on-mismatch path
changed. The preference lives in a browser profile that Kayak controls and can
reset at any time — the check is what makes that safe rather than silent.

`_build_url` is unchanged; the `?currency=` param is still sent as a harmless
attempt.

## Live request budget

Roughly **10 page loads**, 4 of them full flight-results renders, spaced across
~25 minutes. Nothing else was hitting Kayak (every tracker is
`kayak_enabled=0`).

| Run | Page loads | Outcome |
|---|---|---|
| `set` #1 | 1 | redirected to `.com.br`; no control found in header |
| `set` #2 | 2 | escaped to `.com`, opened picker, clicked `€ Euro`, **did not save** |
| `verify` #1 | 1 | USD — preference did not persist |
| `set` #3 | 1 | picker + `€ Euro` + **Save for future** |
| `verify` #2 | 1 | **EUR — PASS** |
| e2e #1 | 2 | render OK + EUR-verified; LLM timed out |
| e2e #2 | 2 | render OK + EUR-verified; LLM timed out |
| e2e #3 | 2 | **5 EUR rows returned** |

**0 blocks across all attempts.** The evasion bundle was not touched.

The two e2e timeouts were isolated to the LLM proxy, not to Kayak, by re-running
`_extract` against an already-captured body (costing no Kayak request):
5.5s / 30.0s timeout / 3.5s. See the Phase 2 report's follow-ups.

## Incident found and fixed: Xvfb stale lock

The first `set` run failed to launch a browser at all:

```
Missing X server or $DISPLAY
The platform failed to initialize.  Exiting.
```

Cause: `docker-entrypoint.sh` started Xvfb only when `/tmp/.X99-lock` was
absent. `docker compose stop` kills the Xvfb process but leaves `/tmp` intact,
so on the next `start` the lock file was present with **no server behind it**,
and the guard skipped the launch permanently. Triggered by the Phase 2 backfill
restart.

This is a sharper form of the hazard CLAUDE.md already records ("Xvfb is not
supervised — if it dies, every headful launch fails until the container
restarts"): a restart does **not** fix it, because the stale lock survives one.

Fix (`docker-entrypoint.sh`): read the pid recorded in the lock file and clear
the lock plus its socket when that process is gone. Verified — the container
restart that followed cleared a lock from `04:54` and brought the display up:

```
X server ALIVE
-r--r--r-- 1 root root 11 Aug  5 15:48 /tmp/.X99-lock
```

No live Kayak request was spent on the failed launch.

## Reproducing / re-applying

`scripts/kayak_currency_picker.py` (new), two modes:

```bash
docker exec airfare-monitor python /app/scripts/kayak_currency_picker.py set
docker exec airfare-monitor python /app/scripts/kayak_currency_picker.py verify
```

Diagnostics (body text, screenshots, localStorage delta, cookies) land in
`data/kayak-currency-experiment/`.

**Re-run `set` whenever the profile is reset or `verify` reports non-EUR** —
the preference lives in `data/kayak-profile`, so deleting that directory loses
it. This is now a piece of operational state the deployment depends on.

## Caveats

- The preference is tied to `data/kayak-profile`. Losing or rebuilding the
  profile silently reverts to USD — `search()` then refuses everything (safely,
  loudly) until `set` is re-run.
- Persistence is confirmed over ~25 minutes and 4 sessions. Longer-horizon
  durability (days, or across Kayak-side session expiry) is **not** established;
  Phase 3's run is the natural place to observe it.
- The escape from the `.com.br` redirect also appears to have persisted (later
  runs went straight to `www.kayak.com`). Same profile-bound caveat applies.
- A BRL-served page returns `None` from `_page_currency` (BRL is unmapped, and
  the `.br` footer uses ISO codes rather than full names), so it refuses
  correctly rather than mislabelling.

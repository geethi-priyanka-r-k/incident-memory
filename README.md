# Incident Memory Agent

An internal incident tool for reporting operational problems, getting a memory-assisted triage, tracking repeat issues, and retaining verified fixes.

## Architecture

- **SQLite (`incidents.db`)** is the record of truth for incident reports, status, diagnosis history, and memory-sync state.
- **Hindsight** is semantic memory. The agent recalls related retained resolutions during triage and retains a resolution after an incident is resolved.
- **Groq** reasons over the report and any recalled memories to produce a short incident briefing.
- **Band** is an optional remote chat interface. The local bridge connects outward, receives agent mentions, and saves through the same SQLite database.
- **Flask** serves the dashboard and incident pages locally at `http://127.0.0.1:5000`.

## How Hindsight memory is used

When a new incident is triaged, the page displays Hindsight's recalled memories before Groq prepares the briefing. Recall uses the low budget and a 2,048-token result cap; the briefing asks Groq for up to 600 tokens using `openai/gpt-oss-20b` at low reasoning effort, with `llama-3.3-70b-versatile` as a compatibility fallback. The agent reports recall and Groq elapsed seconds in the server terminal. Only memories explicitly cited by the model are treated as relevant. The comparison page runs the same report once without memory and once with it. When a resolution is saved, the incident is written to SQLite first; Hindsight retention then runs in a background thread, and the previous briefing is cleared so a later report can use the new fix. SQLite shows whether retention is pending, complete, or failed, and a failed retention can be retried.

The confidence values are model-estimated indications, not calibrated probabilities. The memory page labels them accordingly. Optional local demo samples are explicitly labeled as illustrative; their confidence values are synthetic and are not counted as memories retained.

## Setup on Windows PowerShell

Open PowerShell in the project folder:

```powershell
Set-Location 'E:\Geethi_files\downloads\incident-agent\incident-agent'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

In the PowerShell window where you will run the website, set your own environment values. Replace each example with your own value; do not put real keys in source files or share them in chat.

```powershell
$env:HINDSIGHT_URL = "your-Hindsight-URL"
$env:HINDSIGHT_API_KEY = "your-Hindsight-key"
$env:HINDSIGHT_BANK = "incident-memory"
$env:GROQ_API_KEY = "your-Groq-key"
$env:GROQ_MODEL = "openai/gpt-oss-20b"
```

For login, generate `SECRET_KEY` and `REPORT_API_TOKEN` directly into the blank entries in `.env`. This command does not display either value:

```powershell
@'
from pathlib import Path
import secrets

path = Path(".env")
generated = {
    "SECRET_KEY": secrets.token_hex(32),
    "REPORT_API_TOKEN": secrets.token_urlsafe(32),
}
lines = path.read_text(encoding="utf-8").splitlines()
for index, line in enumerate(lines):
    name, separator, value = line.partition("=")
    if separator and name in generated and not value:
        lines[index] = f"{name}={generated.pop(name)}"
lines.extend(f"{name}={value}" for name, value in generated.items())
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
'@ | .\.venv\Scripts\python.exe -
```

Start the app and open `http://127.0.0.1:5000/signup` to create the first account. Choose a name, email, and password of at least 8 characters; signup logs you in and opens the overview. You can also create accounts from PowerShell with `.\.venv\Scripts\python.exe create_user.py`. Sign in later at `http://127.0.0.1:5000/login`. The report API uses the `X-Report-Token` header; keep its value private.

To enable the optional demo sign-in, set `DEMO_MODE=1` in `.env` and restart the app. Demo sessions may ask the agent and view pages, but cannot use other write actions.

Start the website:

```powershell
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:5000` for the public product page. Use **Sign in** or **Get started** to continue to `/login` or `/signup`. If a Hindsight or Groq variable is missing, the site prints a startup warning naming the missing variable, but still opens so you can use the incident records.

## Three-minute demo

1. **Compare without memory.** Open **Memory comparison**, paste a new report such as `Checkout requests time out when the database pool reaches its limit`, and run both columns. The first run uses no recalled context.
2. **Retain a verified fix.** Select **Report an incident**, save a report, open its page, and enter a root cause and fix. Wait for **Saved to memory**.
3. **Reword the problem.** Open **Memory comparison** again and enter a paraphrase, for example `Orders take too long to submit because database connections are used up`. Compare the no-memory and memory-assisted briefings, including any recalled memories.
4. **Review learning and patterns.** Open **What the agent has learned** for retained fixes and triage history, then **Recurring problems** to see resolved types that repeat.

## Pages

- `/` - public product page with product overview and workflow
- `/login` - sign in to an existing account
- `/signup` - create an account and open the overview
- `/overview` - incident dashboard with workspace counters, live feed, and learning panels
- `/incidents` - incident list with filters and search
- `/ask` - ask the agent for an in-place memory-assisted briefing
- `/report` - report an incident
- `/incident/<id>` - incident details, triage, status, and resolution
- `/compare` - same-report comparison with and without memory
- `/memory` - retained fixes, triage confidence history, and memory explanation
- `/patterns` - resolved incident types in the past 30 and 90 days
- `/handoff` - active incidents, attempted fixes, and saved triage recommendations
- `/outcomes` - responder feedback on suggested fixes and outcome memory-sync state
- `/trail` - resolved incident records and their memory-retention status
- `/replay` - model-estimated briefings rebuilt using memory available at three recorded checkpoints
- `/risk` - change-risk assessment grounded in linked recalled incidents
- `/connect` - Band bridge configuration and heartbeat status, room commands, and a PowerShell API example

## Outcome feedback, memory trail, replay, and change risk

On an incident with a briefing, record whether the suggested fix worked, partly worked, or did not work. The outcome is stored in SQLite with the signed-in user and retained to Hindsight in a background task; the page distinguishes pending, synced, and failed retention. Recalled memories link to source incidents. Older seed documents without incident IDs are matched to resolved SQLite rows by text similarity, and that match method is shown.

Memory replay recalls once for the selected resolved incident, then asks the reasoning model for a briefing at three checkpoints using only recalled texts mapped to incidents resolved by each cutoff. The confidence is model-estimated, not a measured success probability. The change risk check likewise uses only recalled and source-linked incidents; it reports unknown when no history can support a result, and does not invent a rollback plan.

### Test these features

Sign in and use the existing seeded incident history; no seed records need to be changed.

1. **Outcome learning:** report a non-demo incident, open its page, run the briefing, then record Worked, Partly, or Didn't work. Check `/outcomes` for the feedback and its pending-to-synced memory status. Repeat with failed outcomes on resolved incidents, then ask a related question; a source with at least two recorded failures is marked **Needs review**.
2. **Memory trail:** open `/trail` and select an incident with a stored resolution. Open a new briefing that recalls a seed resolution; its numbered source markers open the original record and identify older seed matches as **matched by similarity**.
3. **Memory replay:** open `/replay`, choose a resolved incident, and run the replay. Expect three checkpoint columns. The model-estimated scores and fix steps may differ depending on which resolved records Hindsight recalls.
4. **Change risk:** open `/risk` and check a specific change related to a seeded report, such as a login rate-limit change. Review the linked source incidents. If no source record can be linked, the result must say **No history for this kind of change, risk unknown**.

## Band integration

The Band bridge connects outward from this computer; no public URL or webhook is needed. It saves reports and resolutions through the shared `db.py` SQLite functions. In the Band room, select the agent from the `@` dropdown and describe the incident. To resolve one, mention the agent and use this format:

```text
@geetyravi07/incident-memory-agent resolve #12 root cause: exhausted database connections fix: increase the pool limit not worked: restart the service
```

Use `not worked: none` if nothing failed. The bridge replies after saving to SQLite, while Hindsight retention continues in the background. Recurrence notices link to `/patterns`.

Set the Band and application variables in the PowerShell window that will run the bridge. Values are not shared across separate PowerShell windows:

```powershell
$env:BAND_API_KEY = "your-Band-key"
$env:BAND_AGENT_ID = "your-Band-agent-id"
$env:HINDSIGHT_URL = "your-Hindsight-URL"
$env:HINDSIGHT_API_KEY = "your-Hindsight-key"
$env:HINDSIGHT_BANK = "incident-memory"
$env:GROQ_API_KEY = "your-Groq-key"
$env:GROQ_MODEL = "llama-3.3-70b-versatile"
$env:BAND_ECHO = "0"
.\.venv\Scripts\python.exe band_bridge.py
```

The **Use it from Band** page checks only whether the required environment variables are present; it never shows their values. If a required variable is missing, the bridge stops with a clear message naming it. For a connection test, set `$env:BAND_ECHO = "1"`, restart the bridge, mention the agent from the room dropdown, and confirm it replies `Echo: <message>`. Set it back to `"0"` and restart to process incidents normally.

The bridge updates a SQLite heartbeat while connected. The Band page reports it as online only while a recent heartbeat is present. The **On-call handoff** page groups open and investigating incidents by severity and can copy their saved attempted fixes and recommendations.

The local API can also create a report from PowerShell:

```powershell
$body = @{
  title = "Checkout requests are timing out"
  report = "Requests queue until they time out during checkout."
  where_seen = "Production checkout service"
  source = "monitoring"
  reported_by = "On-call engineer"
} | ConvertTo-Json
$tokenLine = Get-Content .env | Where-Object { $_.StartsWith("REPORT_API_TOKEN=") } | Select-Object -First 1
$reportToken = $tokenLine.Substring("REPORT_API_TOKEN=".Length)

Invoke-RestMethod `
  -Uri "http://127.0.0.1:5000/api/report" `
  -Method Post `
  -ContentType "application/json" `
  -Headers @{ "X-Report-Token" = $reportToken } `
  -Body $body

Remove-Variable tokenLine, reportToken
```

## Ask, duplicate reports, and Band reply checks

The dashboard's **Ask the agent** box is the fastest entry point. It saves or reuses an open incident, runs memory triage, and shows the briefing without leaving the page. Reports with at least 90% text similarity match when they arrive within 60 minutes of an open incident; each repeat adds a timeline event and increments the report count. Resolved incidents are not reused.

After saving a resolution and seeing **Saved. The agent will recognise this next time.**, select **Try a reworded version**. Groq rewrites the report and the app immediately runs Ask on that wording. This requires the Groq environment variable to be set.

On **Memory comparison**, the same report is run with memory disabled and enabled. Select **Try a reworded version** to ask Groq to paraphrase it, then compare both triage results again. Confidence is model-estimated, not a calibrated probability.

To check the Band connection before testing diagnosis, open a second PowerShell window in the project folder and run:

```powershell
Set-Location 'E:\Geethi_files\downloads\incident-agent\incident-agent'
$env:BAND_ECHO = "1"
.\.venv\Scripts\python.exe band_bridge.py
```

In the Band room, select the agent from the `@` dropdown and send a short message. The reply should be `Echo: <your message>`. To restart the bridge, press **Ctrl+C** in that PowerShell window and run `.\.venv\Scripts\python.exe band_bridge.py` again. Once echo works, set `$env:BAND_ECHO = "0"` and restart to test incident handling.

The installed SDK's `send_message` method accepts `content` and an optional `mentions` argument; no recipient argument is required. If the bridge still produces no reply in echo mode, copy the traceback printed in the bridge terminal and paste it to your assistant with any keys hidden. Do not copy environment-variable values.

The incident list has a **Delete** action for open incidents only. No existing records, including rows #4–#8, were deleted.

## Example incident data

The seeded dataset is loaded with:

```powershell
.\.venv\Scripts\python.exe seed_phase3.py
```

This command replaces duplicate/test rows with 15 resolved incidents spread across 60 days (2026-09-08 to 2026-11-05), covering five incident types with realistic titles, error text, root causes, fixes, and failed attempts. It also records three outcome records: two "worked/partly" and one "didn't work" (marked Needs review). No customer names or invented metrics are used. The command is idempotent and does not contact Groq or Hindsight.

## Demo mode

A **Presenter** toggle in the signed-in workspace runs a numbered 60-second demo script: ask a new problem, see generic advice, save the fix, ask a reworded version, see recall, open the memory trail, and open memory replay. Enable demo sign-in with `DEMO_MODE=1` in `.env`.

## Screenshots

Replace these placeholders with screenshots captured from your own local workspace:

- **Sign in:** sign-in page with the Incident Memory wordmark and login form
- **Overview:** four stat cards with sparklines, shorter dark Ask card, live feed with source badges, Memory health card, knowledge gaps with "Document the fix", coverage by incident type
- **Incident detail:** left report and timeline; right briefing with the mint "From memory" badge, memory trail markers, success record, terracotta "Don't try these" box, and Did-it-work buttons
- **Memory comparison:** muted "Without memory" vs deep-teal "With memory" with animated confidence and "Try a reworded version" button
- **Learning and patterns:** confidence curve, retained fixes, recurring incident types
- **Presenter mode:** numbered 60-second demo script overlay

## Why this is different

Four features turn incident response from "search chat and hope" into a repeatable loop:

1. **Outcome learning.** Resolutions enter memory only after the team records the cause, fix, and what did not work. Outcomes marked "didn't work" on two or more cases surface as **Needs review**, so bad fixes don't get reused.
2. **Memory trail.** Every briefing shows numbered source markers linking to the recalled incident. Responders can open the original record and inspect the evidence — including whether a match was found by incident ID or by text similarity — instead of trusting an unexplained conclusion.
3. **Memory replay.** The same report is triaged side by side without memory and with memory, then a reworded version checks whether similar meaning still brings the same memories back. Animated confidence shows exactly what context changed the briefing.
4. **Change risk check.** Before a deployment or config change, the agent surfaces only prior incidents linked to the change, reporting **risk unknown** when no history supports a conclusion rather than inventing a rollback plan.

## How Hindsight is used for each

- **Outcome learning:** when a resolution or outcome is saved, the report, root cause, fix, failed attempts, and outcome note are retained to Hindsight as a memory in the background. SQLite tracks sync state (pending, synced, failed).
- **Memory trail:** when a new incident is triaged, Hindsight recalls related memories. Each recalled text is mapped back to its source incident, shown by ID or similarity match, so responders can verify the evidence.
- **Memory replay:** the compare page runs triage without memory context and with recalled Hindsight memories, so the team sees which memories changed the suggested fix and confidence.
- **Change risk check:** the risk page checks a proposed change only against recalled, source-linked Hindsight incidents and reports unknown when no supporting history exists.

## Design decisions

The interface uses a restrained cream, teal, mint, and terracotta palette to distinguish memory-related details without competing with incident content. Navigation stays consistent across pages, while serif headings and compact data displays separate the narrative briefing from operational status. Charts use stored triage and resolution records; optional local demo records are visibly labeled and never represented as actual model output or Hindsight-retained fixes.

## Test checklist — every page

### Landing (`/`)
- [ ] Loads with Incident Memory wordmark, navigation (Product, How it works, What is different), and Sign in / Get started buttons
- [ ] Hero preview shows sample briefing, confidence bar, and terracotta "Don't try these" box
- [ ] Public counters show when records exist; hidden when empty
- [ ] Links scroll to product/how-it-works/different sections

### Sign in (`/login`) & Create account (`/signup`)
- [ ] Form shows name/email/password (signup) or email/password (login) with validation errors
- [ ] Password show/hide toggle works
- [ ] Demo sign-in button appears when `DEMO_MODE=1`
- [ ] Successful sign-in redirects to Overview; wrong credentials show an error toast/message

### Overview (`/overview`)
- [ ] Greeting uses capitalised first name ("Good morning, Geethi")
- [ ] Ask card is short enough that all four stat cards are visible at 1080p without scrolling
- [ ] Four stat cards: Open incidents, Resolved this month, Memories retained, Median time to resolve — each with a sparkline
- [ ] Animated counting on stat cards; confetti-free, reduced-motion respected
- [ ] Submitting the Ask box saves an incident and shows a briefing panel below the card
- [ ] Live feed rows show source badges (Band, Web, Monitoring, Support), severity, status, and time
- [ ] Live feed refreshes periodically; empty state shows one sentence + "Report an incident" button
- [ ] Learning curve chart shows confidence points with dates; demo samples marked illustrative
- [ ] Knowledge gaps list shows open incidents with no related memory, each with "Document the fix" button
- [ ] Memory coverage list shows types with progress bars; empty state shown when none
- [ ] Memory health card shows "Fixes with a success record" and "Fixes marked Needs review" counts
- [ ] Breadcrumbs show Overview; pressing "/" focuses the Ask box
- [ ] Toasts appear for save/sync outcomes instead of alerts

### Incidents (`/incidents`)
- [ ] Table lists all incidents with ID, title, type, severity, status, source, reported time, memory sync
- [ ] Filters (status, type, source, search) apply and persist in the URL
- [ ] Open incidents have a Delete button; resolved/investigating do not
- [ ] Empty state shows one sentence + button when no matches

### Ask the agent (`/ask`)
- [ ] "/" focuses the textarea
- [ ] Example buttons insert sample reports and focus the field
- [ ] Character counter updates on input; max 10,000
- [ ] Submitting shows a spinner, then a briefing with likely match, confidence bar, fix steps, skip list, and memory citations
- [ ] "Open incident" link navigates to the saved incident

### Report an incident (`/report`)
- [ ] Title, report, where seen, source, and your name fields validate (title + report + name required)
- [ ] Character counter on report field
- [ ] Cancel returns to Incidents; submit saves and redirects to the incident page

### Incident detail (`/incident/<id>`)
- [ ] Breadcrumbs: Overview → Incidents → Incident
- [ ] Left column: report, metadata (source, reported by, reported time), timeline with report/investigation/resolved events
- [ ] Right column: briefing card with sticky position, mint "From memory" badge when memories exist
- [ ] Confidence bar animates; caption notes model-estimated, not calibrated
- [ ] Citation markers ([1], [2]) open the memory drawer with source report, root cause, fix, failed attempts, resolved date
- [ ] "Don't try these, they failed before" terracotta box shows when skip steps exist
- [ ] Success record shows outcome text; "Needs review" badge appears when applicable
- [ ] Resolution form: root cause + fix required; "Saving to memory…" state, then "Resolution saved" with success color and toast
- [ ] "Retry memory save" appears only after a failed sync; "Try a reworded version" appears only after synced
- [ ] Did-it-work buttons (Worked/Partly/Didn't work) with optional note; saving shows pending → synced → done states

### Memory comparison (`/compare`)
- [ ] Incident dropdown or paste report; selecting fills the report field
- [ ] "Without memory" column is muted (light border, muted confidence); "With memory" is deep-teal background
- [ ] Confidence numbers animate up on both columns
- [ ] Recalled memories listed under With memory; "No related memories" shown when empty
- [ ] "Try a reworded version" rewords and re-runs both columns; explanation updates
- [ ] Breadcrumbs: Overview → Memory comparison

### What the agent has learned (`/memory`)
- [ ] Three counters: Incidents resolved, Memories retained, Triages with a relevant past incident (%)
- [ ] Learning curve chart with average first-five vs latest-five callout
- [ ] Recently retained fixes timeline with root cause and fix per incident
- [ ] Local demo fixes section shown only when demo data exists, clearly labeled illustrative
- [ ] How Hindsight is used explainer with two steps (retain on resolve, recall on report)

### Recurring problems (`/patterns`)
- [ ] 30-day and 90-day sections; each type shows count, bar, and notice (permanent fix suggestion at ≥3)
- [ ] Each pattern links to its incidents
- [ ] Empty state when no resolved incidents in window

### On-call handoff (`/handoff`)
- [ ] Active incidents ordered by severity; badges for severity and status
- [ ] Each shows what was tried and agent recommendations
- [ ] "Copy handoff" copies all items to clipboard with a toast confirmation

### Outcome learning (`/outcomes`)
- [ ] Table of outcomes: incident, outcome (Worked/Partly/Didn't work), note, recorded time, memory sync
- [ ] Empty state with button to view incidents

### Memory trail (`/trail`)
- [ ] Timeline of resolved incidents with memory sync status
- [ ] Each links to incident page; shows root cause, fix, what did not work
- [ ] Empty state when no resolved incidents

### Memory replay (`/replay`)
- [ ] Dropdown of resolved incidents; "Replay checkpoints" button
- [ ] Three checkpoint columns (start/middle/now) with confidence, likely match, fix steps, memories available
- [ ] Summary line explains whether steps changed across checkpoints
- [ ] Citation markers open memory drawer

### Change risk check (`/risk`)
- [ ] Change description field validates; submit checks history
- [ ] Result shows risk level, reasons, what failed before, rollback note, recalled records
- [ ] "No history for this kind of change, risk unknown" when no linked sources

### Band (`/connect`)
- [ ] Bridge configuration checklist (each variable Present/Missing, values never shown)
- [ ] Bridge connection online/offline with heartbeat indicator and last heartbeat time
- [ ] Room commands examples (mention agent, resolve format)
- [ ] Local API PowerShell example

### Error pages (404 / 500)
- [ ] Styled error card with logo mark, title, description, and "Go to home" / "Go to overview" buttons
- [ ] Returns correct HTTP status (404 / 500)

### Cross-cutting
- [ ] All pages use the palette only (cream, surface, border, text, muted, accent, sidebar, mint, terracotta, open, resolved, danger) — no off-palette colours
- [ ] Contrast passes WCAG AA for text on surface/page/sidebar backgrounds
- [ ] Keyboard focus visible (mint outline) on all interactive elements; skip-to-content link works
- [ ] Breadcrumbs present on all signed-in pages
- [ ] User menu shows capitalised name and Sign out; presenter toggle present in demo mode
- [ ] 404 for unknown routes and unknown incident IDs
- [ ] Favicon loads on all pages; page titles reflect the current page

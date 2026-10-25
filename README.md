# CaleGlasss

Smart Glasses for Cal Hacks 13.0. **EyeClick**: a Python program reads an endoscopic camera pointed at one eye, measures how long each eye closure lasts, and turns it into a left or right click. The cursor is moved separately by the gyroscope (an ESP32 acting as a BLE mouse), so this module only handles clicks.

| Eye closed | Result |
|---|---|
| less than 0.4 s | Natural blink, ignored |
| 0.5 – 1.2 s | Left click |
| 1.2 – 3.0 s | Right click |
| more than 3.0 s | Cancelled (resting, does nothing) |

The click fires **when the eye opens**, at the position the cursor had **when it closed**. A beep plays at 0.5 s and a different one at 1.2 s.

On top of EyeClick sits the **agent team**: the wearer asks for something by voice, a Forge app routes it to Claude agents (Jira, reporter), and the progress shows up live on the glasses' overlay and on a web dashboard. See [Agent team](#agent-team-voice--forge--agents).

## Setup

Python 3.11, Windows or Mac.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Mac
pip install -r requirements.txt
python -m pytest
```

On Mac, give **Camera**, **Accessibility** and **Input Monitoring** permissions to the terminal or VS Code. Without them the cursor doesn't move and there's no error.

## How to run it

```bash
python run.py --mock              # simulator: hold F8 = eye closed, F7 = eye lost, F9 = pause
python run.py --video ojo.mp4     # real detection on a recorded video
python run.py --camera 1          # real detection with the endoscopic camera
python run.py --camera 1 --demo   # same, with the monitor in demo mode
```

Camera tools (SWE 1), to mount the camera and record the test video:

```bash
python -m eyeclick.vision.camera --probe                       # which index, resolution and real FPS
python -m eyeclick.vision.camera --record ojo.mp4 --camera 1   # 2 min with preview (q = stop)
```

If there's no `calib.json`, the pipeline calibrates on start (~8 s, follow the message on the monitor). Delete `calib.json` or press Recalibrate when the light changes or the camera moves.

## Architecture

One Python process. Detection runs in background threads and actions run in the main thread (tkinter). They connect **only** through an event queue (`bus.py`).

```
SWE 1 (background threads)                             SWE 2 (main thread)
camera -> detector + annotate -> blink_fsm --events--> bus --> mouse / feedback / logger / overlay / monitor
                    |                                                                             ^
                    +------------------------- EyeView (latest value, with lock) -----------------+
```

- **SWE 1 never touches the mouse, and SWE 2 never touches the camera.** They only share `events.py` and `config.py`.
- `EyeView` doesn't go through the queue. It's stored as a "latest value" so the monitor skips frames instead of piling them up.
- **Source interface** (implemented by both `vision/pipeline.py` and `sources/mock.py`): `start()`, `stop()`, `latest_view()`, `recalibrate()`, `set_threshold(value)`.
- **Subscribers**: each one has `handle(event)` and knows nothing about the others.

## Structure

```
CaleGlasss/
├── run.py                    # only reads arguments and calls app.start()            (SWE 2)
├── requirements.txt
├── conftest.py               # lets pytest import eyeclick
├── eyeclick/
│   ├── config.py             # shared thresholds                                     (both) ✅
│   ├── events.py             # EventType, EyeEvent, EyeView: the contract            (both) ✅
│   ├── bus.py                # queue + subscribers                                   (SWE 2)
│   ├── app.py                # builds the pieces for the chosen mode and wires them  (SWE 2)
│   ├── logic/
│   │   └── blink_fsm.py      # durations -> events, with debounce                    (SWE 1) ✅
│   ├── vision/               #                                                       (SWE 1)
│   │   ├── camera.py         # CameraSource and VideoFileSource (+ --probe / --record tools)  ✅
│   │   ├── detector.py       # pupil -> open / closed / lost                          ✅
│   │   ├── calibration.py    # 3 s eye open + 3 s eye closed -> calib.json            ✅
│   │   ├── annotate.py       # draws contour, center and status on the frame          ✅
│   │   └── pipeline.py       # thread: frame -> detector -> FSM -> bus + EyeView      ✅
│   ├── sources/
│   │   └── mock.py           # F8 = eye closed, F7 = lost; same interface as pipeline (SWE 2)
│   ├── actions/              #                                                       (SWE 2)
│   │   ├── mouse.py          # save the position and click there
│   │   ├── feedback.py       # beeps
│   │   └── logger.py         # events_log.csv
│   ├── ui/                   #                                                       (SWE 2)
│   │   ├── monitor.py        # window with the eye video, status and controls
│   │   └── overlay.py        # small floating indicator
│   └── bridge/               # glasses-bridge: voice + agents, same process as EyeClick  (stubs)
│       ├── listener.py       # long blink: approve the pending plan or listen (bus subscriber)
│       ├── stt.py            # faster-whisper
│       ├── forge_client.py   # POST to the Forge `glasses` web trigger (request or approve)
│       └── live_state.py     # polls SpacetimeDB for the newest pending plan (overlay note)
├── forge-app/                # Atlassian Forge app: issue panel deployed ✅, agents (stubs)
│   ├── manifest.yml          # issue panel active; agent modules commented out
│   ├── package.json          # from the jira-issue-panel-ui-kit template
│   ├── src/
│   │   ├── index.ts          # exports every handler
│   │   ├── frontend/index.jsx # issue panel UI (UI Kit)                                 ✅
│   │   ├── resolvers/index.ts # issue panel resolver                                    ✅
│   │   ├── triggers/
│   │   │   ├── glasses.ts    # voice requests and approvals
│   │   │   └── telegram.ts   # ✅ button and written requests
│   │   ├── queue/consumer.ts # dispatches: router, agent, execute
│   │   ├── agents/
│   │   │   ├── loop.ts       # Claude loop with tools
│   │   │   ├── router.ts     # decides which agent and creates the jobs
│   │   │   ├── jira_agent.ts # Jira agent prompt and tools
│   │   │   └── reporter.ts   # reporter prompt and tools
│   │   ├── execute/actions.ts # one function per plan action type
│   │   └── lib/
│   │       ├── claude.ts     # Claude client + model (claude-opus-5-5)
│   │       ├── stdb.ts       # writes the live state to SpacetimeDB
│   │       ├── jira.ts
│   │       ├── confluence.ts
│   │       └── telegram.ts
│   └── static/panel/         # Custom UI (extra)
├── stdb/                     # SpacetimeDB module (TypeScript), see stdb/README.md    (to do)
├── dashboard/                # web panel (Vite + SpacetimeDB SDK), see its README    (to do)
└── tests/
    ├── test_blink_fsm.py     # ✅ passes
    ├── test_vision.py        # ✅ passes (synthetic eye images, no camera needed)
    ├── test_bus.py
    ├── test_feedback.py / test_logger.py / test_mouse.py
    ├── test_monitor.py / test_overlay.py / test_mock.py
    └── conftest.py           # one shared Tk for the UI tests
```

Names are in English: the plan's `lentes.ts` is `glasses.ts` and `reportero.ts` is `reporter.ts`. `glasses-bridge` from the agent-team plan lives in `eyeclick/bridge/` instead of a top-level `glasses-bridge/` folder: it has to run in the same process as EyeClick (to listen to the bus and update the overlay), and Python can't import a package whose name has a hyphen. The TypeScript projects (`forge-app/`, `stdb/`, `dashboard/`) are separate and sit at the root.

✅ = already implemented. (stubs) = files created with their interface and a `TODO` list in the header comment, not implemented yet. To see every pending item:

```bash
git grep -n "TODO (SWE 1)"
git grep -n "TODO (SWE 2)"
git grep -n "TODO (bridge)"     # eyeclick/bridge/
git grep -n "TODO (agents)"     # forge-app/, stdb/
```

## Event contract

| Event | When |
|---|---|
| `EYE_CLOSED` | A closure started (SWE 2 saves the cursor position) |
| `STAGE_LEFT` | Closed for 0.5 s: opening now = left click (beep 1) |
| `STAGE_RIGHT` | Closed for 1.2 s: opening now = right click (beep 2) |
| `CLICK_LEFT` / `CLICK_RIGHT` | Eye opened within that range |
| `CANCELLED` | Natural blink, more than 3 s, or the image was lost |
| `EYE_LOST` | The camera can't see the eye |
| `CALIBRATED` | Calibration finished |

Right click: `EYE_CLOSED → STAGE_LEFT → STAGE_RIGHT → CLICK_RIGHT`. Blink: `EYE_CLOSED → CANCELLED`.

**Nobody changes `events.py` or `config.py` without telling the other person first.**

## Agent team (voice → Forge → agents)

```
glasses laptop (Python, one process)                    cloud
eyeclick bus --blink activation--> bridge/listener.py
                                   -> stt.py (faster-whisper, local)
                                   -> forge_client.py --POST--> forge-app triggers/glasses.ts
                                                                  -> queue/consumer.ts
                                                                     -> agents/router.ts -> jira_agent / reporter (agents/loop.ts + Claude)
                                                                     -> execute/actions.ts -> Jira, Confluence, Telegram
                                                                  -> lib/stdb.ts writes the state -> stdb/ (SpacetimeDB)
ui/overlay.py <-- bridge/live_state.py <--------------------------------------------- reads stdb/
                                                                  dashboard/ reads stdb/ too
Telegram -> triggers/telegram.ts (✅ approve, written requests) -> same queue
```

How the bridge plugs into EyeClick, without changing what already works:

- **`listener.py` is one more bus subscriber.** It gets a `handle(event)` and is registered in `app.py` like `mouse` or `feedback`. Starting the mic is triggered by a blink gesture.
- **Nothing slow runs in the main thread.** Recording, `stt.py` and `forge_client.py` run in their own thread; `handle()` only starts or stops them. Otherwise `bus.dispatch()` and the clicks freeze while Whisper transcribes.
- **`live_state.py` never touches tkinter directly.** It reads SpacetimeDB in its own thread and hands each update to the main thread (the same way `app.py` already does with F9 pause requests). Then the main thread calls `overlay.show(...)`.
- **Approvals:** the wearer approves a plan either from the glasses (`forge_client.py` → `glasses.ts`, "approve") or from Telegram (`telegram.ts`, ✅ button). Both go into the same queue.

Open decisions (agree on them before writing code):

- **Which gesture activates the mic.** It must not collide with clicks (0.5–3.0 s) or rest (> 3 s). If it needs a new event, it means changing `events.py`, so both SWEs have to agree.
- **Owner** of `eyeclick/bridge/`, `forge-app/`, `stdb/` and `dashboard/`.
- **How to start it:** for example, a `run.py` flag so `python run.py --mock` keeps working without the mic or network.
- **New dependencies** (`faster-whisper`, HTTP client, SpacetimeDB client) are added to `requirements.txt` when `bridge/` is implemented. The TypeScript projects keep their own `package.json`.

### Running the Forge app

The app (`eyeclick-agents`) is installed on the Jira demo site **one-atlas-hyek.atlassian.net** (development environment). Open any issue there to see its panel.

```bash
cd forge-app
npm install                                   # first time
forge lint
forge deploy -e development                   # after changing manifest.yml or dependencies
forge install --demo-site --product jira      # first time only
forge install --upgrade                       # when manifest.yml scopes change
forge tunnel                                  # leave it running: code changes show up when you reload the issue
```

To deploy you need to be logged in (`forge login`) and a member of the app's Developer Space.

**After changing `manifest.yml` (modules or scopes), restart `forge tunnel`.** It only reads the manifest when it starts; while it's running, Forge sends every call to it, and a function it doesn't know returns `424 Failed Dependency`.

#### `debug` web trigger: read a sprint

`forge-app/src/triggers/debug.ts` searches a sprint's issues with JQL as the app (`api.asApp().requestJira`) and returns Jira's JSON (`summary`, `status`, `assignee`, `priority`). Sprint ids come from `scripts/demo_ids.txt` (Sprint 12 = `5207`, the default).

```bash
cd forge-app
forge webtrigger create -f debug-webtrigger -s one-atlas-hyek.atlassian.net -p jira -e development
curl "<URL>"                  # Sprint 12
curl "<URL>?sprint=5208"      # another sprint
```

Each call logs `debug: sprint 5207 -> HTTP 200, 15 issues` in the `forge tunnel` terminal. A 401/403 means a scope is missing: add it to `manifest.yml`, `forge deploy`, `forge install --upgrade`. Anyone with the URL can read the sprint, so don't commit it, and remove or protect this trigger before the demo.

#### `glasses` web trigger: requests from the glasses

`forge-app/src/triggers/glasses.ts` receives a request and writes it to SpacetimeDB (`create_work` + `log_event` through `src/lib/stdb.ts`).

- Header `x-secret` must equal the `APPROVAL_SECRET` Forge variable, otherwise `401` and nothing is created.
- Body: `{ "type": "request", "text": "...", "person": "me", "request_id": "r1" }`.
- The same `request_id` twice returns `200` with `"duplicate": true` and doesn't create anything new.

Secrets live in encrypted Forge variables (`STDB_TOKEN`, `APPROVAL_SECRET`) and, for your notes, in the gitignored `stdb/.env` and `forge-app/.env` (which also holds `GLASSES_WEBTRIGGER_URL`).

```bash
cd forge-app
forge variables set --encrypt -e development STDB_TOKEN <token>       # from stdb/.env
forge variables set --encrypt -e development APPROVAL_SECRET <phrase>
forge webtrigger create -f glasses-webtrigger -s one-atlas-hyek.atlassian.net -p jira -e development
curl -X POST "<URL>" -H "x-secret: <APPROVAL_SECRET>" -H "Content-Type: application/json" \
     -d '{"type":"request","text":"move the pending items","person":"me","request_id":"r2"}'
```

After the receipt, `glasses` pushes `{ type: "agent", work_id, person }` to the **`agent-runs`** queue and answers (≈0.6 s warm; the first call after a deploy takes ~3 s while the function cold-starts). The queue consumer (`src/queue/consumer.ts`, function `consume-queue`) claims the work item and runs the Jira agent (`src/agents/jira_agent.ts`, Claude `claude-sonnet-5-5`): it reads Jira and sends the plan to Telegram as a numbered list with a **✅ Approve** button, without changing anything. In `forge logs` the trigger's lines come first, then `consumer: ...`. If the consumer never runs, check that `queue:` in `manifest.yml` matches `QUEUE_KEY` in `consumer.ts`.

Tapping ✅ (`ap:<proposal id>`) hits the `telegram` trigger: `approve_proposal` in stdb (a second tap answers "Already approved" and queues nothing), the message changes to "Approved, executing…", and `{ type: "execute", proposal_id }` goes to the same queue. The consumer then runs `start_execution`, applies each action in Jira (`src/execute/actions.ts`, one `record_action` row per change), `complete_proposal`, and sends `✅ Done` with each change and its `/browse/KEY` link. A 403 from Jira means a missing write scope (`write:jira-work`, `write:sprint:jira-software`); a 400, a wrong request body.

### Voice inside EyeClick (`--voice`)

```bash
.venv/Scripts/python run.py --mock --voice      # or --camera 1 --voice with the glasses
```

- **"Hey glasses, ..."** is how a Jira command starts. The microphone is always on; each utterance is transcribed locally with Whisper `tiny.en` (~0.4 s) and dropped unless it has the phrase, so nothing leaves the laptop until you say it. On the phrase it beeps and:
  - *"Hey glasses, move the open bugs to sprint 13"*: the rest of the sentence (transcribed again with `small.en`) is the request.
  - *"Hey glasses"* alone: after the beep it records the request.
  - *"Hey glasses, approve"*: approves the pending plan.
- **Long blink** = the eye closed for 3 s (`CANCEL_AT`, the eye module's `CANCELLED` event; in `--mock`, hold F8 for 3 s). With a pending plan it approves it (`{"type": "approve", "proposal_id"}` to `glasses`, via `glasses`, and the plan's Telegram message is edited to "Approved from the glasses"); with no plan it starts listening for a request.
- **F10** = talk: listens right away, without the phrase (fallback for a noisy room).
- The overlay gets a second line: `Say "Hey glasses, ..."`, `Plan ready: "Hey glasses, approve" or blink` while `live_state.py` sees a pending plan (it polls SpacetimeDB every 2 s), and "Listening…", "Approved ✓ executing"… while it works.
- Resting the eyes for 3 s also counts as a long blink, so `--voice` is opt-in. Whisper loads in the background; blink approvals work before it's ready.

Without EyeClick: `.venv/Scripts/python -m eyeclick.bridge --wake` runs the same wake loop in the terminal (`--no-send` only prints what it would send).

### Voice test (Enter instead of the blink)

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows; .venv/bin/pip on Mac
cp eyeclick/bridge/.env.example eyeclick/bridge/.env                    # URL, APPROVAL_SECRET, PERSON_ID, MIC_DEVICE
.venv/Scripts/python -m eyeclick.bridge --list-devices                 # find the glasses' Bluetooth mic -> MIC_DEVICE
.venv/Scripts/python -m eyeclick.bridge                                # Enter, talk; prints the text and the time
```

Speak **English**. Enter records at 16 kHz until 1 s of silence after you speak (or 8 s); the microphone stays open with 0.5 s of pre-roll, so a short "approve" isn't cut off. Whisper `small.en` (English-only, int8) transcribes it and it goes to `glasses` with a new `request_id` (uuid4). The first run downloads the model (~30 s). On a laptop CPU `small.en` takes ~2.5 s for a short sentence and `base.en` ~0.8 s: use `--model base.en` if it goes over 3 s. `--no-send` only transcribes; `--level` shows the mic's volume.

`glasses` then asks Claude (`agents/interpret.ts`, Haiku, ~1 s) what the transcript is:

| You say | It does |
|---|---|
| "um so move everything not finished in spring twelve to sprint thirteen" | request: *"Move all issues that were not finished in sprint 12 to sprint 13."* goes to the Jira agent; the receipt shows the clean instruction and what was heard |
| "approve", "yes go ahead" | approves the **newest** pending plan (same as ✅) |
| "reject", "no, cancel that" | rejects the newest pending plan; nothing changes in Jira |
| "thank you", noise | "🤔 Didn't get that" on Telegram, nothing runs |

The agent really changes the demo board, so restore it between rehearsals:

```bash
cd scripts
python demo_reset.py save      # once, with the demo as it should be (writes demo_snapshot.json)
python demo_reset.py restore   # sprint, status, assignee, priority back; new comments deleted
```

`forge tunnel` runs the code on your machine, where encrypted variables don't exist. Export them with the `FORGE_USER_VAR_` prefix before starting it, or stop the tunnel to hit the deployed version:

```powershell
cd forge-app
Get-Content ..\stdb\.env, .env | Where-Object { $_ -match '^(STDB_TOKEN|APPROVAL_SECRET|TELEGRAM_BOT_TOKEN|TELEGRAM_SECRET|ANTHROPIC_API_KEY)=' } | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:FORGE_USER_VAR_$k" $v }
forge tunnel
```

`npm run typecheck` type-checks `src/`. Don't add `"noEmit"` to `tsconfig.json`: Forge's bundler reads it and `forge deploy` fails with "TypeScript emitted no output".

## SWE 1 tasks: detection (camera → events)

Files: `eyeclick/vision/*`, `eyeclick/logic/blink_fsm.py`

- [ ] Connect the endoscopic camera; confirm the index, resolution and actual FPS (15 or more)
- [ ] Mount the camera low and to the side of the eye; dim or cover its LEDs
- [x] `camera.py`: `CameraSource` (thread that keeps only the latest frame) and `VideoFileSource`
- [x] `detector.py`: detect the pupil and decide open / closed / lost (+ Plan B: `USE_STD_ONLY`)
- [x] `calibration.py`: 3 s eye open + 3 s eye closed to set thresholds; save to `calib.json`
- [x] `blink_fsm.py`: durations → events, with debounce
- [x] `annotate.py`: draw what the detector found on the 320×240 frame
- [x] `pipeline.py`: tie it all together in one thread, publish events and store the latest `EyeView`
- [ ] Record 2 minutes of eye video to test without the person wearing the glasses (`--record`, see below)
- [x] pytest tests for the state machine (basic cases)
- [x] pytest tests for detection, calibration and pipeline on synthetic eye images (`tests/test_vision.py`)

## SWE 2 tasks: actions (events → computer)

Files: `eyeclick/bus.py`, `eyeclick/app.py`, `run.py`, `eyeclick/sources/mock.py`, `eyeclick/actions/*`, `eyeclick/ui/*`

- [x] `sources/mock.py`: simulate the eye with F8 and produce a fake `EyeView` (gray image with the status written on it)
- [x] `bus.py`: publish from any thread and dispatch in the main thread; enable `tests/test_bus.py`
- [x] `actions/mouse.py`: save the cursor position on close, click there on open, cooldown and pause
- [x] `actions/feedback.py`: beep at 0.5 s, a different beep at 1.2 s, double beep on click
- [x] `actions/logger.py`: log to `events_log.csv`
- [x] `ui/monitor.py`: eye video, progress bar, status, counters and controls
- [x] `ui/overlay.py`: always-visible floating indicator
- [x] `app.py` and `run.py`: build the pieces for the chosen mode and shut everything down cleanly
- [ ] Mac permissions (Accessibility, Input Monitoring, Camera) or test on Windows

## Agent team tasks (owner TBD)

- [x] `eyeclick/bridge/listener.py`: long blink approves the pending plan or listens for a request (`--voice`, not yet tried with the glasses)
- [x] `eyeclick/bridge/stt.py`: record until silence and transcribe with faster-whisper (Enter test: `python -m eyeclick.bridge`)
- [x] `eyeclick/bridge/forge_client.py`: POST the request to the `glasses` web trigger (approvals: pending)
- [x] `eyeclick/bridge/live_state.py`: poll SpacetimeDB every 2 s, overlay shows "Plan ready: say approve or blink"
- [x] `forge-app/`: app created from `jira-issue-panel-ui-kit`, deployed and installed on the demo site
- [ ] `forge-app/`: triggers (`glasses`, `telegram`), queue consumer, router, agents, actions, `lib/` (then uncomment their modules in `manifest.yml`)
- [ ] `stdb/`: SpacetimeDB module with the request/job state
- [ ] `dashboard/`: web panel that reads the same state
- [ ] `forge-app/static/panel/`: Custom UI (extra)

## Schedule

| Time | SWE 1 (detection) | SWE 2 (actions and monitor) |
|---|---|---|
| 0:00 – 0:30 | Together: structure, `events.py`, `config.py`, `blink_fsm.py`, environment | Together |
| 0:30 – 1:30 | Camera working, mounted on the glasses, eye video recorded; `camera.py` | `bus.py`, `sources/mock.py`, `actions/mouse.py`: clicks working with F8 |
| 1:30 – 3:00 | `detector.py`, `annotate.py`, `pipeline.py` tuned on the recorded video | `ui/monitor.py` with the mock's views; `feedback.py`, `logger.py`, `overlay.py` |
| 3:00 – 3:30 | **Integration:** `--video ojo.mp4`, then `--camera 1` | **Integration** |
| 3:30 – 5:00 | `calibration.py` + robustness to lighting and `EYE_LOST` | `app.py` clean shutdown, demo mode, bus tests |
| 5:00+ | Test with a real user; tune thresholds at the demo location | Demo rehearsal (open an app, close a window with right click) |

## Integration rules

- One branch per person. Only code that runs with `python run.py --mock` gets merged into `main`.
- If you need to change `events.py` or `config.py`, tell the other person first.
- At integration, test with the recorded video first, then with the person wearing the glasses.

**Demo goal:** zero false clicks in 2 minutes of normal use, and at least 9 out of 10 intentional clicks recognized.

## Plan B (in this order)

1. If pupil detection fails, use only the grayscale standard deviation (a closed eye looks flatter). Only `detector.py` changes.
2. If the endoscopic camera doesn't work, use a webcam facing the person with MediaPipe Face Landmarker (`eyeBlinkRight > 0.5`). Only `detector.py` changes.
3. For the demo, the F8 simulator can show the actions side even if the hardware fails.

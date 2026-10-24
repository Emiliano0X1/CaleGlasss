# CaleGlasss

Smart Glasses for Cal Hacks 13.0. **EyeClick**: a Python program reads an endoscopic camera pointed at one eye, measures how long each eye closure lasts, and turns it into a left or right click. The cursor is moved separately by the gyroscope (an ESP32 acting as a BLE mouse), so this module only handles clicks.

| Eye closed | Result |
|---|---|
| less than 0.4 s | Natural blink, ignored |
| 0.5 – 1.2 s | Left click |
| 1.2 – 3.0 s | Right click |
| more than 3.0 s | Cancelled (resting, does nothing) |

The click fires **when the eye opens**, at the position the cursor had **when it closed**. A beep plays at 0.5 s and a different one at 1.2 s.

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
│   └── ui/                   #                                                       (SWE 2)
│       ├── monitor.py        # window with the eye video, status and controls
│       └── overlay.py        # small floating indicator
└── tests/
    ├── test_blink_fsm.py     # ✅ passes
    ├── test_vision.py        # ✅ passes (synthetic eye images, no camera needed)
    ├── test_bus.py
    ├── test_feedback.py / test_logger.py / test_mouse.py
    ├── test_monitor.py / test_overlay.py / test_mock.py
    └── conftest.py           # one shared Tk for the UI tests
```

✅ = already implemented. Every other file has its interface defined and a `TODO` list in its docstring. To see every pending item:

```bash
git grep -n "TODO (SWE 1)"
git grep -n "TODO (SWE 2)"
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

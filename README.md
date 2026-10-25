# CaleGlasss

Smart Glasses for Cal Hacks 13.0. **EyeClick**: a Python program reads an endoscopic camera pointed at one eye, measures how long each eye closure lasts, and turns it into a left or right click. The cursor is moved by **Calestick**: an ESP32-S3 with an MPU-6050 gyroscope on the glasses that pairs with the computer as a Bluetooth (BLE) mouse. Turn your head and the cursor follows where you look (`firmware/Calemouse`). The two parts don't talk to each other: the ESP32 moves the cursor, EyeClick clicks.

| Eye closed | Result |
|---|---|
| less than 0.4 s | Natural blink, ignored |
| 0.5 – 1.2 s | Left click |
| 1.2 – 3.0 s | Right click |
| more than 3.0 s | **Drag**: the left button goes down where the cursor was when you closed your eye; turn your head to move; **open your eye to drop** |

The click fires **when the eye opens**, at the position the cursor had **when it closed**. A beep plays at 0.5 s, a different one at 1.2 s, and a rising two-tone at 3.0 s when the drag starts (falling two-tone when you drop). If the camera loses the eye mid-drag, or you pause or recalibrate, the button is released, so it never stays stuck down.

**Double click:** two left clicks within 1.5 s and 40 px of each other. The second one sends a real double click where the first one was.

**Drag:** press **Drag** on the dashboard (or **F10**) → left blink to grab → turn your head to move → left blink to drop. Pressing Drag/F10 again, a right click, or Pause cancels it and releases the button. The dashboard and floating indicator show the drag state the whole time.

**Dictation (lavalier mic):** look at the **mic** button on the floating indicator and blink (left click), or press **F11**. After a high beep, speak; it stops by itself after 1.5 s of silence (or blink on mic again). After a low beep the text is typed wherever the text cursor was. Clicking the indicator doesn't take focus away from that app. Speech is transcribed on the laptop with faster-whisper (no internet after the first run, nothing is logged). Settings are in `config.py`: `DICTATION_LANGUAGE` (`"en"`, `"es"`, or `None` to auto-detect), `DICTATION_MODEL` (`tiny`/`base`/`small`), `DICTATION_DEVICE` (`None` = Windows default mic, or part of its name such as `"USBAudio"`). The first run downloads the model (~145 MB); it then loads in the background when the app starts.

**Automatic dictation (`DICTATION_AUTO = True`, on by default):** no button needed. Blink into a text box in any app (browser field, Word, Notepad, chat) and just start talking. EyeClick checks with Windows UI Automation whether the focused element is an editable text box, and listens for *your* voice: the lavalier hears its wearer much louder than people nearby (`DICTATION_AUTO_RMS`). A short clip from just before you started is kept, so the first word isn't cut off. Because it could mistake a conversation for dictation, auto-dictated text is **not typed right away**: it appears under the floating indicator with a chime, then **left blink = type it**, **right blink = discard**, or do nothing for 10 s to discard. That confirming blink doesn't click, so the text cursor stays where it was. It doesn't start while paused or when EyeClick's own windows have focus. The mic button / F11 still work and type directly.

**Voice commands:** if everything you say is just **"enter"** it presses Enter, and just **"delete"** deletes the previous word (Ctrl+Backspace), in both manual and automatic dictation (no confirm blink needed). Inside a sentence the words are typed normally.

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

## ESP32 gyroscope mouse (Calestick)

The sketch is `firmware/Calemouse/Calemouse/Calemouse.ino` (Visual Micro solution: `firmware/Calemouse/Calemouse.slnx`; the Arduino IDE also opens the `.ino` directly). It only moves the cursor. All clicks come from EyeClick.

**Hardware:** ESP32-S3 + MPU-6050/6500/9250 (e.g. the blue MPU-92.65 board) over I²C: SDA → GPIO 8, SCL → GPIO 9, VCC → 3.3 V, GND → GND (address 0x68).

**Mounting:** the board stands upright with its pins on top (Y axis up), the X arrow along the temple (forward/back) and the chip facing out to the side. Turning your head left/right moves the cursor left/right; nodding moves it up/down. If a direction is backwards, flip **Invertir X** / **Invertir Y** on the settings page and press **Guardar**.

**Flash it once:**
1. Arduino IDE → Boards Manager: install **esp32 by Espressif**. Library Manager: install **HijelHID_BLEMouse** (`Wire`, `WiFi`, `WebServer` and `Preferences` come with the ESP32 core).
2. Board: **ESP32S3 Dev Module**. Select the ESP32's COM port and Upload.
3. Optional: Serial Monitor at 115200 should print `WHO_AM_I=` followed by `0x68` (MPU-6050), `0x70` (MPU-6500) or `0x71`/`0x73` (MPU-9250/9265 boards); `0xFF` or `0x00` means the sensor isn't answering, so check the wiring. It then prints which network it joined and its address.

**Every time you use it:**
1. Power the ESP32 and **keep your head still for ~1 s**. It calibrates the gyro and takes that position as "center".
2. The first time only: pair **Calestick** in the computer's Bluetooth settings. After that it reconnects on its own.
3. Look at what you want to click. The cursor moves by the same amount your head turns (**Sensibilidad**, default 40 px per degree), so a small turn gives a small, precise move. When the cursor stops at a screen edge and your head keeps turning, the "center" shifts with you, the same as lifting a mouse and putting it back down.
4. On Windows, turn off **Settings → Bluetooth & devices → Mouse → Additional mouse settings → Pointer Options → Enhance pointer precision**. Otherwise Windows adds acceleration and the cursor stops lining up with your head.

**Modes:** *Modo apuntar* (default) maps how far you turn your head to cursor distance. Turn it off on the settings page to get the old joystick mode, where the tilt angle sets the cursor speed (the dead zone, range, max speed and curve sliders only apply to that mode). *Filtro de temblor* hides small shaking while you hold your head still; raise it if the cursor jitters, lower it if slow, fine moves feel sticky.

**Wi-Fi (optional):** copy `firmware/Calemouse/Calemouse/wifi_secrets.example.h` to `wifi_secrets.h` in the same folder and put your network name and password in it (git ignores that file). On power-on the ESP32 tries that network for 10 s. If it can't connect, or there's no `wifi_secrets.h`, it creates its own network **Calestick-AP** (password `12345678`). The mouse works from the first second either way; Wi-Fi is only for the settings page. Serial Monitor (115200) prints which network it joined and its address.

**Recalibrate by shaking your head (no website, no Wi-Fi switching):** shake your head left-right quickly for ~2–3 s (8 fast reversals). The cursor freezes; **hold still** for a moment and the ESP32 recalibrates the gyro and recenters, the same as the **Calibrar giro** button. The dashboard and floating indicator show **GYRO: hold still...** and then **gyro calibrated ✓** with a beep (blinks don't click meanwhile). The ESP32 can't send text to the laptop (it's only a Bluetooth mouse), so it signals with the cursor itself: a tiny down-and-exactly-back blip at the start and a right-and-back blip at the end, which EyeClick recognizes (`eyeclick/actions/gyro_watch.py`; EyeClick's own cursor jumps are ignored). If your board has an RGB LED it also turns yellow while calibrating and green when done. If you don't hold still within 8 s it gives up and EyeClick says *gyro not calibrated*.

**Gyro drift:** a gyroscope reads a small turning speed (bias) even when still, and it changes as the chip warms up. Yaw drifts most because, unlike up/down, it has no gravity reference. The firmware runs the sensor's ~41 Hz filter, and whenever your head has been still for 0.3 s it re-learns the bias and holds the cursor at exactly zero, so the cursor doesn't creep on its own.

**Settings page (optional):** open **http://calestick.local** from any device on the same network (or **http://192.168.4.1** when you're on Calestick-AP). It shows the sensor in 3D and has sliders for dead zone, range, max speed, curve, smoothing and the gyro filter, plus switches to invert or swap axes and to turn the mouse off. Buttons: **Recentrar** (take the current head position as center), **Calibrar giro** (hold still), **Guardar** (keep settings after a reboot; otherwise changes are lost on power-off), **Valores de fábrica**.

**How it works with EyeClick:** you move the cursor with your head and click by closing your eye. Closing your eye can move your head a little. So EyeClick saves the cursor position when the eye closes and clicks *there* when it opens, not where the cursor drifted.

## How to run it

1. Power the ESP32 with your head still (it calibrates, then reconnects to the computer as Calestick).
2. Start EyeClick:

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

**Any camera angle (eye model):** open/closed is decided by a small neural network (`eyeclick/vision/eye_model.onnx`, 250 KB, ~2 ms per frame with onnxruntime). It works with the camera upside down or sideways, and with the iris cut off by the frame edge or out of frame entirely (only the white of the eye showing), where the classic "darkest round blob = pupil" detector fails. It was trained on `ojo.mp4`, `ojo2.mp4` and `ojo3.mp4`, hand-labeled, with random rotations, mirroring, zoom/shift and lighting changes. Calibration still matters: it measures the model's score on *your* open and closed eye and puts the cutoff 40% of the way from closed to open (missing a click is better than a false one). If the model can't tell them apart during calibration, it falls back to pupil detection and says so. The overlay text shows `model +x.x cut y.y`.

On `ojo3.mp4` (camera upside down, iris cut off): pupil detection got 60–93% of frames right depending on the calibration moment; the model gets 99%+ and produces exactly the intended clicks with no false ones. On an angle it was **never trained on** it got 88–97% after calibration; on a hand-held video it never saw, 98.5%. So for the demo, **record ~30 s at the real demo angle** (`--record`, blink a few times with short and long closures), label it in `tools/eye_model/dataset.py` and retrain (`tools/eye_model/train.py`, ~6 min on CPU).

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
├── tools/eye_model/          # labels + training script for eye_model.onnx (needs torch)
├── firmware/
│   └── Calemouse/            # ESP32-S3 + MPU-6050 head-tilt BLE mouse "Calestick" (Arduino / Visual Micro)
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
│   │   ├── model.py          # eye_model.onnx: open/closed at any angle                ✅
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
| `STAGE_DRAG` | Closed for 3.0 s: left button pressed, the head drags (rising beep) |
| `DRAG_END` | Eye opened (or lost) while dragging: button released |
| `CANCELLED` | Natural blink, or the image was lost before the drag |
| `EYE_LOST` | The camera can't see the eye |
| `CALIBRATED` | Calibration finished |

Right click: `EYE_CLOSED → STAGE_LEFT → STAGE_RIGHT → CLICK_RIGHT`. Drag: `EYE_CLOSED → STAGE_LEFT → STAGE_RIGHT → STAGE_DRAG → DRAG_END`. Blink: `EYE_CLOSED → CANCELLED`.

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

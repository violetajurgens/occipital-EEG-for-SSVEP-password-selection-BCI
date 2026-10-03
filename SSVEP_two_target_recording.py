"""TWO-TARGET SSVEP CALIBRATION — NEXT (10 Hz), SELECT (12 Hz).

Run this full program in PsychoPy Coder. Close Arduino Serial Monitor, CHORDS,
and other apps using COM5. Keep your existing eight-channel Nano CHORDS firmware.
SPACE starts 30 prompted trials: 15 NEXT and 15 SELECT, randomized in balanced
blocks. Big yellow text/border tells you where to look BEFORE stimulation.
Both larger boxes then flicker together for 3.5 s. Look directly at the named
box's white dot until REST; there is no look-away task. Each trial has a 0.75 s
cue and 1 s rest. ESC stops and saves the partial recording.

At ~60 Hz: NEXT = 6 frames/cycle (3 white, 3 black), SELECT = 5 frames/cycle
(2 white, 3 black). All frames use one shared frame counter and full-screen VSync.
All A0–A7 samples are saved; offline analysis uses A7. No LSL or LabRecorder.

Saves six matching files inside SSVEP_two_target_results/<timestamp>: EEG CSV,
anchors CSV, markers CSV, transitions CSV, frame_intervals CSV, session JSON.
Run SSVEP_two_target_analysis.py afterward and select the new EEG CSV.
This is calibration only. NEXT/SELECT are the eventual calculator commands;
this program does not yet move a calculator cursor or enter numbers.
USB reception and software flip timestamps estimate synchronization; they do
not measure physical light onset or fully calibrate unknown hardware latency.
"""

from pathlib import Path
import csv
import ctypes
import json
import random
import threading
import time
from datetime import datetime

COM_PORT = "COM5"
BAUD_RATE = 115200
NUM_CHANNELS = 8
EEG_CHANNEL = "A7"           # Saved for analysis; all eight channels are recorded.
NOMINAL_EEG_FS = 250.0
LABELS = ("NEXT", "SELECT")
CYCLE_FRAMES = {"NEXT": 6, "SELECT": 5}
ON_FRAMES = {"NEXT": 3, "SELECT": 2}
REPEATS_PER_TARGET = 15
CUE_S = 0.75
FLICKER_S = 3.50            # 0.25 s settling + 3.00 s analysis + 0.25 s guard.
REST_S = 1.00
PREROLL_S = 1.00
POSTROLL_S = 1.00
SCREEN = 0
BOX_SIZE = 0.28
POSITIONS = {"NEXT": (-0.60, 0.0), "SELECT": (0.60, 0.0)}


class ChordsDecoder:
    """Incremental parser; sample indices preserve detected missing packets."""
    def __init__(self, channels=8):
        self.channels = channels
        self.length = 4 + 2 * channels
        self.buffer = bytearray()
        self.previous = None
        self.index = -1
        self.bad = 0
        self.lost = 0
        self.duplicates = 0

    def feed(self, data):
        self.buffer.extend(data)
        rows = []
        while len(self.buffer) >= self.length:
            pos = self.buffer.find(b"\xc7\x7c")
            if pos < 0:
                self.buffer[:] = b"\xc7" if self.buffer[-1] == 0xC7 else b""
                break
            if pos:
                del self.buffer[:pos]
            if len(self.buffer) < self.length:
                break
            if self.buffer[self.length - 1] != 1:
                self.bad += 1
                del self.buffer[0]
                continue
            packet = self.buffer[:self.length]
            del self.buffer[:self.length]
            counter = packet[2]
            if counter == self.previous:
                self.duplicates += 1
                continue
            lost = 0 if self.previous is None else (counter - self.previous - 1) % 256
            self.index += 1 + lost
            self.previous = counter
            self.lost += lost
            values = [int.from_bytes(packet[3+2*c:5+2*c], "big")
                      for c in range(self.channels)]
            rows.append([self.index, counter, lost, *values])
        return rows


class Acquisition:
    def __init__(self, serial_port, clock):
        self.port = serial_port
        self.clock = clock
        self.decoder = ChordsDecoder(NUM_CHANNELS)
        self.eeg = []
        self.anchors = []
        self.stop_event = threading.Event()
        self.error = None
        self.last_batch_time = None
        self.thread = threading.Thread(target=self._reader, daemon=True)

    def _reader(self):
        try:
            while not self.stop_event.is_set():
                count = self.port.in_waiting
                if not count:
                    self.stop_event.wait(0.0005)
                    continue
                data = self.port.read(count)
                received = self.clock()
                rows = self.decoder.feed(data)
                if rows:
                    gap = 0.0 if self.last_batch_time is None else received-self.last_batch_time
                    self.eeg.extend(rows)
                    self.anchors.append([received, rows[-1][0], len(rows), gap])
                    self.last_batch_time = received
        except Exception as exc:
            self.error = repr(exc)

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=2)


def write_csv(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def main():
    # Lazy imports let the packet decoder be checked without PsychoPy or hardware.
    import numpy as np
    import serial
    from psychopy import visual, core, event

    if NUM_CHANNELS != 8:
        raise ValueError("This program is configured for the eight-channel Nano firmware.")
    base = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out = base / "SSVEP_two_target_results" / stamp
    out.mkdir(parents=True)
    prefix = "SSVEP_two_target_"
    zero = time.perf_counter()
    clock = lambda: time.perf_counter() - zero
    seed = random.SystemRandom().randrange(2**32)
    rng = random.Random(seed)
    order = []
    for _ in range(REPEATS_PER_TARGET):
        block = list(LABELS)
        rng.shuffle(block)
        order.extend(block)
    markers, transitions, frames = [], [], []
    session = {
        "schema_version": 1, "paradigm": "two_target_simultaneous_cca_baseline",
        "stamp": stamp, "completed": False, "aborted": False, "error": None,
        "com_port": COM_PORT, "baud_rate": BAUD_RATE, "num_channels": NUM_CHANNELS,
        "eeg_channel": EEG_CHANNEL, "nominal_eeg_fs": NOMINAL_EEG_FS,
        "command_actions": {"NEXT": "cycle to next option", "SELECT": "choose highlighted option"},
        "labels": list(LABELS), "cycle_frames": CYCLE_FRAMES, "on_frames": ON_FRAMES,
        "random_seed": seed, "trial_order": order, "repeats_per_target": REPEATS_PER_TARGET,
        "cue_s": CUE_S, "flicker_s": FLICKER_S, "rest_s": REST_S,
        "analysis_skip_s": 0.25, "analysis_window_s": 3.0,
        "positions_height_units": POSITIONS, "box_size_height_units": BOX_SIZE,
        "timing_note": "USB anchors estimate host-to-sample mapping; unknown transport/display latency remains.",
    }
    port = acq = win = None
    last_flip = None
    try:
        print("Opening", COM_PORT, "— close other serial programs first.")
        port = serial.Serial(COM_PORT, BAUD_RATE, timeout=0, write_timeout=1)
        time.sleep(2.0)  # Nano resets when the port opens.
        port.reset_input_buffer()
        acq = Acquisition(port, clock)
        acq.thread.start()
        port.write(b"START\n")
        deadline = clock()+5
        while len(acq.eeg) < 100 and clock() < deadline:
            if acq.error:
                raise RuntimeError(acq.error)
            time.sleep(0.01)
        if len(acq.eeg) < 100:
            raise RuntimeError("No valid eight-channel CHORDS stream. Check COM_PORT and firmware.")

        size = (1920, 1080)
        if hasattr(ctypes, "windll") and SCREEN == 0:
            size = (ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1))
        win = visual.Window(size=size, fullscr=True, screen=SCREEN, units="height",
                            color="black", allowGUI=False, waitBlanking=True)
        win.mouseVisible = False
        if win.size[0]/win.size[1] < 1.5:
            raise RuntimeError("Use a landscape display (aspect ratio >= 1.5) for this target layout.")
        text = visual.TextStim(win, height=0.047, wrapWidth=1.35, color="yellow", pos=(0, 0.30))
        rest_text = visual.TextStim(win, text="REST", height=0.047, color="yellow", pos=(0, 0.30))
        help_text = visual.TextStim(win, height=0.031, wrapWidth=1.35, color="white")
        boxes = {label: visual.Rect(win, width=BOX_SIZE, height=BOX_SIZE, pos=POSITIONS[label],
                    fillColor=(-0.55,)*3, lineColor="white", lineWidth=2) for label in LABELS}
        dots = {label: visual.Circle(win, radius=0.007, pos=POSITIONS[label],
                    fillColor="white", lineColor="white") for label in LABELS}
        names = {label: visual.TextStim(win, text=label, height=0.035, color="white",
                    pos=(POSITIONS[label][0], -0.20)) for label in LABELS}
        borders = {label: visual.Rect(win, width=BOX_SIZE+0.035, height=BOX_SIZE+0.035,
                    pos=POSITIONS[label], fillColor=None, lineColor="yellow", lineWidth=4) for label in LABELS}

        def check():
            if "escape" in event.getKeys(keyList=["escape"]):
                raise KeyboardInterrupt
            if acq.error:
                raise RuntimeError("Serial reader failed: "+acq.error)
            if acq.last_batch_time is not None and clock()-acq.last_batch_time > 2:
                raise RuntimeError("EEG stream stopped for more than two seconds.")

        def draw(states=None, target=None, message=None):
            for label in LABELS:
                boxes[label].fillColor = ("white" if states[label] else "black") if states else (-0.55,)*3
                boxes[label].draw()
                dots[label].draw()
                names[label].draw()
            if target:
                borders[target].draw()
            if message:
                if message == "REST":
                    rest_text.draw()
                else:
                    if text.text != message:
                        text.text = message
                    text.draw()

        def flip(phase, trial=0, target="", stimulus_frame=-1, states=None, changed=(), marker=None):
            nonlocal last_flip
            # Capture all marker timestamps inside the same flip callback/shared perf_counter clock.
            timing = {}
            def capture():
                timing["t"] = clock()
            win.callOnFlip(capture)
            win.flip()
            t = timing["t"]
            dt = "" if last_flip is None else t-last_flip
            last_flip = t
            frames.append([t, dt, phase, trial, target, stimulus_frame])
            if marker:
                markers.append([t, marker, trial, target])
            if states:
                for label in changed:
                    transitions.append([t, trial, target, label, stimulus_frame, states[label]])
            return t

        # Measure refresh on the actual full-screen surface, with serial acquisition running.
        samples = []
        for i in range(180):
            check()
            draw(message="Measuring display timing...")
            t = flip("refresh_measurement")
            if i >= 60:
                samples.append(t)
        intervals = np.diff(samples)
        median = float(np.median(intervals))
        good = intervals[(intervals > .7*median) & (intervals < 1.3*median)]
        if len(good) < 50:
            raise RuntimeError("Unstable refresh measurement. Check full-screen display settings.")
        fps = 1.0/float(np.median(good))
        if not 58 <= fps <= 62:
            raise RuntimeError(f"Measured {fps:.2f} Hz. Set the monitor to 60 Hz before this baseline.")
        if float(np.mean(intervals > 1.5/fps)) > .02:
            raise RuntimeError("Too many dropped frames during refresh measurement (>2%).")
        actual = {label: fps/CYCLE_FRAMES[label] for label in LABELS}
        session.update({"measured_refresh_hz": fps, "actual_frequencies_hz": actual,
                        "display_size_pixels": [int(v) for v in win.size]})
        print("Measured refresh:", round(fps, 4), "Hz; frequencies:", actual)
        # Warm the REST glyphs before the first measured flicker offset.
        draw(message="REST")
        flip("text_warmup")
        help_text.text = ("TWO-TARGET SSVEP CALIBRATION\n\n"
            "Look directly at the box named in the yellow cue.\n"
            "NEXT (left) and SELECT (right) flicker together.\n"
            "Keep looking at your chosen box's white dot until REST.\n\n"
            "30 trials: 15 per target; about 3 minutes.\nSPACE starts. ESC stops and saves.")
        event.clearEvents()
        while True:
            check()
            help_text.draw()
            flip("instructions")
            if "space" in event.getKeys(keyList=["space"]):
                break

        def static_period(seconds, phase, trial=0, target="", message=None, marker=None, border=False):
            for i in range(max(1, round(seconds*fps))):
                check()
                draw(target=target if border else None, message=message)
                flip(phase, trial, target, marker=marker if i == 0 else None)

        static_period(PREROLL_S, "preroll", marker="RECORDING_START", message="Get ready")
        flicker_frames = round(FLICKER_S*fps)
        session["flicker_frames"] = flicker_frames
        session["completed_trials"] = 0
        for trial, target in enumerate(order, 1):
            static_period(CUE_S, "cue", trial, target,
                f"LOOK AT {target}\nTrial {trial} / {len(order)}", "CUE_ON", border=True)
            previous = None
            for frame in range(flicker_frames):
                check()
                states = {label: int(frame % CYCLE_FRAMES[label] < ON_FRAMES[label]) for label in LABELS}
                changed = [label for label in LABELS if previous is None or states[label] != previous[label]]
                # Identical static labels/dots throughout; no cue, moving text, or target highlight.
                draw(states=states)
                flip("flicker", trial, target, frame, states, changed,
                     "FLICKER_ON" if frame == 0 else None)
                previous = states
            static_period(REST_S, "rest", trial, target, "REST", "FLICKER_OFF")
            session["completed_trials"] += 1
        static_period(POSTROLL_S, "postroll", message="Finished", marker="RECORDING_END")
        session["completed"] = True

    except KeyboardInterrupt:
        session["aborted"] = True
        markers.append([clock(), "ABORT", 0, ""])
        print("Aborted. Saving completed and partial recording.")
    except Exception as exc:
        session["error"] = repr(exc)
        markers.append([clock(), "ERROR", 0, ""])
        print("Recording error:", exc)
    finally:
        if acq:
            acq.close()
        if port:
            try:
                port.write(b"STOP\n")
            except Exception:
                pass
            try:
                port.close()
            except Exception as exc:
                session["cleanup_serial_error"] = repr(exc)
        if win:
            try:
                win.close()
            except Exception as exc:
                session["cleanup_display_error"] = repr(exc)
        if acq:
            session.update({"valid_packets": len(acq.eeg), "bad_packets": acq.decoder.bad,
                "detected_lost_packets": acq.decoder.lost, "duplicate_packets": acq.decoder.duplicates,
                "serial_error": acq.error})
            write_csv(out/(prefix+"EEG_"+stamp+".csv"),
                ["sample_index", "packet_counter", "lost_before_packet", *[f"A{i}" for i in range(NUM_CHANNELS)]], acq.eeg)
            write_csv(out/(prefix+"anchors_"+stamp+".csv"),
                ["host_time_s", "newest_sample_index", "packets_in_batch", "read_gap_s"], acq.anchors)
        write_csv(out/(prefix+"markers_"+stamp+".csv"), ["host_time_s", "event", "trial", "attended_target"], markers)
        write_csv(out/(prefix+"transitions_"+stamp+".csv"),
            ["host_time_s", "trial", "attended_target", "flicker_stimulus", "stimulus_frame", "state"], transitions)
        write_csv(out/(prefix+"frame_intervals_"+stamp+".csv"),
            ["host_time_s", "frame_interval_s", "phase", "trial", "attended_target", "stimulus_frame"], frames)
        (out/(prefix+"session_"+stamp+".json")).write_text(json.dumps(session, indent=2), encoding="utf-8")
        print("Saved to:", out)
    if session["error"]:
        raise RuntimeError(session["error"])


if __name__ == "__main__":
    main()

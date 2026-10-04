"""
SSVEP PASSWORD / PIN BCI — TWO TARGETS: NEXT and SELECT
=======================================================

Purpose
-------
Enter a fixed-length numeric password using only two SSVEP commands:

    NEXT   = move the highlighted digit 0 -> 1 -> ... -> 9 -> 0
    SELECT = append the highlighted digit and keep it highlighted

The program is designed for the user's current two-target calibration:
    NEXT   : 6 frames/cycle, 3 white + 3 black  (~10 Hz on a 60 Hz display)
    SELECT : 5 frames/cycle, 2 white + 3 black  (~12 Hz on a 60 Hz display)
    EEG    : CHORDS / Arduino Nano, A7 channel
    Serial : 115200 baud
    Packet : C7 7C counter [A0_hi A0_lo ... A7_hi A7_lo] 01
    Filter : 4-30 Hz, 4th-order Butterworth
    CCA    : fundamental + second harmonic
    Window : skip first 0.25 s, analyze the following 3.00 s

This is a BLOCK-ONLINE decoder: each command is decided after a complete 3.5 s
flicker epoch. The full epoch is zero-phase filtered, then the middle 3.0 s is
classified. That makes the live decision closely match the offline calibration
logic while keeping the interface interactive after each epoch.

Dependencies
------------
Run from PsychoPy Coder / PsychoPy Python with:
    numpy
    scipy
    pyserial
    psychopy

Before running
--------------
1. Keep the Arduino/CHORDS firmware running exactly as for calibration.
2. Put electrodes in the same configuration used for the successful calibration.
3. Set SERIAL_PORT below if auto-detection is ambiguous (example: "COM5").
4. The program will ask you to choose the generated
   SSVEP_two_target_classifier_config.json from your calibration analysis.
5. PASSWORD_LENGTH is 4 by default; change it below if needed.

Controls
--------
Connection recovery
-------------------
Retries automatically if the Nano is absent, busy, still booting, or silent.
Sends START\n after each port open. A >0.90 s packet pause closes/reopens the
port. Interrupted decisions are rejected; the PIN and highlighted digit stay.
Every reopen creates a separate sample/timing generation, then requires 2 s of
fresh EEG before resuming. Timing is checked AFTER each complete flicker epoch,
using the most timely reception anchor in each 0.10 s interval over up to 15 s
of recent history. Sparse USB batches are supported: six retained anchors over
at least 3 s are required. After flicker, wait for a timing anchor beyond its
offset, rather than assuming the last batch arrives within 0.20 s.
Delayed USB reads remain in the raw log but are not used as precise acquisition
timestamps. The residual limit still applies to the selected timing anchors;
absolute fixed USB/electronics latency is not measured by this fit.
Auto discovery follows a USB
serial number when available; ambiguous devices require SERIAL_PORT. ESC works
while waiting. Close other apps that hold the COM port before running.

SPACE : start the BCI after setup
ESC   : quit at any time

Output
------
A timestamped folder is created beside this script containing:
    decisions.csv
    EEG.csv
    anchors.csv
    connection_events.csv
    frames.csv
    session.json

The final password is also shown on screen and printed in the console.
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
from threading import Thread, Lock, Event as ThreadEvent
from bisect import bisect_left
import csv
import json
import math
import time
import traceback

import numpy as np
from scipy.signal import butter, sosfiltfilt
import serial
from serial.tools import list_ports

from psychopy import visual, core, event, sound


# =============================================================================
# USER SETTINGS
# =============================================================================

SERIAL_PORT = None          # e.g. "COM5". Leave None for auto-detection.
PROGRAM_REVISION = "2026-10-04 sparse USB batch recovery; keep selected digit highlighted"
BAUD_RATE = 115200
PASSWORD_LENGTH = 4

# Audible confirmation after a SELECT command actually enters a digit.
SELECT_BEEP_HZ = 880
SELECT_BEEP_S = 0.15
SELECT_BEEP_VOLUME = 0.8

FULLSCREEN = True
SCREEN_INDEX = 0

# Set True if you want the program to refuse a config whose offline pilot did
# not pass the 90% / per-target criteria. False is more convenient for testing.
REQUIRE_PASSED_CALIBRATION = False

# Timing is deliberately fixed to match the current calibration.
SKIP_S = 0.25
WINDOW_S = 3.00
FILTER_PAD_S = 0.25
FLICKER_FRAMES = 210        # 3.5 s at 60 Hz; divisible by both 6 and 5.
REST_S = 0.80
SERIAL_WARMUP_S = 2.0
SERIAL_BOOT_WAIT_S = 2.0     # Nano may reset on every port open.
SERIAL_FIRST_PACKET_TIMEOUT_S = 5.0
SERIAL_RETRY_S = 1.0
SERIAL_START_COMMAND = b"START\n"  # Standard CHORDS firmware stream command.
SERIAL_POST_EPOCH_MAX_WAIT_S = 1.20
SERIAL_POST_EPOCH_GUARD_S = 0.025
SERIAL_BURST_DRAIN_S = 0.010

# Current two-target frame patterns.
CYCLE_FRAMES = {"NEXT": 6, "SELECT": 5}
ON_FRAMES = {"NEXT": 3, "SELECT": 2}
LABELS = ("NEXT", "SELECT")

# Signal processing.
FILTER_LOW_HZ = 4.0
FILTER_HIGH_HZ = 30.0
FILTER_ORDER = 4
HARMONICS = 2
EEG_CHANNEL = "A7"
A7_INDEX = 7

# QA thresholds copied from the offline analysis where applicable.
MAX_ANCHOR_P95_SAMPLES = 5.0
TIMING_ANCHOR_BIN_S = 0.10
TIMING_HISTORY_S = 15.0
MIN_TIMING_ANCHORS = 6
MIN_TIMING_SPAN_S = 3.0
NOMINAL_SAMPLE_RATE_HZ = 250.0
MAX_READ_GAP_S = 0.90
MAX_CLIPPED_FRACTION = 0.01
MIN_RAW_STD = 0.10
MIN_FILTERED_STD = 0.01

# Display sanity range. The current 6/5 frame patterns assume a ~60 Hz monitor.
MIN_REFRESH_HZ = 58.0
MAX_REFRESH_HZ = 62.0


# =============================================================================
# EXCEPTIONS
# =============================================================================

class UserAbort(Exception):
    pass


class ConnectionInterrupted(ValueError):
    """Reject a decision; the acquisition worker will reconnect automatically."""
    pass


class TimingAlignmentError(ValueError):
    def __init__(self, message: str, diagnostics: dict):
        super().__init__(message)
        self.diagnostics = diagnostics


# =============================================================================
# SMALL UTILITIES
# =============================================================================

def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def check_escape() -> None:
    if "escape" in event.getKeys(keyList=["escape"]):
        raise UserAbort()


def safe_float(x, default=float("nan")):
    try:
        return float(x)
    except Exception:
        return default


def choose_config_file() -> Path | None:
    """Choose the JSON emitted by SSVEP_two_target_analysis.py."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            name = filedialog.askopenfilename(
                title="Choose SSVEP_two_target_classifier_config.json",
                filetypes=[
                    ("SSVEP classifier config", "SSVEP_two_target_classifier_config.json"),
                    ("JSON files", "*.json"),
                ],
            )
        finally:
            root.destroy()
        return Path(name).resolve() if name else None
    except Exception as exc:
        print("Could not open the file chooser:", exc)
        typed = input("Paste the full path to SSVEP_two_target_classifier_config.json: ").strip()
        return Path(typed).expanduser().resolve() if typed else None


def validate_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))

    expected = {
        "algorithm": "standard_cca_argmax_two_target",
        "eeg_channel": EEG_CHANNEL,
        "labels": list(LABELS),
        "cycle_frames": CYCLE_FRAMES,
        "on_frames": ON_FRAMES,
    }
    for key, wanted in expected.items():
        got = cfg.get(key)
        if got != wanted:
            raise ValueError(
                f"Classifier config mismatch for {key}: expected {wanted!r}, got {got!r}. "
                "Choose the JSON from the CURRENT NEXT/SELECT calibration."
            )

    if abs(float(cfg.get("window_s", -1)) - WINDOW_S) > 1e-9:
        raise ValueError("Config window_s is not the required 3.00 s.")
    if abs(float(cfg.get("skip_after_flicker_on_s", -1)) - SKIP_S) > 1e-9:
        raise ValueError("Config skip_after_flicker_on_s is not the required 0.25 s.")
    if int(cfg.get("harmonics", -1)) != HARMONICS:
        raise ValueError("Config harmonics does not match the live decoder.")

    filt = cfg.get("filter", {})
    if (
        abs(float(filt.get("low_hz", -1)) - FILTER_LOW_HZ) > 1e-9
        or abs(float(filt.get("high_hz", -1)) - FILTER_HIGH_HZ) > 1e-9
        or int(filt.get("order", -1)) != FILTER_ORDER
    ):
        raise ValueError("Config filter does not match 4-30 Hz, fourth-order Butterworth.")

    if REQUIRE_PASSED_CALIBRATION and not bool(cfg.get("calibration_ok")):
        raise ValueError(
            "This config did not pass the offline pilot criterion and "
            "REQUIRE_PASSED_CALIBRATION=True."
        )

    return cfg


def resolve_serial_port() -> str:
    if SERIAL_PORT:
        return SERIAL_PORT

    ports = list(list_ports.comports())
    if not ports:
        raise RuntimeError("No serial ports found. Connect the Arduino Nano and try again.")

    if len(ports) == 1:
        return ports[0].device

    keywords = ("arduino", "ch340", "ch341", "usb serial", "usb-serial", "wch")
    likely = [p for p in ports if any(k in (p.description or "").lower() for k in keywords)]
    if len(likely) == 1:
        return likely[0].device

    print("\nAvailable serial ports:")
    for p in ports:
        print(f"  {p.device:8s}  {p.description}")
    raise RuntimeError(
        "More than one serial port is available and auto-detection is ambiguous. "
        "Set SERIAL_PORT near the top of this script, for example SERIAL_PORT = 'COM5'."
    )


# =============================================================================
# CHORDS SERIAL ACQUISITION
# =============================================================================

class ChordsAcquisition:
    """Continuously decode 20-byte CHORDS packets in a background thread."""

    HEADER = b"\xC7\x7C"
    PACKET_LEN = 20
    END_BYTE = 0x01

    def __init__(self, port: str | None, baud: int = BAUD_RATE):
        self.port = port
        self.requested_port = port
        self.baud = baud
        self.ser: serial.Serial | None = None
        self.thread: Thread | None = None
        self.stop_event = ThreadEvent()
        self.lock = Lock()

        self.buffer = bytearray()
        self.sample_indices: list[int] = []
        self.counters: list[int] = []
        self.channels: list[tuple[int, ...]] = []
        self.anchors: list[dict] = []

        self.last_counter: int | None = None
        self.current_sample_index: int | None = None
        self.last_anchor_time: float | None = None
        self.total_missing_samples = 0
        self.total_bad_packets = 0
        self.thread_error: str | None = None
        self.generation = 0
        self.connected = False
        self.status = "Waiting for Nano"
        self.segment_start = 0
        self.anchor_start = 0
        self.segment_ids: list[int] = []
        self.connection_events: list[dict] = []
        self.device_identity = None

    def start(self) -> None:
        # Opening, boot waiting and retries run off the display thread.
        self.stop_event.clear()
        self.thread = Thread(target=self._run, name="CHORDS-reader", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            if self.thread is not None:
                self.thread.join(timeout=1.0)

    def _status(self, message: str) -> None:
        with self.lock:
            self.status = message
            self.connection_events.append({"host_time_s": time.perf_counter(),
                "generation": self.generation, "port": self.port, "message": message})
        print("Serial:", message)

    def _choose_port(self) -> str:
        # An explicit setting stays pinned. Auto mode follows a unique USB
        # serial number across COM renumbering, never guesses between devices.
        if self.requested_port:
            return self.requested_port
        ports = list(list_ports.comports())
        if self.device_identity is not None:
            matches = [p for p in ports if
                (p.vid, p.pid, p.serial_number) == self.device_identity]
            if len(matches) == 1:
                return matches[0].device
            raise RuntimeError("Waiting for the same Nano USB device")
        candidate = resolve_serial_port()
        p = next((p for p in ports if p.device == candidate), None)
        if p is not None and p.serial_number:
            self.device_identity = (p.vid, p.pid, p.serial_number)
        elif self.port is not None and candidate != self.port:
            raise RuntimeError("COM port changed without USB identity; set SERIAL_PORT explicitly")
        return candidate

    def _run(self) -> None:
        try:
            while not self.stop_event.is_set():
                try:
                    port = self._choose_port()
                    self.port = port
                    self._status("Opening " + port)
                    self.ser = serial.Serial(port, self.baud, timeout=0.02, write_timeout=0.5)
                    if self.stop_event.wait(SERIAL_BOOT_WAIT_S):
                        break
                    self.ser.reset_input_buffer()
                    with self.lock:
                        self.generation += 1
                        self.connected = True
                        self.segment_start = len(self.sample_indices)
                        self.anchor_start = len(self.anchors)
                        self.last_counter = None
                        self.last_anchor_time = None
                        self.buffer.clear()
                    self.ser.write(SERIAL_START_COMMAND)
                    self._status("Waiting for valid CHORDS packets on " + port)
                    opened_at = time.perf_counter()
                    first_received = False
                    while not self.stop_event.is_set():
                        with self.lock:
                            last = self.last_anchor_time
                        limit = MAX_READ_GAP_S if last is not None else SERIAL_FIRST_PACKET_TIMEOUT_S
                        if time.perf_counter() - (last if last is not None else opened_at) > limit:
                            raise ConnectionInterrupted("No valid EEG packets; reopening Nano")
                        n = self.ser.in_waiting
                        chunk = self.ser.read(min(n, 8192) if n else 1)
                        if not chunk:
                            continue
                        host_time = time.perf_counter()
                        # Do not unwrap the 8-bit counter after a long pause.
                        if last is not None and host_time - last > MAX_READ_GAP_S:
                            raise ConnectionInterrupted("EEG reception gap exceeded 0.90 s")
                        decoded = self._feed_bytes(chunk)
                        if decoded:
                            with self.lock:
                                gap = 0.0 if self.last_anchor_time is None else host_time - self.last_anchor_time
                                self.anchors.append({"host_time_s": host_time,
                                    "newest_sample_index": self.sample_indices[-1],
                                    "packets_in_batch": decoded, "read_gap_s": gap,
                                    "generation": self.generation})
                                self.last_anchor_time = host_time
                            if not first_received:
                                self._status("Receiving EEG on " + port + "; warming up")
                                first_received = True
                except (serial.SerialException, OSError, RuntimeError, ConnectionInterrupted) as exc:
                    self._status(str(exc) + " — retrying")
                finally:
                    with self.lock:
                        self.connected = False
                    if self.ser is not None:
                        try:
                            self.ser.close()
                        except Exception:
                            pass
                        self.ser = None
                self.stop_event.wait(SERIAL_RETRY_S)
        except Exception:
            with self.lock:
                self.connected = False
                self.thread_error = traceback.format_exc()

    def state(self) -> tuple[bool, int, str]:
        with self.lock:
            if self.thread_error:
                raise RuntimeError("Serial worker failed:\n" + self.thread_error)
            live = (self.connected and self.last_anchor_time is not None
                    and time.perf_counter() - self.last_anchor_time <= MAX_READ_GAP_S)
            count = len(self.sample_indices) - self.segment_start
            warm = (live and count >= int(NOMINAL_SAMPLE_RATE_HZ * SERIAL_WARMUP_S)
                    and len(self.anchors) - self.anchor_start >= 3)
            return warm, self.generation, self.status

    def check_generation(self, expected: int) -> None:
        with self.lock:
            if (not self.connected or self.generation != expected
                    or self.last_anchor_time is None
                    or time.perf_counter() - self.last_anchor_time > MAX_READ_GAP_S):
                raise ConnectionInterrupted("Serial connection interrupted this decision")

    def _feed_bytes(self, chunk: bytes) -> int:
        self.buffer.extend(chunk)
        decoded = 0

        while True:
            pos = self.buffer.find(self.HEADER)
            if pos < 0:
                # Keep one byte in case it is the first header byte.
                if len(self.buffer) > 1:
                    del self.buffer[:-1]
                break

            if pos > 0:
                del self.buffer[:pos]

            if len(self.buffer) < self.PACKET_LEN:
                break

            pkt = bytes(self.buffer[: self.PACKET_LEN])
            if pkt[-1] != self.END_BYTE:
                # Bad alignment: discard one byte and search again.
                del self.buffer[0]
                self.total_bad_packets += 1
                continue

            del self.buffer[: self.PACKET_LEN]
            counter = pkt[2]
            vals = tuple((pkt[3 + 2 * i] << 8) | pkt[4 + 2 * i] for i in range(8))

            if any(v > 1023 for v in vals):
                self.total_bad_packets += 1
                continue

            with self.lock:
                if self.last_counter is None:
                    # The next connection is a NEW timeline. A gap prevents
                    # any contiguous-window check from spanning a reset.
                    self.current_sample_index = self.sample_indices[-1] + 2 if self.sample_indices else 0
                else:
                    delta = (counter - self.last_counter) & 0xFF
                    if delta == 0:
                        # Duplicate packet: do not add the same sample twice.
                        self.last_counter = counter
                        continue
                    assert self.current_sample_index is not None
                    self.current_sample_index += delta
                    if delta > 1:
                        self.total_missing_samples += delta - 1

                assert self.current_sample_index is not None
                self.sample_indices.append(self.current_sample_index)
                self.counters.append(counter)
                self.channels.append(vals)
                self.segment_ids.append(self.generation)
                self.last_counter = counter

            decoded += 1

        return decoded

    def assert_healthy(self) -> None:
        ready, generation, _ = self.state()
        if not ready:
            raise ConnectionInterrupted("Waiting for fresh EEG after connection/reset")
        self.check_generation(generation)

    def sample_count(self) -> int:
        with self.lock:
            return len(self.sample_indices)

    def latest_sample_index(self) -> int | None:
        with self.lock:
            return self.sample_indices[-1] if self.sample_indices else None

    def snapshot_anchors(self) -> list[dict]:
        with self.lock:
            recent = self.anchors[self.anchor_start:]
            if recent:
                cutoff = recent[-1]["host_time_s"] - 20.0
                recent = [a for a in recent if a["host_time_s"] >= cutoff]
            return [dict(a) for a in recent]

    def get_exact_range(self, first_index: int, count: int) -> tuple[np.ndarray, np.ndarray]:
        """Return exact contiguous A7 samples or raise if packets are missing."""
        last_exclusive = first_index + count
        with self.lock:
            lo = bisect_left(self.sample_indices, first_index)
            hi = bisect_left(self.sample_indices, last_exclusive)
            idx = np.asarray(self.sample_indices[lo:hi], dtype=np.int64)
            a7 = np.asarray([row[A7_INDEX] for row in self.channels[lo:hi]], dtype=float)

        expected = np.arange(first_index, last_exclusive, dtype=np.int64)
        if len(idx) != count or not np.array_equal(idx, expected):
            raise ValueError("missing EEG packets in live analysis segment")
        return idx, a7

    def all_data(self):
        with self.lock:
            return (
                list(self.sample_indices),
                list(self.counters),
                list(self.channels),
                [dict(a) for a in self.anchors],
            )


# =============================================================================
# ALIGNMENT + SIGNAL PROCESSING
# =============================================================================

def fit_alignment(anchor_rows: list[dict]):
    """Fit sample counter to timely USB arrivals near the current epoch.

    Host reception timestamps include variable USB/OS delays. For a fixed
    sampling clock, the largest index - nominal_fs*time within a short time
    interval corresponds to the least delayed arrival. Keep one such anchor
    per interval, then robustly fit only that fixed eligible subset. Other
    buffered/stale arrivals never re-enter the local timing QA. This estimates
    a reception-time clock; fixed acquisition/USB latency remains unknown.
    """
    if len(anchor_rows) < MIN_TIMING_ANCHORS:
        raise ValueError("Need at least six serial timing anchors after reconnecting.")
    times = np.array([float(r["host_time_s"]) for r in anchor_rows])
    indices = np.array([float(r["newest_sample_index"]) for r in anchor_rows])
    if not np.isfinite(times).all() or not np.isfinite(indices).all():
        raise ValueError("Non-finite serial timing anchors.")
    if np.any(np.diff(times) <= 0) or np.any(np.diff(indices) <= 0):
        raise ValueError("Serial anchors must increase strictly in time and sample index.")

    origin = float(np.median(times))
    x = times - origin
    bins = np.floor((times - times[0]) / TIMING_ANCHOR_BIN_S).astype(np.int64)
    arrival_score = indices - NOMINAL_SAMPLE_RATE_HZ * x
    eligible = np.zeros(len(times), dtype=bool)
    edges = np.r_[0, np.flatnonzero(np.diff(bins)) + 1, len(times)]
    for lo, hi in zip(edges[:-1], edges[1:]):
        eligible[lo + int(np.argmax(arrival_score[lo:hi]))] = True
    if eligible.sum() < MIN_TIMING_ANCHORS:
        raise ValueError("Need six independent timing anchors; collecting recent EEG history.")

    mask = eligible.copy()
    for _ in range(8):
        slope, offset = np.polyfit(x[mask], indices[mask], 1)
        residual = indices - (slope * x + offset)
        center = np.median(residual[mask])
        sigma = 1.4826 * np.median(np.abs(residual[mask] - center))
        new = eligible & (np.abs(residual - center) <= max(3.5 * sigma, 2.0))
        if new.sum() < MIN_TIMING_ANCHORS or np.array_equal(new, mask):
            break
        mask = new

    if np.ptp(times[mask]) < MIN_TIMING_SPAN_S:
        raise ValueError("Timing anchors span less than 3 s; collecting recent EEG history.")
    slope, offset = np.polyfit(x[mask], indices[mask], 1)
    intercept = offset - slope * origin
    residual = indices - (slope * x + offset)
    p95 = float(np.percentile(np.abs(residual[mask]), 95))
    diag = {
        "anchors_total": len(times),
        "anchors_eligible": int(eligible.sum()),
        "anchors_used": int(mask.sum()),
        "estimated_sampling_rate_hz": float(slope),
        "p95_abs_residual_samples": p95,
        "raw_anchor_p95_samples": float(np.percentile(np.abs(residual), 95)),
        "median_abs_residual_samples": float(np.median(np.abs(residual[mask]))),
        "max_gap_between_retained_anchors_s": float(np.max(np.diff(times[mask]))),
        "alignment_method": "least_delayed_per_100ms_then_robust_recent_fit",
    }
    if not 240 <= slope <= 260:
        raise TimingAlignmentError(
            f"Estimated sampling rate {slope:.3f} Hz is inconsistent with the Nano 250 Hz setup.", diag)
    if p95 > MAX_ANCHOR_P95_SAMPLES:
        raise TimingAlignmentError(
            f"Epoch timing uncertain: timely-anchor p95={p95:.2f} samples "
            f"({1000*p95/slope:.1f} ms); repeating this decision.", diag)
    return float(slope), float(intercept), diag, times, residual, mask


def cca_score(signal: np.ndarray, frequency: float, fs: float) -> float:
    """Exact one-channel CCA against sin/cos references at f and 2f."""
    x = np.asarray(signal, dtype=float).copy()
    x -= x.mean()
    norm = np.linalg.norm(x)
    if norm < 1e-12 or not np.isfinite(x).all():
        return 0.0

    t = np.arange(len(x)) / fs
    refs = np.column_stack(
        [
            fun(2 * np.pi * h * frequency * t)
            for h in range(1, HARMONICS + 1)
            for fun in (np.sin, np.cos)
        ]
    )
    refs -= refs.mean(axis=0)
    u, singular, _ = np.linalg.svd(refs, full_matrices=False)
    rank = int(np.sum(singular > singular[0] * 1e-10))
    return float(np.clip(np.linalg.norm(u[:, :rank].T @ x) / norm, 0, 1))


def decode_epoch(
    acq: ChordsAcquisition,
    onset_host_time: float,
    frame_times: list[float],
    off_host_time: float,
    startup_refresh_hz: float,
    expected_generation: int,
) -> dict:
    """Decode one complete simultaneous NEXT/SELECT epoch."""
    acq.check_generation(expected_generation)
    # A single 3.5 s epoch may contain only 4-5 independent USB bursts.
    # Use recent same-generation history to estimate the sample clock, then
    # check the retained local anchors around this epoch separately.
    anchors = [a for a in acq.snapshot_anchors()
               if a["host_time_s"] >= onset_host_time - TIMING_HISTORY_S]
    if not anchors or any(a["generation"] != expected_generation for a in anchors):
        raise ConnectionInterrupted("Timing anchors belong to another connection")

    fs, intercept, timing, anchor_times, residuals, inliers = fit_alignment(anchors)
    retained_times = anchor_times[inliers]

    analysis_start_t = onset_host_time + SKIP_S
    analysis_end_t = analysis_start_t + WINDOW_S
    pad_start_t = analysis_start_t - FILTER_PAD_S
    pad_end_t = analysis_end_t + FILTER_PAD_S

    if pad_start_t < retained_times[0] or pad_end_t > retained_times[-1]:
        raise ValueError("live analysis segment lies outside retained serial-anchor coverage")

    # Reject long serial reception pauses overlapping this epoch.
    for a in anchors:
        gap = float(a["read_gap_s"])
        if gap > MAX_READ_GAP_S:
            end = float(a["host_time_s"])
            start = end - gap
            if onset_host_time < end and off_host_time > start:
                raise ValueError("long serial read pause overlapped the SSVEP epoch")

    # Local alignment QA around this exact epoch.
    near = inliers & (anchor_times >= onset_host_time - 0.05) & (anchor_times <= off_host_time + 0.05)
    if int(near.sum()) < 2:
        raise ValueError("fewer than two retained local timing anchors")
    local_p95 = float(np.percentile(np.abs(residuals[near]), 95))
    if local_p95 > MAX_ANCHOR_P95_SAMPLES:
        raise ValueError(f"local serial-anchor p95 too large: {local_p95:.2f} samples")

    # Require retained alignment anchors to cover the analysis interval without a big hole.
    left = np.searchsorted(retained_times, pad_start_t, side="right") - 1
    right = np.searchsorted(retained_times, pad_end_t, side="left")
    local_coverage = retained_times[max(0, left) : min(len(retained_times), right + 1)]
    if len(local_coverage) < 2 or np.max(np.diff(local_coverage)) > 1.0:
        raise ValueError("gap >1 s between retained timing anchors around the live EEG segment")

    # Display timing QA. Include the first non-flicker flip so the duration of the
    # final flicker frame is also checked.
    ft = np.asarray(frame_times + [off_host_time], dtype=float)
    if len(frame_times) != FLICKER_FRAMES or np.any(np.diff(ft) <= 0):
        raise ValueError("missing or non-monotonic flicker frame timestamps")

    gaps = np.diff(ft)
    dropped = int(np.sum(gaps > 1.5 / startup_refresh_hz))
    too_short = int(np.sum(gaps < 0.5 / startup_refresh_hz))
    if dropped or too_short:
        raise ValueError(
            f"unstable display timing: {dropped} long frame(s), {too_short} implausibly short frame(s)"
        )

    # Regression is more stable than simply taking 1/mean(interval).
    trial_refresh = 1.0 / float(np.polyfit(np.arange(len(ft)), ft - ft[0], 1)[0])
    frequencies = {
        label: trial_refresh / CYCLE_FRAMES[label]
        for label in LABELS
    }

    # Sample-index mapping uses the same host-time alignment model as calibration.
    first_analysis = int(round(fs * analysis_start_t + intercept))
    n_analysis = int(round(fs * WINDOW_S))
    n_pad = int(round(fs * FILTER_PAD_S))
    first_pad = first_analysis - n_pad
    total = n_analysis + 2 * n_pad

    _, raw_padded = acq.get_exact_range(first_pad, total)

    clipped_fraction = float(np.mean((raw_padded <= 0) | (raw_padded >= 1023)))
    if clipped_fraction >= MAX_CLIPPED_FRACTION:
        raise ValueError(f"ADC clipping >=1% ({100*clipped_fraction:.2f}%)")
    if np.std(raw_padded) < MIN_RAW_STD:
        raise ValueError("raw EEG is flat or nearly flat")

    sos = butter(
        FILTER_ORDER,
        [FILTER_LOW_HZ, FILTER_HIGH_HZ],
        fs=fs,
        btype="bandpass",
        output="sos",
    )
    filtered_padded = sosfiltfilt(sos, raw_padded)
    x = filtered_padded[n_pad : n_pad + n_analysis]

    if len(x) != n_analysis or not np.isfinite(x).all() or np.std(x) < MIN_FILTERED_STD:
        raise ValueError("filtered EEG is flat or unusable")

    scores = {label: cca_score(x, frequencies[label], fs) for label in LABELS}
    predicted = max(LABELS, key=lambda label: scores[label])
    margin = scores["NEXT"] - scores["SELECT"]

    if abs(margin) < 1e-10:
        raise ValueError("NEXT and SELECT CCA scores are indistinguishable")

    acq.check_generation(expected_generation)
    return {
        "predicted": predicted,
        "cca_NEXT": scores["NEXT"],
        "cca_SELECT": scores["SELECT"],
        "cca_NEXT_minus_SELECT": margin,
        "sampling_rate_hz": fs,
        "trial_refresh_hz": trial_refresh,
        "frequency_NEXT_hz": frequencies["NEXT"],
        "frequency_SELECT_hz": frequencies["SELECT"],
        "window_start_sample": first_analysis,
        "raw_clipped_fraction": clipped_fraction,
        "local_anchor_p95_samples": local_p95,
        "timely_anchor_p95_samples": timing["p95_abs_residual_samples"],
        "raw_anchor_p95_samples": timing["raw_anchor_p95_samples"],
        "timing_anchors_total": timing["anchors_total"],
        "timing_anchors_used": timing["anchors_used"],
        "alignment_method": timing["alignment_method"],
        "dropped_display_frames": dropped,
    }


# =============================================================================
# PSYCHOPY DISPLAY
# =============================================================================

def make_window() -> visual.Window:
    return visual.Window(
        # PsychoPy requires a two-element pixel size even for fullscreen.
        # The pyglet fullscreen backend uses the selected screen's actual size.
        size=(1280, 720),
        fullscr=FULLSCREEN,
        winType="pyglet",
        screen=SCREEN_INDEX,
        units="height",
        color=(-1, -1, -1),
        allowGUI=False,
        waitBlanking=True,
    )


def measure_refresh(win: visual.Window, warmup_frames: int = 60, measure_frames: int = 180) -> tuple[float, list[float]]:
    blank = visual.TextStim(win, text="", height=0.01)

    for _ in range(warmup_frames):
        blank.draw()
        win.flip()
        check_escape()

    times: list[float] = []

    def mark():
        times.append(time.perf_counter())

    for _ in range(measure_frames):
        blank.draw()
        win.callOnFlip(mark)
        win.flip()
        check_escape()

    if len(times) < 2:
        raise RuntimeError("Could not measure display refresh rate.")

    slope = float(np.polyfit(np.arange(len(times)), np.asarray(times) - times[0], 1)[0])
    refresh = 1.0 / slope
    return refresh, times


class BCIView:
    def __init__(self, win: visual.Window):
        self.win = win

        self.title = visual.TextStim(
            win,
            text="SSVEP PASSWORD BCI",
            pos=(0, 0.42),
            height=0.045,
            color="white",
            bold=True,
        )
        self.pin_text = visual.TextStim(
            win,
            text="PIN:",
            pos=(0, 0.31),
            height=0.05,
            color="white",
        )
        self.instruction = visual.TextStim(
            win,
            text="Look at NEXT to move. Look at SELECT to choose.",
            pos=(0, 0.23),
            height=0.028,
            color="white",
        )
        self.status = visual.TextStim(
            win,
            text="",
            pos=(0, 0.14),
            height=0.026,
            color="white",
        )

        self.digit_boxes = []
        self.digit_texts = []
        xs = np.linspace(-0.40, 0.40, 10)
        for d, x in enumerate(xs):
            box = visual.Rect(
                win,
                width=0.065,
                height=0.085,
                pos=(float(x), 0.02),
                fillColor=(-0.65, -0.65, -0.65),
                lineColor=(0.15, 0.15, 0.15),
                lineWidth=1.5,
            )
            txt = visual.TextStim(
                win,
                text=str(d),
                pos=(float(x), 0.02),
                height=0.05,
                color="white",
                bold=True,
            )
            self.digit_boxes.append(box)
            self.digit_texts.append(txt)

        self.next_box = visual.Rect(
            win,
            width=0.30,
            height=0.22,
            pos=(-0.6, -0.25),
            fillColor="black",
            lineColor="white",
            lineWidth=2,
        )
        self.select_box = visual.Rect(
            win,
            width=0.30,
            height=0.22,
            pos=(0.6, -0.25),
            fillColor="black",
            lineColor="white",
            lineWidth=2,
        )
        self.next_label = visual.TextStim(
            win,
            text="NEXT\n10 Hz",
            pos=(-0.25, -0.25),
            height=0.043,
            color="white",
            bold=True,
            alignText="center",
        )
        self.select_label = visual.TextStim(
            win,
            text="SELECT\n12 Hz",
            pos=(0.25, -0.25),
            height=0.043,
            color="white",
            bold=True,
            alignText="center",
        )

        self.footer = visual.TextStim(
            win,
            text="ESC = quit",
            pos=(0, -0.46),
            height=0.018,
            color=(0.55, 0.55, 0.55),
        )

    def draw_common(self, current_digit: int, selected: list[str], status: str = "") -> None:
        self.title.draw()
        self.pin_text.text = "PIN: " + " ".join(selected + ["_"] * (PASSWORD_LENGTH - len(selected)))
        self.pin_text.draw()
        self.instruction.draw()
        self.status.text = status
        self.status.draw()

        for d, (box, txt) in enumerate(zip(self.digit_boxes, self.digit_texts)):
            if d == current_digit:
                box.fillColor = (0.45, 0.45, 0.45)
                box.lineColor = "white"
                box.lineWidth = 3
            else:
                box.fillColor = (-0.65, -0.65, -0.65)
                box.lineColor = (0.15, 0.15, 0.15)
                box.lineWidth = 1.5
            box.draw()
            txt.draw()

        self.footer.draw()

    def draw_targets(self, next_on: bool, select_on: bool) -> None:
        self.next_box.fillColor = "white" if next_on else "black"
        self.select_box.fillColor = "white" if select_on else "black"
        self.next_label.color = "black" if next_on else "white"
        self.select_label.color = "black" if select_on else "white"
        self.next_box.draw()
        self.select_box.draw()
        self.next_label.draw()
        self.select_label.draw()

    def static_screen(self, current_digit: int, selected: list[str], status: str = "") -> None:
        self.draw_common(current_digit, selected, status)
        self.draw_targets(False, False)
        self.win.flip()

    def feedback_screen(self, current_digit: int, selected: list[str], message: str) -> None:
        self.static_screen(current_digit, selected, message)


# =============================================================================
# SESSION SAVING
# =============================================================================

def save_session(
    out_dir: Path,
    acq: ChordsAcquisition,
    decisions: list[dict],
    frame_log: list[dict],
    session_meta: dict,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    indices, counters, channels, anchors = acq.all_data()

    eeg_path = out_dir / "EEG.csv"
    with eeg_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sample_index", "packet_counter", "generation"] + [f"A{i}" for i in range(8)])
        for idx, counter, generation, vals in zip(indices, counters, acq.segment_ids, channels):
            w.writerow([idx, counter, generation, *vals])

    anchor_path = out_dir / "anchors.csv"
    with anchor_path.open("w", newline="", encoding="utf-8") as f:
        fields = ["host_time_s", "newest_sample_index", "packets_in_batch", "read_gap_s", "generation"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(anchors)

    with (out_dir / "connection_events.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["host_time_s", "generation", "port", "message"])
        w.writeheader()
        w.writerows(acq.connection_events)

    decision_path = out_dir / "decisions.csv"
    if decisions:
        fields = []
        for row in decisions:
            for key in row:
                if key not in fields:
                    fields.append(key)
        with decision_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(decisions)
    else:
        decision_path.write_text("", encoding="utf-8")

    frame_path = out_dir / "frames.csv"
    if frame_log:
        fields = ["decision", "stimulus_frame", "host_time_s"]
        with frame_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(frame_log)
    else:
        frame_path.write_text("", encoding="utf-8")

    (out_dir / "session.json").write_text(
        json.dumps(session_meta, indent=2, allow_nan=False),
        encoding="utf-8",
    )


# =============================================================================
# MAIN BCI
# =============================================================================

def wait_for_eeg(acq: ChordsAcquisition, view: BCIView,
                 current_digit: int, selected: list[str]) -> int:
    """Wait for packets, not for a pre-stimulus fit that can block forever.

    The full epoch provides the timing evidence. Check its alignment once after
    it finishes; a rejected epoch then retries without another fit-gated wait.
    """
    while True:
        check_escape()
        ready, generation, status = acq.state()
        if ready:
            try:
                acq.check_generation(generation)
                return generation
            except ConnectionInterrupted:
                pass
        view.static_screen(current_digit, selected, status + " | ESC = quit")
        core.wait(0.01)


def wait_for_trailing_eeg(acq: ChordsAcquisition, view: BCIView,
                          current_digit: int, selected: list[str],
                          off_time: float, generation: int) -> None:
    """Wait for a post-offset batch, then allow its short drain to finish.

    Wait from the FIRST observed post-offset receipt, not until the stream
    becomes quiet: a continuously delivered 250 Hz stream may never be quiet.
    """
    deadline = time.perf_counter() + SERIAL_POST_EPOCH_MAX_WAIT_S
    first_post_seen = None
    while time.perf_counter() < deadline:
        check_escape()
        acq.check_generation(generation)
        with acq.lock:
            latest = acq.last_anchor_time
        if latest is not None and latest >= off_time + SERIAL_POST_EPOCH_GUARD_S:
            if first_post_seen is None:
                first_post_seen = time.perf_counter()
            if time.perf_counter() - first_post_seen >= SERIAL_BURST_DRAIN_S:
                return
        view.static_screen(current_digit, selected, "Receiving the final EEG batch...")
        core.wait(0.01)
    raise ConnectionInterrupted("Final EEG batch did not arrive before the decision timeout")


def run_bci() -> None:
    print("Program revision:", PROGRAM_REVISION, flush=True)
    script_dir = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
    stamp = now_stamp()
    out_dir = script_dir / f"SSVEP_password_session_{stamp}"

    config_path = choose_config_file()
    if config_path is None:
        print("Cancelled: no classifier config selected.")
        return
    config = validate_config(config_path)

    port = SERIAL_PORT
    print(f"Serial port: {port or 'automatic discovery with retries'}")
    print(f"Using classifier config: {config_path}")
    print(f"Offline pilot passed: {bool(config.get('calibration_ok'))}")

    acq = ChordsAcquisition(port, BAUD_RATE)

    select_beep = None

    win = None
    decisions: list[dict] = []
    frame_log: list[dict] = []
    selected: list[str] = []
    current_digit = 0
    completed = False
    abort_reason = ""
    startup_refresh = None

    session_meta = {
        "program_revision": PROGRAM_REVISION,
        "schema_version": 2,
        "alignment_method": "least_delayed_per_100ms_then_robust_recent_fit",
        "timing_anchor_bin_s": TIMING_ANCHOR_BIN_S,
        "timing_history_s": TIMING_HISTORY_S,
        "min_timing_anchors": MIN_TIMING_ANCHORS,
        "min_timing_span_s": MIN_TIMING_SPAN_S,
        "post_epoch_max_wait_s": SERIAL_POST_EPOCH_MAX_WAIT_S,
        "max_timely_anchor_p95_samples": MAX_ANCHOR_P95_SAMPLES,
        "startup_wait_policy": "fresh_packets_only_alignment_checked_after_full_epoch",
        "paradigm": "two_target_numeric_password_bci",
        "created": datetime.now().isoformat(timespec="seconds"),
        "classifier_config": str(config_path),
        "classifier_calibration_ok": bool(config.get("calibration_ok")),
        "password_length": PASSWORD_LENGTH,
        "labels": list(LABELS),
        "command_actions": {"NEXT": "advance highlighted digit", "SELECT": "append highlighted digit"},
        "cycle_frames": CYCLE_FRAMES,
        "on_frames": ON_FRAMES,
        "flicker_frames": FLICKER_FRAMES,
        "skip_s": SKIP_S,
        "window_s": WINDOW_S,
        "filter_pad_s": FILTER_PAD_S,
        "filter": {
            "low_hz": FILTER_LOW_HZ,
            "high_hz": FILTER_HIGH_HZ,
            "order": FILTER_ORDER,
            "mode": "block_zero_phase_on_complete_3.5_s_epoch",
        },
        "harmonics": HARMONICS,
        "eeg_channel": EEG_CHANNEL,
        "serial_port": port,
        "baud_rate": BAUD_RATE,
        "select_beep": {
            "enabled": True,
            "frequency_hz": SELECT_BEEP_HZ,
            "duration_s": SELECT_BEEP_S,
            "volume": SELECT_BEEP_VOLUME,
        },
    }

    try:
        print("Creating fullscreen PsychoPy window...", flush=True)
        win = make_window()
        view = BCIView(win)
        view.static_screen(0, [], "Preparing selection beep...")
        # Initialize once, within error handling and before flicker starts.
        select_beep = sound.Sound(
            value=SELECT_BEEP_HZ,
            secs=SELECT_BEEP_S,
            volume=SELECT_BEEP_VOLUME,
        )
        print("Window and beep ready. Connecting Nano...", flush=True)
        acq.start()
        wait_for_eeg(acq, view, current_digit, selected)

        view.static_screen(0, [], "Measuring fullscreen refresh timing...")
        startup_refresh, refresh_times = measure_refresh(win)
        session_meta["startup_refresh_hz"] = startup_refresh
        session_meta["startup_refresh_measurement_frames"] = len(refresh_times)

        if not (MIN_REFRESH_HZ <= startup_refresh <= MAX_REFRESH_HZ):
            raise RuntimeError(
                f"Measured fullscreen refresh is {startup_refresh:.3f} Hz. "
                "This program is configured for the 60 Hz calibration (NEXT 6 frames/cycle, SELECT 5)."
            )

        nominal_freq_next = startup_refresh / CYCLE_FRAMES["NEXT"]
        nominal_freq_select = startup_refresh / CYCLE_FRAMES["SELECT"]
        print(f"Measured fullscreen refresh: {startup_refresh:.4f} Hz")
        print(f"Expected live NEXT frequency:   {nominal_freq_next:.4f} Hz")
        print(f"Expected live SELECT frequency: {nominal_freq_select:.4f} Hz")

        # Start screen.
        while True:
            wait_for_eeg(acq, view, current_digit, selected)
            view.draw_common(
                current_digit,
                selected,
                f"Ready | NEXT ~{nominal_freq_next:.2f} Hz | SELECT ~{nominal_freq_select:.2f} Hz | SPACE to start",
            )
            view.draw_targets(False, False)
            win.flip()
            keys = event.getKeys(keyList=["space", "escape"])
            if "escape" in keys:
                raise UserAbort()
            if "space" in keys:
                break
            core.wait(0.02)

        # Main command loop.
        decision_number = 0
        while len(selected) < PASSWORD_LENGTH:
            check_escape()
            epoch_generation = wait_for_eeg(acq, view, current_digit, selected)
            decision_number += 1

            before_digit = current_digit
            before_password = "".join(selected)
            frame_times: list[float] = []
            onset_holder = {"time": None}

            interrupted = ""
            # Simultaneous two-target flicker using an exact shared frame counter.
            for f in range(FLICKER_FRAMES):
                try:
                    acq.check_generation(epoch_generation)
                except ConnectionInterrupted as exc:
                    interrupted = str(exc)
                    break
                next_on = (f % CYCLE_FRAMES["NEXT"]) < ON_FRAMES["NEXT"]
                select_on = (f % CYCLE_FRAMES["SELECT"]) < ON_FRAMES["SELECT"]

                view.draw_common(current_digit, selected, "Focus on NEXT or SELECT")
                view.draw_targets(next_on, select_on)

                def mark_frame(frame_id=f):
                    t = time.perf_counter()
                    frame_times.append(t)
                    frame_log.append(
                        {
                            "decision": decision_number,
                            "stimulus_frame": frame_id,
                            "host_time_s": t,
                        }
                    )
                    if frame_id == 0:
                        onset_holder["time"] = t

                win.callOnFlip(mark_frame)
                win.flip()
                check_escape()

            # First static flip defines the end of the final flicker frame.
            off_holder = {"time": None}

            def mark_off():
                off_holder["time"] = time.perf_counter()

            view.draw_common(current_digit, selected, "Decoding...")
            view.draw_targets(False, False)
            win.callOnFlip(mark_off)
            win.flip()

            onset = onset_holder["time"]
            off_time = off_holder["time"]
            if off_time is None or (onset is None and not interrupted):
                raise RuntimeError("Could not timestamp the SSVEP epoch flips.")

            # Wait for a real trailing batch, which can arrive ~0.8 s apart
            # on this Nano/driver. Preserve the generation and keep ESC/UI live.
            if not interrupted:
                try:
                    wait_for_trailing_eeg(acq, view, current_digit, selected,
                                          off_time, epoch_generation)
                except ConnectionInterrupted as exc:
                    interrupted = str(exc)

            row = {
                "decision": decision_number,
                "generation": epoch_generation,
                "host_flicker_on_s": onset,
                "host_flicker_off_s": off_time,
                "digit_before": before_digit,
                "password_before": before_password,
                "valid": False,
                "reason": "",
                "predicted_command": "",
                "digit_after": current_digit,
                "password_after": "".join(selected),
            }

            try:
                if interrupted:
                    raise ConnectionInterrupted(interrupted)
                result = decode_epoch(acq, onset, frame_times, off_time, startup_refresh, epoch_generation)
                command = result["predicted"]

                with acq.lock:
                    if (not acq.connected or acq.generation != epoch_generation
                            or acq.last_anchor_time is None
                            or time.perf_counter() - acq.last_anchor_time > MAX_READ_GAP_S):
                        raise ConnectionInterrupted("Connection changed before command commit")
                    if command == "NEXT":
                        current_digit = (current_digit + 1) % 10
                    elif command == "SELECT":
                        selected.append(str(current_digit))
                    else:
                        raise RuntimeError("Unexpected decoder label: " + command)
                if command == "SELECT":
                    select_beep.play()

                row.update(result)
                row.update(
                    {
                        "valid": True,
                        "predicted_command": command,
                        "digit_after": current_digit,
                        "password_after": "".join(selected),
                    }
                )
                decisions.append(row)

                score_text = (
                    f"{command} | CCA NEXT {result['cca_NEXT']:.3f} | "
                    f"SELECT {result['cca_SELECT']:.3f}"
                )
                print(
                    f"Decision {decision_number}: {score_text} | "
                    f"digit {before_digit} -> {current_digit} | PIN {''.join(selected)}"
                )
                view.feedback_screen(current_digit, selected, score_text)

            except ValueError as exc:
                if isinstance(exc, TimingAlignmentError):
                    row.update({"timing_" + k: v for k, v in exc.diagnostics.items()})
                row["reason"] = str(exc)
                row["digit_after"] = current_digit
                row["password_after"] = "".join(selected)
                decisions.append(row)
                print(f"Decision {decision_number} rejected: {exc}")
                view.feedback_screen(current_digit, selected, "RETRY — " + str(exc))

            # Static rest to reduce carry-over and give the user time to redirect gaze.
            rest_end = time.perf_counter() + REST_S
            while time.perf_counter() < rest_end and len(selected) < PASSWORD_LENGTH:
                check_escape()
                view.draw_common(current_digit, selected, "Prepare for the next command")
                view.draw_targets(False, False)
                win.flip()

        completed = True
        final_password = "".join(selected)
        session_meta["completed"] = True
        session_meta["final_password"] = final_password
        print("\nPASSWORD ENTERED:", final_password)

        # Final screen stays until SPACE or ESC.
        while True:
            view.draw_common(current_digit, selected, f"PASSWORD COMPLETE: {final_password} | SPACE to finish")
            view.draw_targets(False, False)
            win.flip()
            keys = event.getKeys(keyList=["space", "escape"])
            if "space" in keys or "escape" in keys:
                break
            core.wait(0.02)

    except UserAbort:
        abort_reason = "user pressed ESC"
        print("Session aborted by user.")
        session_meta["completed"] = False
        session_meta["abort_reason"] = abort_reason

    except Exception as exc:
        abort_reason = f"{type(exc).__name__}: {exc}"
        print("\nERROR:", abort_reason)
        traceback.print_exc()
        session_meta["completed"] = False
        session_meta["abort_reason"] = abort_reason
        session_meta["error_traceback"] = traceback.format_exc()

        if win is not None:
            try:
                error_text = visual.TextStim(
                    win,
                    text="BCI ERROR\n\n" + str(exc) + "\n\nPress ESC or wait to close.",
                    color="white",
                    height=0.035,
                    wrapWidth=1.3,
                )
                error_text.draw()
                win.flip()
                core.wait(3.0)
            except Exception:
                pass

    finally:
        acq.stop()
        session_meta.setdefault("completed", completed)
        session_meta["finished"] = datetime.now().isoformat(timespec="seconds")
        session_meta["decisions_total"] = len(decisions)
        session_meta["decisions_valid"] = int(sum(bool(r.get("valid")) for r in decisions))
        session_meta["last_serial_port"] = acq.port
        session_meta["connection_generations"] = acq.generation
        session_meta["serial_samples_recorded"] = acq.sample_count()
        session_meta["serial_missing_samples_detected"] = acq.total_missing_samples
        session_meta["serial_bad_packets_detected"] = acq.total_bad_packets
        if startup_refresh is not None:
            session_meta["startup_refresh_hz"] = startup_refresh
        if abort_reason:
            session_meta["abort_reason"] = abort_reason

        try:
            save_session(out_dir, acq, decisions, frame_log, session_meta)
            if session_meta.get("error_traceback"):
                (out_dir / "ERROR.txt").write_text(
                    session_meta["error_traceback"], encoding="utf-8")
            print("Saved session to:", out_dir.resolve())
        except Exception:
            print("WARNING: saving session failed")
            traceback.print_exc()

        if win is not None:
            try:
                win.close()
            except Exception:
                pass
        core.quit()


if __name__ == "__main__":
    run_bci()

"""TWO-TARGET SSVEP ANALYSIS — NEXT versus SELECT, fixed 3 s CCA.

Run in PsychoPy Coder or Python with numpy/scipy/matplotlib. Choose the NEW
SSVEP_two_target_EEG_<stamp>.csv. Matching session, markers, anchors, transitions,
and frame-interval files load automatically from the SAME folder. Old three-
target/sequential runs are rejected. Frequencies come from session frame counts
and each trial's flip timing, so NEXT and SELECT stay mapped consistently.

Input: recorded A7 EEG. For each trial: discard 0.25 s after onset, analyze ONE
3.00 s window, compare CCA at NEXT (10 Hz) and SELECT (12 Hz), including their
second harmonics, and predict the larger score. Continuous segments are filtered
4–30 Hz with a fourth-order zero-phase Butterworth filter. This is an OFFLINE
pilot baseline; standard CCA has no fitted classifier weights. No attention
thresholds, LDA, sliding-window voting, or window optimization are used.

The corrected alignment check uses only the SAME robust anchor inliers globally
and locally. Stale intermediate USB reads are not reintroduced into trial QA.
Missing samples, clipping, flat EEG, display disruption and missing transitions
are reported rather than silently repaired. Accuracy is reported on valid trials
and on all planned trials, with per-target recall and a 2x2 confusion matrix.
Chance for balanced two-target selection is 50%, not the three-target 33.3%.

Saves a new analysis_<timestamp> subfolder with trial_results.csv,
calibration_summary.png, analysis_summary.json, timing_anchor_diagnostics.csv,
and SSVEP_two_target_classifier_config.json. The target pass criterion is 90%
correct/all planned trials, at least 30 trials and 80% per-target planned-trial
recall. Passing this pilot still requires a separate real-time validation.
This program does not operate the calculator. Its JSON is for a future TWO-
target decoder; previous three-target/sequential live programs cannot use it.

Optional terminal usage:
python SSVEP_two_target_analysis.py --eeg "path/to/EEG.csv" --no-show
"""

from pathlib import Path
from datetime import datetime
import argparse
import csv
import json
import numpy as np
from scipy.signal import butter, sosfiltfilt

EEG_CHANNEL = "A7"
LABELS = ("NEXT", "SELECT")
SKIP_S = 0.25
WINDOW_S = 3.0
FILTER_LOW_HZ = 4.0
FILTER_HIGH_HZ = 30.0
FILTER_ORDER = 4
HARMONICS = 2
REQUIRED_ACCURACY = 0.90
MAX_ANCHOR_P95_SAMPLES = 5.0
MAX_READ_GAP_S = 0.90     # >225 samples; 8-bit counter cannot safely unwrap a long outage.


def rows(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def fit_alignment(anchor_rows):
    if len(anchor_rows) < 20:
        raise ValueError("Need at least 20 serial timing anchors.")
    times = np.array([float(r["host_time_s"]) for r in anchor_rows])
    indices = np.array([float(r["newest_sample_index"]) for r in anchor_rows])
    if not np.isfinite(times).all() or not np.isfinite(indices).all():
        raise ValueError("Non-finite serial timing anchors.")
    if np.any(np.diff(times) <= 0) or np.any(np.diff(indices) <= 0):
        raise ValueError("Serial anchors must increase strictly in time and sample index.")
    # Center time to avoid conditioning problems; reject irregular USB batch latency.
    origin = float(np.median(times))
    x = times-origin
    mask = np.ones(len(times), dtype=bool)
    for _ in range(8):
        slope, offset = np.polyfit(x[mask], indices[mask], 1)
        residual = indices-(slope*x+offset)
        center = np.median(residual[mask])
        sigma = 1.4826*np.median(np.abs(residual[mask]-center))
        new = np.abs(residual-center) <= max(3.5*sigma, 2.0)
        if new.sum() < 20 or np.array_equal(new, mask):
            break
        mask = new
    slope, offset = np.polyfit(x[mask], indices[mask], 1)
    intercept = offset-slope*origin
    residual = indices-(slope*times+intercept)
    if not 240 <= slope <= 260:
        raise ValueError(f"Estimated sampling rate {slope:.3f} Hz is inconsistent with the Nano 250 Hz setup.")
    diag = {"anchors_total": len(times), "anchors_used": int(mask.sum()),
            "estimated_sampling_rate_hz": float(slope),
            "median_abs_residual_samples": float(np.median(np.abs(residual[mask]))),
            "p95_abs_residual_samples": float(np.percentile(np.abs(residual[mask]), 95)),
            "note": "Residuals describe fitted USB reception anchors; unknown fixed latency is not measured."}
    diag["anchors_rejected"] = int((~mask).sum())
    diag["max_gap_between_retained_anchors_s"] = float(np.max(np.diff(times[mask])))
    return float(slope), float(intercept), diag, times, residual, mask


def cca_score(signal, frequency, fs):
    """For ONE EEG channel, CCA equals correlation with its reference projection.

    Orthogonalize sine/cosine references using SVD, then compute the length of the
    EEG projection divided by EEG norm. This is exact one-channel CCA, not a PSD
    or amplitude score, and has the same meaning as the previous synthetic CCA.
    """
    x = np.asarray(signal, dtype=float).copy()
    x -= x.mean()
    norm = np.linalg.norm(x)
    if norm < 1e-12 or not np.isfinite(x).all():
        return 0.0
    t = np.arange(len(x))/fs
    refs = np.column_stack([fun(2*np.pi*h*frequency*t)
                           for h in range(1, HARMONICS+1) for fun in (np.sin, np.cos)])
    refs -= refs.mean(axis=0)
    u, singular, _ = np.linalg.svd(refs, full_matrices=False)
    rank = int(np.sum(singular > singular[0]*1e-10))
    return float(np.clip(np.linalg.norm(u[:, :rank].T@x)/norm, 0, 1))


def filter_contiguous(indices, raw, fs):
    """Never filter across packet loss or across a different sample timeline."""
    result = np.full(len(raw), np.nan)
    edges = np.r_[0, np.flatnonzero(np.diff(indices) != 1)+1, len(raw)]
    sos = butter(FILTER_ORDER, [FILTER_LOW_HZ, FILTER_HIGH_HZ], fs=fs,
                 btype="bandpass", output="sos")
    for lo, hi in zip(edges[:-1], edges[1:]):
        if hi-lo < max(40, int(.5*fs)):
            continue
        result[lo:hi] = sosfiltfilt(sos, raw[lo:hi])
    return result, edges


def choose_eeg():
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        name = filedialog.askopenfilename(title="Choose NEW SSVEP_two_target_EEG CSV",
                    filetypes=[("EEG CSV", "SSVEP_two_target_EEG_*.csv"), ("CSV files", "*.csv")])
    finally:
        root.destroy()
    return Path(name) if name else None


def matching_paths(eeg_path):
    head = "SSVEP_two_target_EEG_"
    if not eeg_path.name.startswith(head) or eeg_path.suffix.lower() != ".csv":
        raise ValueError("Select the NEW two-target EEG CSV, not a three-target or sequential run.")
    stamp = eeg_path.name[len(head):-4]
    paths = {kind: eeg_path.parent/f"SSVEP_two_target_{kind}_{stamp}.{ext}"
             for kind, ext in (("anchors", "csv"), ("markers", "csv"),
                ("transitions", "csv"), ("frame_intervals", "csv"), ("session", "json"))}
    missing = [p.name for p in paths.values() if not p.exists()]
    if missing:
        raise FileNotFoundError("Keep all session files together. Missing: "+", ".join(missing))
    return paths


def analyze(eeg_path, output=None, show=True, channel=EEG_CHANNEL):
    eeg_path = Path(eeg_path).resolve()
    paths = matching_paths(eeg_path)
    session = json.loads(paths["session"].read_text(encoding="utf-8"))
    if session.get("paradigm") != "two_target_simultaneous_cca_baseline":
        raise ValueError("Wrong paradigm in session JSON.")
    if tuple(session.get("labels", [])) != LABELS:
        raise ValueError("Unexpected target label order.")
    trial_order = session.get("trial_order", [])
    if not trial_order or any(label not in LABELS for label in trial_order):
        raise ValueError("Missing or invalid NEXT/SELECT trial order in session JSON.")
    if session.get("cycle_frames") != {"NEXT": 6, "SELECT": 5} or session.get("on_frames") != {"NEXT": 3, "SELECT": 2}:
        raise ValueError("Expected NEXT=6-frame/10 Hz and SELECT=5-frame/12 Hz patterns. Use the matching recorder.")
    data = rows(eeg_path)
    if not data or channel not in data[0]:
        raise ValueError(f"No EEG data or missing channel {channel}.")
    indices = np.array([int(r["sample_index"]) for r in data], dtype=np.int64)
    raw = np.array([float(r[channel]) for r in data])
    if np.any(np.diff(indices) <= 0) or not np.isfinite(raw).all():
        raise ValueError("EEG sample indices must increase strictly; EEG values must be finite.")
    anchors = rows(paths["anchors"])
    fs, intercept, timing, anchor_times, residuals, anchor_inliers = fit_alignment(anchors)
    retained_times = anchor_times[anchor_inliers]
    filtered, edges = filter_contiguous(indices, raw, fs)
    marker_rows = rows(paths["markers"])
    frame_rows = rows(paths["frame_intervals"])
    transition_rows = rows(paths["transitions"])
    refresh = float(session["measured_refresh_hz"])
    expected_frames = int(session["flicker_frames"])
    large_gaps = []
    for r in anchors:
        gap = float(r["read_gap_s"])
        if gap > MAX_READ_GAP_S:
            end = float(r["host_time_s"])
            large_gaps.append((end-gap, end))
    timing_ok = timing["p95_abs_residual_samples"] <= MAX_ANCHOR_P95_SAMPLES
    results = []
    for trial, true_target in enumerate(session["trial_order"], 1):
        record = {"trial": trial, "true_target": true_target, "valid": False,
                  "reason": "", "predicted_target": "", "correct": "",
                  "window_s": WINDOW_S, "sampling_rate_hz": fs,
                  "window_start_sample": "", "dropped_display_frames": "",
                  "raw_clipped_fraction": "", "local_anchor_p95_samples": "", "cca_NEXT_minus_SELECT": ""}
        for label in LABELS:
            record[f"cca_{label}"] = ""
            record[f"frequency_{label}_hz"] = ""
        try:
            marks = [r for r in marker_rows if int(r["trial"]) == trial]
            starts = [r for r in marks if r["event"] == "FLICKER_ON"]
            stops = [r for r in marks if r["event"] == "FLICKER_OFF"]
            if len(starts) != 1 or len(stops) != 1:
                raise ValueError("incomplete flicker epoch")
            if starts[0]["attended_target"] != true_target or stops[0]["attended_target"] != true_target:
                raise ValueError("marker/target mismatch")
            start, stop = float(starts[0]["host_time_s"]), float(stops[0]["host_time_s"])
            window_start = start+SKIP_S
            window_end = window_start+WINDOW_S
            if stop-window_end < .10:
                raise ValueError("flicker too short for fixed 3 s analysis and ending guard")
            if not timing_ok:
                raise ValueError("global serial-anchor fit residuals too large")
            if window_start < retained_times[0] or window_end > retained_times[-1]:
                raise ValueError("analysis window outside serial anchor coverage")
            if any(start < b and stop > a for a, b in large_gaps):
                raise ValueError("long serial read pause; packet counter loss ambiguous")
            near = anchor_inliers & (anchor_times >= start-.05) & (anchor_times <= stop+.05)
            if int(near.sum()) < 2:
                raise ValueError("fewer than two retained local timing anchors")
            # Demand retained anchors that bracket the actual analysis window,
            # and reject a hole >1 s; a small global residual cannot hide an outage.
            first_anchor = np.searchsorted(retained_times, window_start, side="right")-1
            last_anchor = np.searchsorted(retained_times, window_end, side="left")
            local_coverage = retained_times[first_anchor:last_anchor+1]
            if len(local_coverage) < 2 or np.max(np.diff(local_coverage)) > 1.0:
                raise ValueError("gap >1 s between retained alignment anchors around EEG window")
            local_p95 = float(np.percentile(np.abs(residuals[near]), 95))
            record["local_anchor_p95_samples"] = local_p95
            if local_p95 > MAX_ANCHOR_P95_SAMPLES:
                raise ValueError("local serial-anchor residuals too large")
            fr = [r for r in frame_rows if int(r["trial"]) == trial and r["phase"] == "flicker"]
            ft = np.array([float(r["host_time_s"]) for r in fr]+[stop])
            frame_ids = [int(r["stimulus_frame"]) for r in fr]
            if frame_ids != list(range(expected_frames)) or np.any(np.diff(ft) <= 0):
                raise ValueError("missing or unordered flicker frame log")
            if abs(ft[0]-start) > .001:
                raise ValueError("frame/marker onset mismatch")
            gaps = np.diff(ft)
            # Include first REST flip: it determines how long the final flicker frame stayed up.
            dropped = int(np.sum(gaps > 1.5/refresh))
            record["dropped_display_frames"] = dropped
            if dropped or np.any(gaps < .5/refresh):
                raise ValueError("unstable stimulus timing (dropped or implausibly short frame)")
            trial_refresh = 1/float(np.polyfit(np.arange(len(ft)), ft-ft[0], 1)[0])
            frequencies = {label: trial_refresh/int(session["cycle_frames"][label]) for label in LABELS}
            # Check that both stimuli really had the intended frame-counted transitions.
            for label in LABELS:
                logged = [(int(r["stimulus_frame"]), int(r["state"])) for r in transition_rows
                          if int(r["trial"]) == trial and r["flicker_stimulus"] == label]
                cycle, on = int(session["cycle_frames"][label]), int(session["on_frames"][label])
                expected = [(f, int(f % cycle < on)) for f in range(expected_frames)
                            if f == 0 or int(f % cycle < on) != int((f-1) % cycle < on)]
                if logged != expected:
                    raise ValueError("missing/incorrect stimulus transitions for "+label)
            first = int(round(fs*window_start+intercept))
            n = int(round(fs*WINDOW_S))
            lo = int(np.searchsorted(indices, first))
            hi = lo+n
            record["window_start_sample"] = first
            if hi > len(raw) or lo >= len(raw) or indices[lo] != first:
                raise ValueError("EEG window not fully recorded")
            if not np.array_equal(indices[lo:hi], np.arange(first, first+n)):
                raise ValueError("missing EEG packets in analysis window")
            segment = int(np.searchsorted(edges, lo, side="right")-1)
            if hi > edges[segment+1] or min(lo-edges[segment], edges[segment+1]-hi) < .25*fs:
                raise ValueError("EEG gap/boundary too close for reliable offline filtering")
            x = filtered[lo:hi]
            clip = float(np.mean((raw[lo:hi] <= 0) | (raw[lo:hi] >= 1023)))
            record["raw_clipped_fraction"] = clip
            if clip >= .01:
                raise ValueError("ADC clipping >=1%")
            if np.std(raw[lo:hi]) < .1 or np.std(x) < .01 or not np.isfinite(x).all():
                raise ValueError("flat or unusable EEG")
            scores = np.array([cca_score(x, frequencies[label], fs) for label in LABELS])
            predicted = LABELS[int(np.argmax(scores))]
            if float(np.max(scores)-np.min(scores)) < 1e-10:
                raise ValueError("no distinguishable CCA scores")
            record.update({"valid": True, "predicted_target": predicted,
                           "correct": int(predicted == true_target),
                           "cca_NEXT_minus_SELECT": float(scores[0]-scores[1])})
            for label, score in zip(LABELS, scores):
                record[f"cca_{label}"] = float(score)
                record[f"frequency_{label}_hz"] = frequencies[label]
        except ValueError as exc:
            record["reason"] = str(exc)
        results.append(record)

    valid = [r for r in results if r["valid"]]
    matrix = np.zeros((len(LABELS), len(LABELS)), dtype=int)
    for r in valid:
        matrix[LABELS.index(r["true_target"]), LABELS.index(r["predicted_target"])] += 1
    correct = int(np.trace(matrix))
    per_target = {label: {"correct": int(matrix[i, i]), "valid": int(matrix[i].sum()),
                         "planned": int(session["trial_order"].count(label))}
                  for i, label in enumerate(LABELS)}
    accuracy = correct/len(valid) if valid else None
    completion_rate = correct/len(results) if results else 0.0
    calibration_ok = bool(session.get("completed") and not session.get("error") and timing_ok
        and len(results) >= 30 and completion_rate >= REQUIRED_ACCURACY
        and all(v["correct"]/max(1, v["planned"]) >= .8 for v in per_target.values()))
    config = {"schema_version": 1, "analysis_version": 2, "algorithm": "standard_cca_argmax_two_target",
              "paradigm": session["paradigm"], "calibration_ok": calibration_ok,
              "eeg_channel": channel, "sampling_rate_hz": fs, "harmonics": HARMONICS,
              "filter": {"low_hz": FILTER_LOW_HZ, "high_hz": FILTER_HIGH_HZ,
                         "order": FILTER_ORDER, "offline_zero_phase": True},
              "window_s": WINDOW_S, "skip_after_flicker_on_s": SKIP_S,
              "labels": list(LABELS), "chance_accuracy": 0.5,
              "command_actions": {"NEXT": "cycle to next option", "SELECT": "choose highlighted option"},
              "cycle_frames": session["cycle_frames"],
              "on_frames": session["on_frames"],
              "frequencies_hz": {label: float(np.median([r[f"frequency_{label}_hz"] for r in valid]))
                  if valid else float(session["actual_frequencies_hz"][label]) for label in LABELS},
              "baseline_accuracy_valid_trials": accuracy,
              "correct_fraction_all_planned_trials": completion_rate,
              "per_target": per_target, "timing_alignment": timing,
              "source_eeg_file": str(eeg_path),
              "note": "Pilot prompted-trial baseline. Not an independent online validation. Previous three-target/sequential decoders incompatible; online filtering must be designed/validated separately."}
    summary = {"config": config, "planned_trials": len(results), "valid_trials": len(valid),
               "invalid_trials": len(results)-len(valid), "correct_trials": correct,
               "session_completed": bool(session.get("completed")),
               "balanced_accuracy_valid_trials": float(np.mean([matrix[i, i]/matrix[i].sum()
                    for i in range(len(LABELS))])) if all(matrix.sum(axis=1) > 0) else None,
               "confusion_matrix_rows_true_columns_predicted": matrix.tolist(),
               "invalid_trial_details": [{"trial": r["trial"], "reason": r["reason"]}
                                         for r in results if not r["valid"]]}
    out = Path(output) if output else eeg_path.parent/("analysis_"+datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    out.mkdir(parents=True, exist_ok=True)
    with (out/"trial_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    with (out/"timing_anchor_diagnostics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["host_time_s", "newest_sample_index", "packets_in_batch",
                         "residual_samples", "retained_in_alignment_fit"])
        writer.writerows([float(anchor_times[i]), r["newest_sample_index"], r["packets_in_batch"],
                          float(residuals[i]), int(anchor_inliers[i])] for i, r in enumerate(anchors))
    (out/"analysis_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    (out/"SSVEP_two_target_classifier_config.json").write_text(json.dumps(config, indent=2, allow_nan=False), encoding="utf-8")
    save_figure(results, matrix, summary, out/"calibration_summary.png", show)
    print(f"Fixed window: {WINDOW_S:.2f} s; channel {channel}; fitted fs {fs:.3f} Hz")
    print(f"Valid trials: {len(valid)}/{len(results)}; correct: {correct}")
    print("Chance accuracy for balanced two-target selection: 50%")
    print("Valid-trial accuracy:", "N/A" if accuracy is None else f"{100*accuracy:.1f}%")
    print("Correct / all planned trials:", f"{100*completion_rate:.1f}%")
    for label, stat in per_target.items():
        print(f"{label}: {stat['correct']} correct / {stat['valid']} valid / {stat['planned']} planned")
    for r in results:
        if not r["valid"]:
            print(f"Invalid trial {r['trial']}: {r['reason']}")
    print("Pilot baseline passed:", calibration_ok)
    print("Saved to:", out.resolve())
    return summary, results, out


def save_figure(results, matrix, summary, path, show):
    import matplotlib
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), constrained_layout=True)
    valid = [r for r in results if r["valid"]]
    image = axes[0].imshow(matrix, cmap="Blues", vmin=0, vmax=max(1, int(matrix.max())))
    for i in range(len(LABELS)):
        for j in range(len(LABELS)):
            axes[0].text(j, i, str(matrix[i, j]), ha="center", va="center",
                         color="white" if matrix[i, j] > matrix.max()*.55 else "black", fontsize=17)
    axes[0].set(xticks=range(len(LABELS)), yticks=range(len(LABELS)), xticklabels=LABELS, yticklabels=LABELS,
                xlabel="Predicted", ylabel="True target", title="Confusion matrix (valid trials)")
    colors = ("#6188b5", "#60a594")
    for k, label in enumerate(LABELS):
        axes[1].plot([r["trial"] for r in valid], [r[f"cca_{label}"] for r in valid],
                     "o-", ms=3.5, lw=1, color=colors[k], label=label)
    axes[1].set(xlabel="Trial", ylabel="CCA correlation", ylim=(0, 1), title="Two scores from the SAME EEG window")
    axes[1].legend(frameon=False, fontsize=9)
    for i, label in enumerate(LABELS):
        group = [r for r in valid if r["true_target"] == label]
        means = [np.mean([r[f"cca_{candidate}"] for r in group]) if group else 0 for candidate in LABELS]
        for j in range(len(LABELS)):
            axes[2].bar(i+(j-(len(LABELS)-1)/2)*.28, means[j], width=.27, color=colors[j], label=LABELS[j] if i == 0 else None)
    axes[2].set(xticks=range(len(LABELS)), xticklabels=LABELS, xlabel="Instructed target", ylabel="Mean CCA",
                ylim=(0, 1), title="Does the instructed frequency win?")
    axes[2].legend(frameon=False, fontsize=9)
    acc = summary["config"]["baseline_accuracy_valid_trials"]
    text = "N/A" if acc is None else f"{100*acc:.1f}%"
    fig.suptitle(f"Two-target SSVEP | fixed 3 s | {summary['valid_trials']}/{summary['planned_trials']} valid | accuracy {text}", fontsize=13)
    fig.savefig(path, dpi=180)
    if show:
        plt.show()
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eeg", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--channel", default=EEG_CHANNEL)
    parser.add_argument("--no-show", action="store_true")
    args, _ = parser.parse_known_args()  # PsychoPy Coder can supply unrelated launch args.
    eeg = args.eeg or choose_eeg()
    if eeg is None:
        print("Cancelled.")
        return
    analyze(eeg, args.output, not args.no_show, args.channel)


if __name__ == "__main__":
    main()

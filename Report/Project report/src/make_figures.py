"""Diagrams and data plots for the project report (real recordings from data/)."""
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "figures"
PROJ = HERE.parents[2]
sys.path.insert(0, str(PROJ))
from dsp.pulse_dsp import analyze_frame, FEATURE_NAMES  # noqa: E402

NAVY, BLUE, RED, GREEN, GREY, ORANGE = "#0f294a", "#1e56a0", "#c0392b", "#1e8449", "#5d6d7e", "#d68910"
DEV_COL = {"FOB_A": "#8e44ad", "EMU_1": "#17a2b8", "EMU_2": ORANGE, "CLONE_A": RED, "EMU_3": GREEN}
plt.rcParams.update({"font.family": "Times New Roman", "mathtext.fontset": "custom", "mathtext.rm": "Times New Roman", "mathtext.it": "Times New Roman:italic", "mathtext.bf": "Times New Roman:bold", "font.size": 10.5, "axes.titlesize": 11, "axes.titleweight": "bold",
                     "axes.edgecolor": "#444", "axes.grid": True, "grid.alpha": 0.25,
                     "savefig.facecolor": "white"})


def save(fig, name):
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    print("wrote", name)


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def load():
    rows = []
    for f in sorted(glob.glob(str(PROJ / "data" / "s0*.jsonl"))):
        for line in open(f):
            r = json.loads(line)
            if r.get("type") != "frame":
                continue
            fa = analyze_frame(r["d"], int(r.get("g", -1) or -1))
            rows.append((r, fa))
    return rows


# ---------------------------------------------------------------------------
# block diagrams
# ---------------------------------------------------------------------------
def box(ax, x, y, w, h, text, fc="#eaf1fb", ec=BLUE, fs=9, bold=False, tc=NAVY):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=fc, ec=ec, lw=1.4))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
            fontweight="bold" if bold else "normal", color=tc, wrap=True)


def arrow(ax, p, q, text=None, color=NAVY, off=(0, 0.12), fs=8, style="-|>", ls="-"):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=13, color=color, lw=1.4, ls=ls))
    if text:
        ax.text((p[0] + q[0]) / 2 + off[0], (p[1] + q[1]) / 2 + off[1], text, ha="center",
                va="bottom", fontsize=fs, color=color, style="italic")


def fig_architecture():
    fig, ax = plt.subplots(figsize=(12, 6.4))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6.4)
    ax.axis("off")
    # transmitters
    ax.text(1.25, 6.1, "TRANSMITTERS", ha="center", fontsize=10, fontweight="bold", color=GREY)
    box(ax, 0.1, 4.6, 2.3, 1.2, "Genuine remote\nQC5681 (EV1527)\nFOB_A  ON / OFF", fc="#f4ecf7", ec="#8e44ad", bold=True)
    box(ax, 0.1, 2.9, 2.3, 1.3, "ESP32-S3 + STX882\nEMU_1 / EMU_2 (enrolled)\nEMU_3 (unknown)\nCLONE_A (replay)", fc="#fdf2e9", ec=ORANGE)
    # receiver
    ax.add_patch(FancyBboxPatch((3.1, 0.35), 4.4, 5.6, boxstyle="round,pad=0.02,rounding_size=0.1",
                                fc="#fbfcfe", ec=NAVY, lw=1.6, ls="--"))
    ax.text(5.3, 5.72, "RECEIVER NODE (ESP32 @ 240 MHz)", ha="center", fontsize=10, fontweight="bold", color=NAVY)
    box(ax, 3.3, 4.75, 1.4, 0.8, "SRX882\nsuperhet RX", fc="#e8f8f5", ec=GREEN)
    box(ax, 5.0, 4.75, 2.3, 0.8, "GPIO14 ISR: cycle-counter\nedge stamps (4.17 ns)")
    box(ax, 5.0, 3.75, 2.3, 0.7, "Frame cut (4 ms gap)\nglitch merge (<80 us)")
    box(ax, 5.0, 2.8, 2.3, 0.7, "Pulse DSP: clock T, bits,\ncode, 11 features")
    box(ax, 3.3, 2.8, 1.4, 1.65, "EdgeMLP\n11-32-16\n(963 params)\n+ Mahalanobis\nper device", fc="#fef9e7", ec=ORANGE)
    box(ax, 3.3, 1.65, 4.0, 0.8, "Burst fusion (median of 4 frames) -> verdict\nAUTHENTIC / SPOOF / UNKNOWN", fc="#fdedec", ec=RED)
    box(ax, 3.3, 0.55, 2.4, 0.8, "Pattern lock FSM\n(fingerprint + ON/OFF code)", fc="#eafaf1", ec=GREEN)
    box(ax, 5.9, 0.55, 1.4, 0.8, "LED GPIO25\nBuzzer GPIO27", fc="#eafaf1", ec=GREEN, fs=8)
    # laptop
    ax.add_patch(FancyBboxPatch((8.2, 0.35), 3.7, 5.6, boxstyle="round,pad=0.02,rounding_size=0.1",
                                fc="#fbfcfe", ec=GREY, lw=1.6, ls="--"))
    ax.text(10.05, 5.72, "LAPTOP (Python + Next.js)", ha="center", fontsize=10, fontweight="bold", color=GREY)
    box(ax, 8.4, 4.75, 3.3, 0.8, "Serial link (921 600 baud JSON)\nwatchdog auto-reopen")
    box(ax, 8.4, 3.75, 3.3, 0.7, "FastAPI hub: recorder, decisions,\nSQLite event log")
    box(ax, 8.4, 2.8, 3.3, 0.7, "Trainer: FingerprintNet (21 k) +\nEdgeMLP, triplet + CE loss")
    box(ax, 8.4, 1.65, 3.3, 0.8, "Exporter -> phyauth_model.h\n(7 KB C arrays) -> PlatformIO flash")
    box(ax, 8.4, 0.55, 3.3, 0.8, "Dashboard (WebSocket):\nRF Fingerprinting | Smart Lock", fc="#f4f6f7", ec=GREY)
    # arrows
    arrow(ax, (2.4, 5.2), (3.3, 5.15))
    ax.text(2.85, 5.95, "433.92 MHz\nOOK", ha="center", fontsize=8, color=NAVY, style="italic")
    arrow(ax, (2.4, 3.6), (3.3, 4.9))
    arrow(ax, (4.7, 5.15), (5.0, 5.15))
    arrow(ax, (6.15, 4.75), (6.15, 4.45))
    arrow(ax, (6.15, 3.75), (6.15, 3.5))
    arrow(ax, (5.0, 3.15), (4.7, 3.15))
    arrow(ax, (4.0, 2.8), (4.0, 2.45))
    arrow(ax, (4.5, 1.65), (4.5, 1.35))
    arrow(ax, (5.7, 0.95), (5.9, 0.95))
    arrow(ax, (7.3, 5.15), (8.4, 5.15))
    ax.text(7.85, 5.3, "USB", ha="center", fontsize=8, color=NAVY, style="italic")
    arrow(ax, (10.05, 4.75), (10.05, 4.45))
    arrow(ax, (10.05, 3.75), (10.05, 3.5))
    arrow(ax, (10.05, 2.8), (10.05, 2.45))
    arrow(ax, (8.4, 2.05), (7.5, 3.0), color=RED, ls="--")
    ax.text(7.62, 2.25, "flash\nmodel", ha="center", fontsize=8, color=RED, style="italic")
    arrow(ax, (10.05, 1.65), (10.05, 1.35))
    save(fig, "fig_architecture.png")


def fig_lock_fsm():
    fig, ax = plt.subplots(figsize=(12, 5.6))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 5.6)
    ax.axis("off")
    st = {"DISABLED": (0.2, 2.3, "#f4f6f7", GREY), "LEARN": (0.2, 4.4, "#f4ecf7", "#8e44ad"),
          "LOCKED": (4.6, 2.3, "#fdedec", RED), "UNLOCKED": (9.6, 2.3, "#eafaf1", GREEN),
          "LOCKOUT": (4.6, 0.2, "#fef5e7", ORANGE)}
    for k, (x, y, fc, ec) in st.items():
        box(ax, x, y, 2.0, 0.9, k, fc=fc, ec=ec, fs=11, bold=True, tc=ec)
    arrow(ax, (1.2, 3.2), (1.2, 4.4), "LOCK LEARN", off=(0.55, -0.05))
    arrow(ax, (2.2, 4.85), (5.6, 3.2), "same pattern entered twice", off=(0.6, 0.1))
    arrow(ax, (2.2, 2.75), (4.6, 2.75), "LOCK SET", off=(0, 0.06))
    arrow(ax, (6.6, 2.95), (9.6, 2.95), "N presses, all AUTHENTIC, sequence matches", off=(0, 0.08), fs=7.8)
    arrow(ax, (9.6, 2.55), (6.6, 2.55), "pattern again / auto-relock 15 s / LOCK NOW", off=(0, -0.34), fs=7.8)
    arrow(ax, (5.2, 2.3), (5.2, 1.1), "3rd failed attempt", off=(-0.95, -0.12))
    arrow(ax, (6.0, 1.1), (6.0, 2.3), "after 30 s x 2^k", off=(0.9, -0.12))
    ax.text(9.1, 4.75, "While LOCKED, every press is counted without revealing\n"
            "which one was wrong. A foreign or wrong press makes the\n"
            "attempt FAIL only at full length; 30 s of silence clears an\n"
            "unfinished attempt with no penalty.", ha="center", va="center", fontsize=8.3, color=NAVY,
            bbox=dict(boxstyle="round,pad=0.4", fc="#f8f9f9", ec="#aab7b8"))
    save(fig, "fig_lock_fsm.png")


def fig_wiring():
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.8))
    for ax in axs:
        ax.set_xlim(0, 6.6)
        ax.set_ylim(0, 4.6)
        ax.axis("off")
    a, b = axs
    a.set_title("(a) Receiver / verifier node", color=NAVY)
    box(a, 2.45, 0.4, 2.0, 3.8, "ESP32 DevKit\n(ESP32-D0WD-V3)\n\n3V3\nGND\nGPIO14\nGPIO25\nGPIO27\n\nUSB-C to laptop", fc="#eaf1fb", ec=NAVY, fs=9, bold=True)
    box(a, 0.05, 2.6, 1.1, 1.5, "SRX882\n\nVCC, CS\nGND\nDATA", fc="#e8f8f5", ec=GREEN, fs=9, bold=True)
    box(a, 5.0, 2.9, 1.45, 1.0, "Green LED\n+ 470 \u03a9", fc="#eafaf1", ec=GREEN, fs=9, bold=True)
    box(a, 5.0, 1.3, 1.45, 1.0, "Piezo\nbuzzer", fc="#fdedec", ec=RED, fs=9, bold=True)
    arrow(a, (1.15, 3.6), (2.45, 3.6), "VCC, CS -> 3V3", off=(0, 0.04), fs=7.5, style="-")
    arrow(a, (1.15, 3.2), (2.45, 3.2), "GND -> GND", off=(0, 0.04), fs=7.5, style="-")
    arrow(a, (1.15, 2.8), (2.45, 2.8), "DATA -> GPIO14", off=(0, 0.04), fs=7.5)
    arrow(a, (4.45, 3.4), (5.0, 3.4), "GPIO25", off=(0, 0.04), fs=7.5)
    arrow(a, (4.45, 1.8), (5.0, 1.8), "GPIO27", off=(0, 0.04), fs=7.5)
    a.text(3.45, 0.05, "LED cathode and buzzer (-) return to the GND rail", ha="center", fontsize=8, color=GREY, style="italic")
    b.set_title("(b) Transmitter / emulator node", color=NAVY)
    box(b, 1.75, 0.4, 2.0, 3.8, "ESP32-S3-DevKitC\n(N16R8)\n\n3V3\nGND\nGPIO4\nGPIO0 (BOOT)\n\nUSB-C 'COM'\nto laptop", fc="#eaf1fb", ec=NAVY, fs=9, bold=True)
    box(b, 4.8, 2.6, 1.5, 1.5, "STX882\n\nDATA\nVCC\nGND", fc="#fdf2e9", ec=ORANGE, fs=9, bold=True)
    arrow(b, (3.7, 3.6), (4.8, 3.6), "GPIO4 -> DATA", off=(0, 0.04), fs=7.5)
    arrow(b, (3.7, 3.2), (4.8, 3.2), "3V3 -> VCC", off=(0, 0.04), fs=7.5, style="-")
    arrow(b, (3.7, 2.8), (4.8, 2.8), "GND -> GND", off=(0, 0.04), fs=7.5, style="-")
    b.text(0.9, 2.2, "RMT peripheral,\n100 ns ticks;\nwhole press sent as\none waveform", ha="center", fontsize=8.5, color=GREY, style="italic")
    save(fig, "fig_wiring.png")


def fig_pipeline():
    steps = [("1  Edge capture", "GPIO ISR reads CPU cycle counter on every edge\n(240 MHz -> 4.17 ns), lock-free ring buffer"),
             ("2  Framing", "merge glitches < 80 us, cut frames at >= 4 ms LOW,\nkeep the preceding sync gap g"),
             ("3  Clock recovery", "two-symbol clock: pair period P = 4T and\nsync gap = 31T decide T uniquely"),
             ("4  Decoding", "pair-based bit decisions ('HIGH is the long half'),\nquality gate (pair RMS < 8 %, |resid| < 0.45 T)"),
             ("5  Features", "11 code-invariant timing features\n(clock T, jitter, duty errors, drift, sync ratio, ...)"),
             ("6  Embedding", "z-score -> EdgeMLP 11-32-16 -> L2-normalised\nembedding on the unit hypersphere"),
             ("7  Open-set test", "Mahalanobis distance to the claimed device\n(Ledoit-Wolf covariance), score = d / threshold"),
             ("8  Decision", "median score of first 4 frames <= 1 -> AUTHENTIC,\nelse SPOOF (claimed code) / UNKNOWN (no claim)")]
    fig, ax = plt.subplots(figsize=(9, 9.4))
    ax.set_xlim(0, 9)
    ax.set_ylim(0, len(steps) * 1.15 + 0.1)
    ax.axis("off")
    for i, (h, t) in enumerate(steps):
        y = (len(steps) - 1 - i) * 1.15 + 0.15
        box(ax, 0.2, y, 2.4, 0.85, h, fc="#0f294a", ec=NAVY, fs=10, bold=True, tc="white")
        box(ax, 2.9, y, 5.9, 0.85, t, fc="#f4f7fb", ec=BLUE, fs=9)
        if i < len(steps) - 1:
            arrow(ax, (1.4, y), (1.4, y - 0.3))
    save(fig, "fig_pipeline.png")


# ---------------------------------------------------------------------------
# data plots
# ---------------------------------------------------------------------------
def fig_real_frame(rows):
    pick = None
    for r, fa in rows:
        if r["device_id"] == "FOB_A" and fa.ok and r.get("distance_m") == 1.0 and len(fa.pulses_ns) >= 49:
            pick = (r, fa)
            break
    r, fa = pick
    T = fa.clock_t_ns / 1000.0
    w = np.array(fa.pulses_ns) / 1000.0
    t = np.concatenate([[0], np.cumsum(w)])
    lvl = np.array([1 - (i % 2) for i in range(len(w))])
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 5.4), gridspec_kw={"height_ratios": [1.3, 1]}, sharex=True)
    xs, ys = [], []
    for i in range(len(w)):
        xs += [t[i] / 1000, t[i + 1] / 1000]
        ys += [lvl[i], lvl[i]]
    a1.plot(xs, ys, color=BLUE, lw=1.3)
    a1.set_ylim(-0.25, 1.55)
    a1.set_yticks([0, 1])
    a1.set_yticklabels(["LOW", "HIGH"])
    a1.set_title(f"Real FOB_A frame (ON, code 0x{fa.code_hex}) received by SRX882 at 1 m: "
                 f"{len(w)} pulses, recovered T = {T:.1f} us")
    # annotate first two bits
    a1.annotate("bit '1' = 3T HIGH + 1T LOW", xy=((t[0] + t[2]) / 2000, 1.05), xytext=(t[0] / 1000 + 0.1, 1.38),
                fontsize=8.5, color=NAVY, arrowprops=dict(arrowstyle="->", color=NAVY))
    a1.annotate("bit '0' = 1T HIGH + 3T LOW", xy=((t[2] + t[4]) / 2000, 1.05), xytext=(t[4] / 1000 + 4.5, 1.38),
                fontsize=8.5, color=NAVY, arrowprops=dict(arrowstyle="->", color=NAVY))
    a1.text(t[-1] / 1000, 0.5, "trailing sync\nHIGH (then 31T LOW)", ha="right", fontsize=8, color=GREY)
    res = np.array(fa.residuals) * 100
    cols = [ORANGE if l else "#17a2b8" for l in lvl]
    mids = (t[:-1] + t[1:]) / 2000
    a2.bar(mids, res, width=np.maximum(w / 1000 * 0.7, 0.12), color=cols)
    a2.axhline(0, color="#333", lw=0.8)
    a2.set_ylabel("(width - nT) / T  [%]")
    a2.set_xlabel("time within frame [ms]")
    a2.set_title("Per-pulse timing residual: SRX882 shortens every HIGH (orange) and stretches every LOW (blue)")
    save(fig, "fig_real_frame.png")


def fig_width_hist(rows):
    hi, lo = [], []
    for r, fa in rows:
        if r["device_id"] != "FOB_A" or not fa.ok:
            continue
        T = fa.clock_t_ns
        for i, p in enumerate(fa.pulses_ns):
            (hi if i % 2 == 0 else lo).append(p / T)
    fig, ax = plt.subplots(figsize=(10, 3.6))
    bins = np.linspace(0.4, 3.6, 161)
    ax.hist(hi, bins=bins, color=ORANGE, alpha=0.75, label=f"HIGH pulses ({len(hi):,})")
    ax.hist(lo, bins=bins, color="#17a2b8", alpha=0.6, label=f"LOW pulses ({len(lo):,})")
    for n in (1, 3):
        ax.axvline(n, color=NAVY, ls="--", lw=1)
        ax.text(n, ax.get_ylim()[1] * 0.92, f" {n}T ideal", color=NAVY, fontsize=9)
    ax.set_xlabel("pulse width / recovered clock T")
    ax.set_ylabel("count")
    ax.set_title("Pulse-width distribution of the genuine remote (all FOB_A frames): two symbols, biased by the receiver slicer")
    ax.legend()
    save(fig, "fig_width_hist.png")


def fig_feature_scatter(rows):
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.6))
    pairs = [(0, 1), (2, 5)]
    for ax, (i, j) in zip(axs, pairs):
        for dev in ["FOB_A", "EMU_1", "EMU_2", "CLONE_A", "EMU_3"]:
            X = np.array([fa.features for r, fa in rows if fa.ok and (r["device_id"] == dev or
                          (dev == "FOB_A" and r["device_id"] == "FOB_A_OFF"))])
            if not len(X):
                continue
            m = np.isfinite(X[:, i]) & np.isfinite(X[:, j])
            mk = "x" if dev in ("CLONE_A", "EMU_3") else "o"
            ax.scatter(X[m, i], X[m, j], s=10, alpha=0.55, marker=mk, color=DEV_COL[dev],
                       label=dev + (" (not enrolled)" if mk == "x" else ""))
        ax.set_xlabel(FEATURE_NAMES[i])
        ax.set_ylabel(FEATURE_NAMES[j])
    axs[0].set_xlim(300, 345)
    axs[0].set_ylim(3000, 13500)
    axs[0].set_title("Clock period vs bit-period jitter")
    axs[1].set_title("Short-HIGH duty error vs first-edge residual")
    axs[1].legend(fontsize=8, loc="best")
    fig.suptitle("Raw physical features of every accepted frame (before the neural embedding)", fontweight="bold", color=NAVY)
    save(fig, "fig_feature_scatter.png")


def fig_dataset(rows):
    cnt = defaultdict(lambda: defaultdict(int))
    for r, fa in rows:
        if not fa.ok:
            continue
        dev = r["device_id"]
        cnt[dev][r.get("distance_m")] += 1
    devs = ["FOB_A", "FOB_A_OFF", "EMU_1", "EMU_2", "EMU_3", "CLONE_A"]
    dists = [0.75, 1.0, 1.25]
    fig, ax = plt.subplots(figsize=(10, 3.6))
    bottom = np.zeros(len(devs))
    for d, c in zip(dists, ["#aed6f1", "#5dade2", "#1b4f72"]):
        v = np.array([cnt[x].get(d, 0) for x in devs])
        ax.bar(devs, v, bottom=bottom, color=c, label=f"{d} m")
        bottom += v
    for k, b in enumerate(bottom):
        ax.text(k, b + 5, int(b), ha="center", fontsize=9, fontweight="bold")
    ax.set_ylabel("decoded frames")
    ax.set_title("Dataset: frames that passed the quality gate, by transmitter and distance")
    ax.legend(title="distance")
    save(fig, "fig_dataset.png")
    return {d: dict(v) for d, v in cnt.items()}


def fig_frames_decision():
    a = json.loads((PROJ / "Report" / "Seminar" / "analysis.json").read_text())["frames_per_decision"]
    n = [x["frames"] for x in a]
    frr = [x["genuine_frr"] * 100 for x in a]
    lat = [x["latency_ms"] for x in a]
    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.bar(n, frr, color=BLUE, width=0.55, label="genuine presses rejected (FRR)")
    for x, y in zip(n, frr):
        ax.text(x, y + 1, f"{y:.1f} %", ha="center", fontsize=9, fontweight="bold")
    ax.set_xlabel("frames fused per decision")
    ax.set_ylabel("FRR [%]  (90 genuine presses)")
    ax.set_xticks(n)
    ax2 = ax.twinx()
    ax2.plot(n, lat, "o-", color=RED, label="decision latency")
    ax2.set_ylabel("latency after first frame [ms]", color=RED)
    ax2.grid(False)
    ax.set_title("Burst fusion trade-off (clone and unknown rejection stayed 100 % at every setting)")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper center")
    save(fig, "fig_frames_decision.png")


def fig_distance(report):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 3.9), gridspec_kw={"width_ratios": [1.1, 1]})
    for k, (name, col) in enumerate((("edge", BLUE), ("fusion", "#8e44ad"))):
        bd = report["models"][name]["by_distance"]
        x = np.arange(len(bd)) + (k - 0.5) * 0.36
        y = [b["frr"] * 100 for b in bd]
        a1.bar(x, y, width=0.34, color=col, label=f"{name} model")
        for xi, yi in zip(x, y):
            a1.text(xi, yi + 0.6, f"{yi:.1f}", ha="center", fontsize=8.5)
    a1.set_xticks(range(len(bd)))
    a1.set_xticklabels([f"{b['distance_m']} m\n({b['frames']} test frames)" for b in bd])
    a1.set_ylabel("single-frame FRR [%]")
    a1.set_title("(a) Single-frame FRR by distance")
    a1.legend()
    # operating window (bench observation)
    zones = [(0.0, 0.5, "#f5b7b1", "receiver saturates\n(AGC/slicer clip)"),
             (0.5, 0.75, "#fad7a0", "marginal"),
             (0.75, 1.25, "#abebc6", "reliable window\n0.75 - 1.25 m"),
             (1.25, 1.5, "#fad7a0", "marginal"),
             (1.5, 2.2, "#f5b7b1", "short pulses lost\n(SNR too low)")]
    for x0, x1, c, t in zones:
        a2.axvspan(x0, x1, color=c, alpha=0.9)
        a2.text((x0 + x1) / 2, 0.5, t, ha="center", va="center", fontsize=8.2, rotation=90 if x1 - x0 < 0.3 else 0)
    a2.set_xlim(0, 2.2)
    a2.set_yticks([])
    a2.set_xlabel("remote-to-antenna distance [m]")
    a2.set_title("(b) Observed SRX882 decoding window")
    a2.grid(False)
    save(fig, "fig_distance.png")


def main():
    OUT.mkdir(exist_ok=True)
    # architecture, pipeline, lock FSM and wiring are TikZ: tikz/build_tikz.py
    fig_frames_decision()
    rep = json.loads(Path(sys.argv[1]).read_text()) if len(sys.argv) > 1 else None
    if rep:
        fig_distance(rep)
    rows = load()
    fig_real_frame(rows)
    fig_width_hist(rows)
    fig_feature_scatter(rows)
    stats = fig_dataset(rows)
    ok = sum(1 for _, fa in rows if fa.ok)
    print("frames", len(rows), "ok", ok)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()

"""Illustrative (synthetic) figures for the seminar survey slides."""
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle
T, O, N, G, BG = "#0E6E73", "#B4531A", "#1B2638", "#7A8394", "#FDFCFA"
plt.rcParams.update({"font.size": 15, "axes.edgecolor": "#555", "axes.grid": True, "grid.alpha": .25,
                     "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG})
rng = np.random.default_rng(3)
def save(f, n): f.savefig(n, dpi=160, bbox_inches="tight", pad_inches=.15); plt.close(f)

# 1 impairment chain
f, a = plt.subplots(figsize=(9, 5.2)); a.axis("off"); a.set_xlim(0, 10); a.set_ylim(0, 6)
blocks = [("Bits", 0.2), ("DAC +\nfilter", 2.2), ("I/Q\nmixer", 4.2), ("Oscillator", 4.2), ("Power\namplifier", 6.2), ("Antenna", 8.2)]
for i, (t, x) in enumerate(blocks):
    y = 1.0 if t == "Oscillator" else 3.4
    a.add_patch(FancyBboxPatch((x, y), 1.6, 1.2, boxstyle="round,pad=.05", fc="#EEF1F6", ec=N, lw=1.6))
    a.text(x + .8, y + .6, t, ha="center", va="center", fontsize=14, color=N, weight="bold")
for x in (1.8, 3.8, 5.8, 7.8):
    a.annotate("", (x + .4, 4.0), (x, 4.0), arrowprops=dict(arrowstyle="-|>", color=N, lw=1.6))
a.annotate("", (5.0, 3.4), (5.0, 2.2), arrowprops=dict(arrowstyle="-|>", color=N, lw=1.6))
for x, y, t in [(3.0, 4.9, "distortion"), (5.0, 5.6, "I/Q imbalance"), (3.2, 0.3, "frequency offset · clock skew · phase noise"), (7.6, 4.9, "non-linearity,\nturn-on transient")]:
    a.text(x, y, t, ha="center", fontsize=13, color=O, style="italic", weight="bold")
save(f, "fig_impairments.png")

# 2 clock skew
f, a = plt.subplots(figsize=(8, 5))
t = np.linspace(0, 60, 120)
for s, c, l in [(35, T, "Device A (+35 ppm)"), (-20, O, "Device B (−20 ppm)"), (5, N, "Device C (+5 ppm)")]:
    a.plot(t, s * t / 1000 + rng.normal(0, .08, t.size), color=c, lw=2, label=l)
a.set_xlabel("observation time [min]"); a.set_ylabel("clock offset [ms]"); a.legend(frameon=False)
a.set_title("Clock offset grows at a device-specific slope", color=N, weight="bold")
save(f, "fig_clockskew.png")

# 3 transient
f, a = plt.subplots(figsize=(8, 5))
t = np.linspace(0, 10, 600)
for tau, ov, c, l in [(0.9, .18, T, "Device A"), (1.6, .05, O, "Device B")]:
    env = np.where(t < 2, 0, 1 - np.exp(-(t - 2) / tau) + ov * np.exp(-(t - 2) / 1.2) * np.sin((t - 2) * 3))
    a.plot(t, env + rng.normal(0, .01, t.size), color=c, lw=2, label=l)
a.axvspan(2, 6, color="#F7E9DF", alpha=.6); a.text(4, 0.12, "turn-on transient", ha="center", color=O, weight="bold")
a.set_xlabel("time [µs]"); a.set_ylabel("envelope amplitude"); a.legend(frameon=False, loc="lower right")
a.set_title("Same model, different turn-on shape", color=N, weight="bold")
save(f, "fig_transient.png")

# 4 constellation errors
f, a = plt.subplots(figsize=(6.4, 6.4))
ideal = np.array([[1, 1], [1, -1], [-1, 1], [-1, -1]]) / np.sqrt(2)
ang = np.deg2rad(5)
R = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
for p in ideal:
    q = (R @ (p * [1.05, .96])) + [.05, -.03]
    pts = q + rng.normal(0, .045, (60, 2))
    a.scatter(pts[:, 0], pts[:, 1], s=10, color=T, alpha=.6)
a.scatter(ideal[:, 0], ideal[:, 1], s=180, marker="x", color=O, lw=3, label="ideal symbol")
a.scatter([], [], s=30, color=T, label="measured (offset, rotation, I/Q gain error)")
a.set_xlim(-1.3, 1.3); a.set_ylim(-1.3, 1.3); a.set_aspect("equal"); a.set_xlabel("I"); a.set_ylabel("Q")
a.legend(frameon=False, loc="upper center", bbox_to_anchor=(.5, -.12), fontsize=13)
a.set_title("Modulation errors in the constellation", color=N, weight="bold")
save(f, "fig_constellation.png")

# 5 CNN pipeline
f, a = plt.subplots(figsize=(11, 3.6)); a.axis("off"); a.set_xlim(0, 11); a.set_ylim(0, 3.6)
x = np.linspace(0, 1.8, 200)
a.plot(.2 + x, 2.6 + .35 * np.sin(18 * x), color=T, lw=1.4); a.plot(.2 + x, 1.6 + .35 * np.cos(18 * x + .4), color=O, lw=1.4)
a.text(1.1, .6, "raw I/Q\nsamples", ha="center", fontsize=14, color=N, weight="bold")
for i, (xx, h) in enumerate([(3.0, 2.6), (4.2, 2.1), (5.4, 1.6), (6.6, 1.1)]):
    a.add_patch(FancyBboxPatch((xx, 1.8 - h / 2), .7, h, boxstyle="round,pad=.03", fc="#E6F1F1", ec=T, lw=1.5))
a.text(4.8, .25, "convolution + pooling layers", ha="center", fontsize=14, color=N, weight="bold")
a.add_patch(FancyBboxPatch((7.9, 1.2), .9, 1.2, boxstyle="round,pad=.03", fc="#F7E9DF", ec=O, lw=1.5))
a.text(8.35, .7, "dense", ha="center", fontsize=14, color=N, weight="bold")
for i, t_ in enumerate(["Device 1", "Device 2", "Device 3"]):
    a.text(9.4, 2.7 - i * .7, t_, fontsize=14, color=N)
for x0, x1 in [(2.15, 2.9), (7.4, 7.85), (8.85, 9.3)]:
    a.annotate("", (x1, 1.8), (x0, 1.8), arrowprops=dict(arrowstyle="-|>", color=N, lw=1.6))
save(f, "fig_cnn.png")

# 6 channel effect
f, a = plt.subplots(figsize=(8, 5))
fr = np.linspace(-1, 1, 300)
dev = 1 + .15 * np.sin(4 * fr)
for d, c, l in [(0, T, "location 1"), (2.2, O, "location 2")]:
    ch = 1 + .45 * np.cos(np.pi * fr * 3 + d)
    a.plot(fr, 20 * np.log10(dev * ch), color=c, lw=2, label=l)
a.plot(fr, 20 * np.log10(dev), color=N, lw=2, ls="--", label="device response only")
a.set_xlabel("normalised frequency"); a.set_ylabel("magnitude [dB]"); a.legend(frameon=False, fontsize=13)
a.set_title("Same device, different multipath channel", color=N, weight="bold")
save(f, "fig_channel.png")

# 7 open set
f, a = plt.subplots(figsize=(7, 6))
cents = {"A": (-1.5, 1), "B": (1.6, 1.2), "C": (0, -1.5)}
for (k, c), col in zip(cents.items(), [T, O, N]):
    p = np.array(c) + rng.normal(0, .3, (60, 2)); a.scatter(p[:, 0], p[:, 1], s=14, color=col, alpha=.7)
    a.add_patch(Circle(c, 1.0, fill=False, ec=col, lw=2, ls="--")); a.text(c[0], c[1] + 1.12, f"enrolled {k}", ha="center", color=col, weight="bold")
u = np.array((2.1, -0.9)) + rng.normal(0, .25, (25, 2))
a.scatter(u[:, 0], u[:, 1], s=60, marker="x", color="#9A3412", lw=2); a.text(2.2, -1.75, "unknown device:\nrejected", ha="center", color="#9A3412", weight="bold")
a.set_xlim(-3.2, 3.4); a.set_ylim(-2.6, 2.8); a.set_aspect("equal"); a.set_xticks([]); a.set_yticks([])
a.set_title("Open set: accept only inside a device's boundary", color=N, weight="bold")
save(f, "fig_openset.png")
print("ok")

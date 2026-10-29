"""Generate report diagrams as SVG (rendered to PNG with rsvg-convert)."""
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "diagrams"
SRC = Path(__file__).resolve().parent
FONT = 'font-family="Helvetica, Arial, sans-serif"'


def svg(name, w, h, body, title):
    s = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" {FONT}>'
         f'<rect width="{w}" height="{h}" fill="#fff"/>'
         '<defs><marker id="a" markerWidth="14" markerHeight="14" refX="12" refY="7" orient="auto">'
         '<path d="M0,0 L14,7 L0,14 z" fill="#333"/></marker></defs>'
         f'<text x="{w/2}" y="62" text-anchor="middle" font-size="40" font-weight="bold" fill="#111">{title}</text>'
         f'{body}</svg>')
    p = SRC / f"{name}.svg"
    p.write_text(s)
    subprocess.run(["rsvg-convert", "-w", str(w), str(p), "-o", str(OUT / f"{name}.png")], check=True)


def box(x, y, w, h, lines, fill="#f3f8ff", stroke="#1565c0", bold_first=True, fs=26):
    out = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="3"/>'
    n = len(lines)
    y0 = y + h / 2 - (n - 1) * fs * 0.62
    for i, t in enumerate(lines):
        wgt = ' font-weight="bold"' if (i == 0 and bold_first) else ''
        col = "#111" if i == 0 else "#444"
        out += f'<text x="{x+w/2}" y="{y0+i*fs*1.25+fs*0.35}" text-anchor="middle" font-size="{fs}"{wgt} fill="{col}">{t}</text>'
    return out


def arrow(x1, y1, x2, y2, label=""):
    s = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#333" stroke-width="4" marker-end="url(#a)"/>'
    if label:
        s += f'<text x="{(x1+x2)/2+12}" y="{(y1+y2)/2-8}" font-size="22" fill="#333">{label}</text>'
    return s


# 1. system block diagram -------------------------------------------------
b = ""
b += box(60, 200, 420, 200, ["433 MHz remote (FOB_A)", "EV1527 encoder", "code 0x936768"], "#e8f5e9", "#2e7d32")
b += box(60, 460, 420, 200, ["Test transmitter node", "ESP32-S3 + STX882", "other-device profiles"], "#fff8e1", "#f9a825")
b += box(620, 320, 340, 220, ["SRX882", "superhet OOK", "receiver"])
b += box(1090, 260, 400, 340, ["ESP32 receiver", "edge timing 4.17 ns", "DSP + EdgeMLP", "Mahalanobis verify", "LED verdict"])
b += box(1640, 200, 380, 200, ["Laptop backend", "FastAPI, training,", "SQLite"], "#f3e5f5", "#6a1b9a")
b += box(1640, 470, 380, 200, ["Web dashboard", "Next.js, live view,", "reports"], "#f3e5f5", "#6a1b9a")
b += arrow(480, 300, 620, 400, "") + arrow(480, 560, 620, 460, "")
b += '<text x="500" y="440" font-size="22" fill="#333">433.92 MHz OOK</text>'
b += arrow(960, 430, 1090, 430, "DATA")
b += arrow(1490, 360, 1640, 300, "USB 921600")
b += arrow(1830, 400, 1830, 470, "WS")
b += box(1090, 700, 400, 150, ["Verdict per press", "AUTHENTIC / SPOOF / UNKNOWN"], "#ffebee", "#c62828")
b += arrow(1290, 600, 1290, 700)
svg("01_system_block_diagram", 2100, 900, b, "System block diagram")

# 2. processing flowchart -------------------------------------------------
steps = [
    ["GPIO edge interrupt", "timestamp with CPU cycle counter"],
    ["Pulse widths", "frame cut at LOW gap ≥ 4 ms"],
    ["Glitch merge (< 80 µs)"],
    ["Clock estimate", "P = H+L,  n from sync = 31 T,  T = P / n"],
    ["Decode pairs → 24-bit code (claim)"],
    ["Quality gate", "≥ 12 pairs, timing RMS ≤ 8 %, no outliers"],
    ["11 physical features", "T, jitter, duty distortion, drift, sync ratio …"],
    ["EdgeMLP embedding", "11 → 32 → 16, L2-normalised"],
    ["Mahalanobis distance to claimed device", "score = d / threshold"],
    ["Per press: median of first 4 frames"],
]
b = ""
y = 110
for i, s in enumerate(steps):
    h = 95 if len(s) == 1 else 120
    b += box(500, y, 900, h, s, fs=27)
    if i < len(steps) - 1:
        b += arrow(950, y + h, 950, y + h + 40)
    y += h + 40
b += f'<polygon points="950,{y} 1250,{y+90} 950,{y+180} 650,{y+90}" fill="#fff8e1" stroke="#f9a825" stroke-width="3"/>'
b += f'<text x="950" y="{y+100}" text-anchor="middle" font-size="28" font-weight="bold">score ≤ 1 ?</text>'
b += arrow(950, y - 40, 950, y)
b += box(250, y + 230, 520, 110, ["AUTHENTIC", "LED solid"], "#e8f5e9", "#2e7d32")
b += box(1130, y + 230, 520, 110, ["SPOOF / UNKNOWN", "code claimed / not enrolled · LED blinks"], "#ffebee", "#c62828")
b += arrow(800, y + 140, 600, y + 230, "yes") + arrow(1100, y + 140, 1300, y + 230, "no")
svg("02_processing_flowchart", 1900, y + 380, b, "Signal processing and decision flowchart")

# 3/4. wiring ----------------------------------------------------------------
def wiring(name, title, board, module, rows, note):
    b = box(150, 160, 520, 560, [board, "", "", "", "", ""], "#263238", "#263238")
    b = b.replace('fill="#111"', 'fill="#fff"', 1)
    b += box(1250, 230, 440, 420, [module, "", "", ""], "#1565c0", "#0d47a1")
    b = b.replace(f'>{module}<', f' fill="#fff">{module}<')
    colors = ["#e53935", "#212121", "#fbc02d", "#43a
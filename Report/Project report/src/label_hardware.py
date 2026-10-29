"""Hardware photos on a white background with labelled call-outs."""
from pathlib import Path
import unicodedata
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = "Times New Roman"
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
IMG = ROOT / "Images"
OUT = ROOT / "figures"
SEM = ROOT.parent / "Seminar" / "src"


def find(prefix):
    for f in IMG.iterdir():
        if unicodedata.normalize("NFKC", f.name).replace(" ", " ").startswith(prefix):
            return f
    raise FileNotFoundError(prefix)


def on_white(path):
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    return bg.convert("RGB")


def labelled(im, labels, out, title=None, pad=(0.42, 0.42), w=11):
    """labels: (text, (x, y) on image, side 'L'|'R', y_text_frac)."""
    W, H = im.size
    fig_w = w
    fig_h = fig_w * H / W / (1 + pad[0] + pad[1]) * 1.0
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=200)
    ax = fig.add_axes([pad[0] / (1 + sum(pad)), 0, 1 / (1 + sum(pad)), 1])
    ax.imshow(im)
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")
    for i, (text, (x, y), side, fy) in enumerate(labels, 1):
        tx = -W * 0.06 if side == "L" else W * 1.06
        ty = fy * H
        ax.annotate(f"{i}. {text}", xy=(x, y), xytext=(tx, ty), textcoords="data",
                    ha="right" if side == "L" else "left", va="center", fontsize=10.5,
                    fontweight="bold", color="#0f294a", annotation_clip=False,
                    bbox=dict(boxstyle="round,pad=0.35", fc="#f3f6fb", ec="#1e56a0", lw=1),
                    arrowprops=dict(arrowstyle="-|>", color="#c0392b", lw=1.4, shrinkA=0, shrinkB=2))
        ax.plot([x], [y], "o", ms=6, mfc="none", mec="#c0392b", mew=1.8)
    if title:
        fig.suptitle(title, fontsize=12, fontweight="bold", color="#0f294a", y=0.995)
    fig.savefig(OUT / out, facecolor="white", bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print("wrote", out)


def main():
    OUT.mkdir(exist_ok=True)
    rx = on_white(find("Screenshot 2026-10-21 at 10.39.44"))
    labelled(rx, [
        ("Piezo buzzer\nGPIO27 (alarm: wrong pattern,\nforeign remote, lockout)", (165, 690), "L", 0.38),
        ("ESP32 DevKit\n(ESP32-D0WD-V3, 240 MHz)\nedge-timestamping + TinyML", (650, 1240), "L", 0.62),
        ("USB-C: 5 V power +\n921 600 baud serial to laptop", (150, 1150), "L", 0.84),
        ("433 MHz helical\nspring antenna (RX)", (1335, 330), "R", 0.18),
        ("SRX882 superheterodyne\nASK receiver, 433.92 MHz\nDATA -> GPIO14, VCC/CS -> 3V3", (1395, 1010), "R", 0.50),
        ("Green status LED\nGPIO25 (unlocked / press\naccepted / alarm blink)", (1166, 1317), "R", 0.76),
        ("470 Ω current-limiting\nresistor (LED series)", (1060, 1356), "R", 0.93),
    ], "fig_receiver_labelled.png")

    tx = on_white(find("Screenshot 2026-10-21 at 10.40.30"))
    labelled(tx, [
        ("On-board RGB LED\n(TX activity)", (425, 1080), "L", 0.48),
        ("USB-C 'USB' (native CDC)", (150, 1090), "L", 0.62),
        ("USB-C 'COM' (UART):\npower + commands from laptop", (150, 1330), "L", 0.76),
        ("BOOT button\n(manual press trigger)", (600, 1290), "L", 0.92),
        ("433 MHz helical\nspring antenna (TX)", (1290, 330), "R", 0.18),
        ("STX882 ASK transmitter\n433.92 MHz", (1385, 770), "R", 0.40),
        ("STX882 pins: DATA -> GPIO4,\nVCC -> 3V3, GND -> GND", (1385, 885), "R", 0.55),
        ("ESP32-S3-DevKitC (N16R8)\nRMT peripheral, 100 ns ticks", (960, 1250), "R", 0.74),
        ("RST button", (694, 1290), "R", 0.92),
    ], "fig_transmitter_labelled.png")

    rf = on_white(SEM / "remote_front_clean.png")
    fig, a0 = plt.subplots(figsize=(6.5, 5.6), dpi=200)
    a0.imshow(rf)
    a0.axis("off")
    W, H = rf.size
    for text, xy, xt in [
        ("Telescopic antenna", (172, 165), (-120, 120)),
        ("Status LED", (222, 222), (-120, 220)),
        ("ON  (key nibble 0x8)\ncode 0x936768", (222, 270), (-120, 300)),
        ("OFF (key nibble 0x4)\ncode 0x936764", (222, 320), (-120, 390)),
        ("QC5681 shell, EV1527\nencoder + SAW-stabilised\n433.92 MHz oscillator inside", (222, 440), (-120, 500)),
    ]:
        a0.annotate(text, xy=xy, xytext=xt, ha="right", va="center", fontsize=10, fontweight="bold",
                    color="#0f294a", annotation_clip=False,
                    bbox=dict(boxstyle="round,pad=0.3", fc="#f3f6fb", ec="#1e56a0", lw=1),
                    arrowprops=dict(arrowstyle="-|>", color="#c0392b", lw=1.3))
    a0.set_xlim(0, W)
    fig.savefig(OUT / "fig_remote_labelled.png", facecolor="white", bbox_inches="tight", pad_inches=0.15)
    print("wrote fig_remote_labelled.png")


if __name__ == "__main__":
    main()

"""Compile the TikZ diagrams and render them as 300-dpi PNGs into ../../figures."""
import subprocess
from pathlib import Path

import fitz

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "figures"
for tex in ("fig_architecture", "fig_pipeline", "fig_lock_fsm", "fig_wiring"):
    subprocess.run(["pdflatex", "-interaction=nonstopmode", f"{tex}.tex"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL)
    fitz.open(HERE / f"{tex}.pdf")[0].get_pixmap(dpi=300).save(OUT / f"{tex}.png")
    print("wrote", tex + ".png")
for ext in ("aux", "log"):
    for f in HERE.glob(f"*.{ext}"):
        f.unlink()

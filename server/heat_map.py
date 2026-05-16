"""
Generate a gaze heatmap from the logged CSV file.
"""

import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter

SCREEN_WIDTH  = 1920  # must match what you set in the tracker
SCREEN_HEIGHT = 1080
CSV_FILE      = "gaze_log_20260512_192309.csv"

df = pd.read_csv(CSV_FILE)
print(f"Loaded {len(df)} gaze points from {CSV_FILE}")

# Build a 2D density grid
heatmap = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.float32)

for _, row in df.iterrows():
    x, y = int(row["screen_x"]), int(row["screen_y"])
    if 0 <= x < SCREEN_WIDTH and 0 <= y < SCREEN_HEIGHT:
        heatmap[y, x] += 1

# Smooth with Gaussian blur (increase sigma for more spread)
heatmap = gaussian_filter(heatmap, sigma=40)

# Plot
fig, ax = plt.subplots(figsize=(16, 9))
ax.imshow(heatmap, cmap="jet", origin="upper",
          extent=[0, SCREEN_WIDTH, SCREEN_HEIGHT, 0])
ax.set_title("Gaze Heatmap", fontsize=16)
ax.set_xlabel("Screen X (px)")
ax.set_ylabel("Screen Y (px)")
plt.colorbar(ax.images[0], ax=ax, label="Gaze density")
plt.tight_layout()

output = CSV_FILE.replace(".csv", "_heatmap.png")
plt.savefig(output, dpi=150)
print(f"Heatmap saved to {output}")
plt.show()
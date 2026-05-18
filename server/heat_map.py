"""
Generate a gaze heatmap from the logged CSV file.
"""

import sys
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter

SCREEN_WIDTH  = 1920  # must match what you set in the tracker
SCREEN_HEIGHT = 1080

def generate_heatmap(csv_file, show=False):
    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} does not exist.")
        return None

    df = pd.read_csv(csv_file)
    print(f"Loaded {len(df)} gaze points from {csv_file}")

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

    output = csv_file.replace(".csv", "_heatmap.png")
    plt.savefig(output, dpi=150)
    print(f"Heatmap saved to {output}")
    
    if show:
        plt.show()
        
    plt.close(fig)
    return output

if __name__ == "__main__":
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
    else:
        # Try to find the most recent log file
        import glob
        logs = glob.glob(os.path.join("logs", "gaze_log_*.csv")) + glob.glob(os.path.join("server", "logs", "gaze_log_*.csv"))
        if logs:
            csv_file = max(logs, key=os.path.getctime)
            print(f"No CSV file provided. Using most recent: {csv_file}")
        else:
            print("Usage: python heat_map.py <path_to_csv>")
            sys.exit(1)
            
    generate_heatmap(csv_file, show=True)
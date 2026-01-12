#!/usr/bin/env python3
"""
Analyze the actual pixel colors around Feb 13 in the Butts calendar.
This will help us understand if there's actually a color difference.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pdf2image import convert_from_path
from PIL import Image
import numpy as np

PDF_PATH = PROJECT_ROOT / "Official_Calendars" / "Public" / "Butts" / "ButtsSchoolYearCalendar2025-2026_FINAL_Approved1112.pdf"


def analyze_calendar():
    """Analyze pixel colors in the calendar."""
    print("Converting PDF at DPI 300...")
    images = convert_from_path(str(PDF_PATH), dpi=300, poppler_path='/opt/homebrew/bin')
    img = images[0]

    print(f"Image size: {img.size}")
    print(f"Image mode: {img.mode}")

    # Convert to numpy array
    arr = np.array(img)

    # Let's sample colors from different regions
    # First, save the image so we can look at it
    output_path = PROJECT_ROOT / "scripts" / "test_images" / "full_calendar_300dpi.png"
    output_path.parent.mkdir(exist_ok=True)
    img.save(output_path)
    print(f"Saved full calendar to: {output_path}")

    # Get image dimensions
    height, width = arr.shape[:2]
    print(f"Dimensions: {width}x{height}")

    # Sample some pixel regions to understand the color palette
    print("\nAnalyzing pixel samples...")

    # Sample from corners and center to understand the color range
    samples = [
        ("Top-left", arr[50:60, 50:60]),
        ("Top-right", arr[50:60, width-60:width-50]),
        ("Center", arr[height//2-5:height//2+5, width//2-5:width//2+5]),
        ("Bottom-left", arr[height-60:height-50, 50:60]),
        ("Bottom-right", arr[height-60:height-50, width-60:width-50]),
    ]

    for name, region in samples:
        avg_color = np.mean(region, axis=(0, 1))
        print(f"  {name}: RGB({avg_color[0]:.0f}, {avg_color[1]:.0f}, {avg_color[2]:.0f})")

    # Now let's look at a histogram of colors
    print("\nColor distribution analysis...")

    # Flatten and look at unique colors
    flat = arr.reshape(-1, 3)

    # Count white-ish pixels (R, G, B all > 240)
    white_mask = (flat[:, 0] > 240) & (flat[:, 1] > 240) & (flat[:, 2] > 240)
    white_count = np.sum(white_mask)
    total = len(flat)
    print(f"  White-ish pixels (>240): {white_count:,} / {total:,} ({100*white_count/total:.1f}%)")

    # Look for yellow-ish pixels (R > 200, G > 200, B < 180)
    yellow_mask = (flat[:, 0] > 200) & (flat[:, 1] > 200) & (flat[:, 2] < 180)
    yellow_count = np.sum(yellow_mask)
    print(f"  Yellow-ish pixels: {yellow_count:,} / {total:,} ({100*yellow_count/total:.1f}%)")

    # Look for blue-ish pixels (B > R and B > G)
    blue_mask = (flat[:, 2] > flat[:, 0]) & (flat[:, 2] > flat[:, 1]) & (flat[:, 2] > 150)
    blue_count = np.sum(blue_mask)
    print(f"  Blue-ish pixels: {blue_count:,} / {total:,} ({100*blue_count/total:.1f}%)")

    # Find unique non-white colors
    print("\nLooking for distinct calendar colors...")
    non_white = flat[~white_mask]
    if len(non_white) > 0:
        # Get a sample of unique colors
        unique_colors = np.unique(non_white, axis=0)
        print(f"  Found {len(unique_colors)} unique non-white colors")

        # Show some of the most common non-white colors
        from collections import Counter
        color_tuples = [tuple(c) for c in non_white]
        color_counts = Counter(color_tuples)
        print("\n  Top 20 non-white colors:")
        for color, count in color_counts.most_common(20):
            r, g, b = color
            # Classify the color
            if r > 200 and g > 200 and b < 150:
                color_type = "YELLOW"
            elif b > r and b > g:
                color_type = "BLUE"
            elif r > b and g > b and r > 150 and g > 150:
                color_type = "LIGHT YELLOW/CREAM"
            elif r == g == b:
                color_type = "GRAY"
            else:
                color_type = "OTHER"
            print(f"    RGB({r:3d}, {g:3d}, {b:3d}) - count: {count:6d} - {color_type}")


if __name__ == "__main__":
    analyze_calendar()

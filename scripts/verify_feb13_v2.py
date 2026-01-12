#!/usr/bin/env python3
"""
Extract the full February section correctly and analyze colors.
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
    """Full analysis of the calendar image."""
    print("Converting PDF at DPI 400...")
    images = convert_from_path(str(PDF_PATH), dpi=400, poppler_path='/opt/homebrew/bin')
    img = images[0]
    arr = np.array(img)

    height, width = arr.shape[:2]
    print(f"Image dimensions: {width}x{height}")

    output_dir = PROJECT_ROOT / "scripts" / "test_images"
    output_dir.mkdir(exist_ok=True)

    # Let me try a different approach - crop a larger area that definitely includes Feb
    # and save it so we can see the structure

    # The calendar has 4 rows of months (3 months per row):
    # Row 1: July, Aug, Sep
    # Row 2: Oct, Nov, Dec
    # Row 3: Jan, Feb, Mar
    # Row 4: Apr, May, Jun

    # Each row is approximately 1/4 of the usable calendar area
    # With headers and legend, usable area is roughly 15% to 85% of height

    # Let's crop the third row (Jan/Feb/Mar) more precisely
    # Looking at the layout, this row should be around 50-70% of height

    # Crop the entire Jan/Feb/Mar row
    row3_top = int(height * 0.50)
    row3_bottom = int(height * 0.68)

    row3_img = img.crop((0, row3_top, width, row3_bottom))
    row3_img.save(output_dir / "row3_jan_feb_mar.png")
    print(f"Saved Row 3 (Jan/Feb/Mar) to: {output_dir / 'row3_jan_feb_mar.png'}")

    # Now let's look specifically at the February portion
    # February is in the middle third of the row
    feb_left = int(width * 0.33)
    feb_right = int(width * 0.66)
    feb_top = row3_top
    feb_bottom = row3_bottom

    feb_full = img.crop((feb_left, feb_top, feb_right, feb_bottom))
    feb_full.save(output_dir / "feb_full.png")
    print(f"Saved February full section to: {output_dir / 'feb_full.png'}")

    # Now analyze pixel colors in the February section
    feb_arr = np.array(feb_full)
    feb_h, feb_w = feb_arr.shape[:2]
    print(f"\nFebruary section: {feb_w}x{feb_h}")

    # Find colored pixels (non-white, non-text)
    # White: R>240, G>240, B>240
    # Yellow (Teacher Workday): high R, high G, low B
    # Blue (Holiday): low R, low G, high B

    # Let's scan the entire February image for colored pixels
    print("\nScanning for colored pixels in February section...")

    # Create masks for different colors
    yellow_mask = (feb_arr[:,:,0] > 200) & (feb_arr[:,:,1] > 200) & (feb_arr[:,:,2] < 150)
    blue_mask = (feb_arr[:,:,2] > feb_arr[:,:,0] + 20) & (feb_arr[:,:,2] > feb_arr[:,:,1] + 20) & (feb_arr[:,:,2] > 100)

    yellow_pixels = np.sum(yellow_mask)
    blue_pixels = np.sum(blue_mask)

    print(f"Yellow pixels found: {yellow_pixels}")
    print(f"Blue pixels found: {blue_pixels}")

    # Find the bounding boxes of colored regions
    if yellow_pixels > 0:
        yellow_coords = np.where(yellow_mask)
        print(f"Yellow region Y range: {yellow_coords[0].min()} to {yellow_coords[0].max()}")
        print(f"Yellow region X range: {yellow_coords[1].min()} to {yellow_coords[1].max()}")

    if blue_pixels > 0:
        blue_coords = np.where(blue_mask)
        print(f"Blue region Y range: {blue_coords[0].min()} to {blue_coords[0].max()}")
        print(f"Blue region X range: {blue_coords[1].min()} to {blue_coords[1].max()}")

    # Create a visualization showing colored regions
    vis_arr = feb_arr.copy()
    vis_arr[yellow_mask] = [255, 0, 255]  # Magenta overlay for yellow regions
    vis_arr[blue_mask] = [0, 255, 0]  # Green overlay for blue regions

    vis_img = Image.fromarray(vis_arr)
    vis_img.save(output_dir / "feb_color_overlay.png")
    print(f"\nSaved color overlay to: {output_dir / 'feb_color_overlay.png'}")
    print("(Yellow areas shown as magenta, Blue areas shown as green)")


if __name__ == "__main__":
    analyze_calendar()

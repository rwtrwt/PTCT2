#!/usr/bin/env python3
"""
Extract and analyze the actual pixel color of Feb 13 in the calendar.
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


def analyze_specific_dates():
    """Extract pixel colors from specific date cells."""
    print("Converting PDF at DPI 400...")
    images = convert_from_path(str(PDF_PATH), dpi=400, poppler_path='/opt/homebrew/bin')
    img = images[0]
    arr = np.array(img)

    height, width = arr.shape[:2]
    print(f"Image dimensions: {width}x{height}")

    # Based on the calendar layout, February is in the middle column
    # and the third row of months (Jan/Feb/Mar row)

    # February section approximate coordinates (at 400 DPI):
    # The calendar is roughly 2550 x 3300 at 300 DPI, so at 400 DPI it's ~3400 x 4400
    # February '26 header is around y=2300-2400 at 400 DPI
    # The date grid starts around y=2400

    # Looking at the cropped image, I can see:
    # Feb 13 is in the second row of dates, under "F" (Friday) column
    # Feb 16 is in the third row, under "M" (Monday) column
    # Feb 17 is in the third row, under "T" (Tuesday) column

    # Let me sample specific regions
    # First, let me save a high-res version for reference
    output_dir = PROJECT_ROOT / "scripts" / "test_images"
    output_dir.mkdir(exist_ok=True)

    # At 400 DPI, let me estimate February section location
    # February is middle column (roughly 1/3 to 2/3 of width)
    # Third row of months (roughly 52% to 68% of height based on 4 rows of months)

    feb_left = int(width * 0.36)
    feb_right = int(width * 0.64)
    feb_top = int(height * 0.55)
    feb_bottom = int(height * 0.68)

    # Crop February
    feb_section = img.crop((feb_left, feb_top, feb_right, feb_bottom))
    feb_section.save(output_dir / "feb_section_400dpi.png")
    print(f"Saved February section to: {output_dir / 'feb_section_400dpi.png'}")

    # Now let's analyze pixel colors from the February section
    feb_arr = np.array(feb_section)
    feb_h, feb_w = feb_arr.shape[:2]
    print(f"February section dimensions: {feb_w}x{feb_h}")

    # The February grid has 7 columns (S M T W T F S) and 5 rows
    # Feb 13 is at row 2 (0-indexed: 1), column 6 (Friday, 0-indexed: 5)
    # Feb 16 is at row 3 (0-indexed: 2), column 2 (Monday, 0-indexed: 1)
    # Feb 17 is at row 3 (0-indexed: 2), column 3 (Tuesday, 0-indexed: 2)

    # Estimate cell positions (row heights and column widths)
    # There's a header row for the month name and day labels
    header_height = feb_h * 0.20  # Top 20% for headers
    cell_height = (feb_h - header_height) / 5  # 5 rows of dates
    cell_width = feb_w / 7  # 7 columns

    def get_cell_color(row, col, name):
        """Get average color of a cell."""
        x_start = int(col * cell_width + cell_width * 0.2)
        x_end = int(col * cell_width + cell_width * 0.8)
        y_start = int(header_height + row * cell_height + cell_height * 0.2)
        y_end = int(header_height + row * cell_height + cell_height * 0.8)

        region = feb_arr[y_start:y_end, x_start:x_end]
        avg_color = np.mean(region, axis=(0, 1))

        # Classify the color
        r, g, b = avg_color
        if r > 240 and g > 240 and b > 240:
            color_type = "WHITE"
        elif r > 200 and g > 200 and b < 100:
            color_type = "YELLOW"
        elif b > r and b > g and b > 100:
            color_type = "BLUE"
        else:
            color_type = "OTHER"

        print(f"{name}: RGB({r:.0f}, {g:.0f}, {b:.0f}) = {color_type}")
        return avg_color, color_type

    print("\nAnalyzing specific date cells in February:")
    print("-" * 50)

    # Feb 13 - Row 1 (second row of dates, 0-indexed), Column 5 (Friday)
    get_cell_color(1, 5, "Feb 13")

    # Feb 16 - Row 2, Column 1 (Monday)
    get_cell_color(2, 1, "Feb 16")

    # Feb 17 - Row 2, Column 2 (Tuesday)
    get_cell_color(2, 2, "Feb 17")

    # Also check a known white cell for reference
    get_cell_color(1, 3, "Feb 11 (Wed, should be white)")

    # Check a known yellow cell - let's look at October
    print("\n\nFor reference, analyzing October '25 Teacher Workday cells:")
    print("-" * 50)

    # October is in the first column of the second row of months
    oct_left = int(width * 0.02)
    oct_right = int(width * 0.32)
    oct_top = int(height * 0.32)
    oct_bottom = int(height * 0.46)

    oct_section = img.crop((oct_left, oct_top, oct_right, oct_bottom))
    oct_section.save(output_dir / "oct_section_400dpi.png")

    oct_arr = np.array(oct_section)
    oct_h, oct_w = oct_arr.shape[:2]
    oct_header_height = oct_h * 0.20
    oct_cell_height = (oct_h - oct_header_height) / 5
    oct_cell_width = oct_w / 7

    def get_oct_cell_color(row, col, name):
        x_start = int(col * oct_cell_width + oct_cell_width * 0.2)
        x_end = int(col * oct_cell_width + oct_cell_width * 0.8)
        y_start = int(oct_header_height + row * oct_cell_height + oct_cell_height * 0.2)
        y_end = int(oct_header_height + row * oct_cell_height + oct_cell_height * 0.8)

        region = oct_arr[y_start:y_end, x_start:x_end]
        avg_color = np.mean(region, axis=(0, 1))

        r, g, b = avg_color
        if r > 240 and g > 240 and b > 240:
            color_type = "WHITE"
        elif r > 200 and g > 200 and b < 100:
            color_type = "YELLOW"
        elif b > r and b > g and b > 100:
            color_type = "BLUE"
        else:
            color_type = "OTHER"

        print(f"{name}: RGB({r:.0f}, {g:.0f}, {b:.0f}) = {color_type}")
        return avg_color, color_type

    # Oct 6 - Row 1, Column 1 (Monday) - should be yellow
    get_oct_cell_color(1, 1, "Oct 6 (Mon, Teacher Workday)")

    # Oct 13 - Row 2, Column 1 (Monday) - should be blue (holiday)
    get_oct_cell_color(2, 1, "Oct 13 (Mon, Holiday)")


if __name__ == "__main__":
    analyze_specific_dates()

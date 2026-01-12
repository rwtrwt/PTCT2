#!/usr/bin/env python3
"""
Improved AI Calendar Scanner (Claude/Anthropic Version)

Uses Claude's vision capabilities for accurate extraction of school calendar dates.
Multi-pass validation and cross-referencing with verified data patterns.

Run with: python scripts/improved_calendar_scanner.py [pdf_path]

Configuration:
    Set ANTHROPIC_API_KEY environment variable, or create a .env file with:
    ANTHROPIC_API_KEY=your_key_here
"""

import os
import sys
import json
import base64
import re
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# Add parent directory to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"  Loaded environment from {env_path}")
except ImportError:
    pass

import anthropic

# Target holidays to extract - ONLY these 7 types are valid
# (No Memorial Day - it's after school ends; No First/Last Day of School - those are school days)
TARGET_HOLIDAYS = [
    "Fall Break",           # September/October
    "Thanksgiving Break",   # November
    "Christmas Break",      # December-January
    "MLK Day",              # January (3rd Monday)
    "Winter Break",         # February (Presidents Day area)
    "March Break",          # March (between Winter Break and Spring Break)
    "Spring Break",         # March/April (must be 5+ consecutive days)
]

EXTRACTION_PROMPT = """You are an expert school calendar analyst. Extract student holidays and breaks from this Georgia school calendar.

## ONLY EXTRACT THESE 7 HOLIDAY TYPES:
1. **Fall Break** = Student days off in SEPTEMBER or OCTOBER (after Labor Day, before Thanksgiving)
2. **Thanksgiving Break** = NOVEMBER break (week of 4th Thursday in November)
3. **Christmas Break** = Long break at END OF DECEMBER into EARLY JANUARY (typically Dec 20-Jan 3)
4. **MLK Day** = Single day in mid-JANUARY (3rd Monday, around Jan 15-21)
5. **Winter Break** = FEBRUARY break (often around Presidents Day, Feb 13-20)
6. **March Break** = Single day or short break in MARCH between Winter Break and Spring Break
7. **Spring Break** = 5+ consecutive days off in late MARCH or APRIL (typically Apr 6-10 area)

## DO NOT EXTRACT:
- Memorial Day (it's after school ends)
- First Day of School (it's a school day, not a holiday)
- Last Day of School (it's a school day, not a holiday)
- Labor Day
- Any other holidays not in the 7 types above

## CRITICAL: INFER BREAK NAMES FROM TIMING
Many calendars label breaks generically as "Student Holiday" or "School Closed". YOU MUST INFER the correct break name based on WHEN it occurs using the 7 types above.

## NAMING RULES:
- Even if calendar says "Winter Break" in December → call it "Christmas Break"
- Even if calendar says "Student Holiday" → infer the name from the date
- "Presidents Day" area break → call it "Winter Break"
- Any break in February → "Winter Break" (not Christmas)

## TEACHER WORKDAYS = STUDENT HOLIDAYS (CRITICAL)
- "Teacher Workday", "Staff Development", "Professional Development", "Planning Day" = NO SCHOOL for students
- These ARE student holidays even though they have a different color in the legend
- IMPORTANT: When a Teacher Workday is adjacent to a Holiday (including across a weekend), COMBINE them into one break
- Example: If Feb 13 (Fri) is "Teacher Workday" and Feb 16 (Mon) is "Presidents Day Holiday" → Report as Winter Break Feb 13-17
- Look for Teacher Workdays on Fridays before holiday Mondays - they extend the break

## CONTINUOUS BREAKS (WEEKEND BRIDGING) - CRITICAL
- If Friday is a holiday/workday AND the following Monday is a holiday → treat as ONE continuous break
- The weekend is NOT a school day, so it naturally bridges adjacent days off
- ALWAYS check the Friday BEFORE any Monday holiday - it's often part of the break (may be marked as Teacher Workday)
- ALWAYS check the Monday/Tuesday AFTER any Friday holiday
- For EVERY break you find, scan the entire week (Mon-Fri) to find ALL days off

## WINTER BREAK (FEBRUARY)
- Winter Break is around Presidents Day (3rd Monday in February)
- ALWAYS check the Friday before Presidents Day - it's often a Teacher Workday that extends the break
- If the Friday before AND the Monday (Presidents Day) are both colored, combine them

## SPRING BREAK (MARCH/APRIL)
- Spring Break is 5 consecutive weekdays in late March or early April
- Look for a full week (Mon-Fri) of colored/shaded dates
- Usually first week of April for Georgia schools

## MERGING RULES:
- Merge ALL consecutive non-school days into single breaks
- Include teacher workdays that are adjacent to holidays
- Christmas Break should include any January student holidays immediately following

## COLOR-CODED CALENDARS (CRITICAL FOR VISION)
- Many calendars use colors/shading to mark holidays instead of text labels
- ALWAYS look at the COLOR KEY/LEGEND to understand what each color means
- Match colored/shaded dates to the holiday type from the key
- Common patterns: Yellow = holiday, Blue = teacher workday, Red = no school
- Count ALL shaded days of the same color as part of the same break

## SPRING BREAK VALIDATION:
- Spring Break MUST be 5+ consecutive days. If you only see 1-2 days in March/April, look harder for the full break period.
- Check for shaded/highlighted date ranges that might indicate the full break.

## REQUIRED OUTPUT FORMAT:
Return ONLY valid JSON with this exact structure:
{
    "school_name": "Name of school/district",
    "school_year": "YYYY-YYYY",
    "holidays": [
        {
            "name": "Holiday Name (MUST be one of the 7 types above)",
            "start_date": "YYYY-MM-DD",
            "end_date": "YYYY-MM-DD",
            "confidence": 0.95,
            "source_text": "Exact text from calendar that indicates this date"
        }
    ],
    "extraction_notes": "Any difficulties or ambiguities encountered"
}

## CONFIDENCE SCORING:
- 0.95-1.0: Clearly stated date with explicit holiday name
- 0.80-0.94: Date visible but required inference (e.g., shading indicates day off)
- 0.60-0.79: Ambiguous or partially visible
- Below 0.60: Uncertain, may need verification

## IMPORTANT:
- Use YYYY-MM-DD format for ALL dates
- Extract the SCHOOL YEAR from the calendar header (e.g., "2025-2026")
- Look for visual indicators: shaded cells, colored backgrounds, bold text
- Do NOT include weekends unless explicitly marked as extended break days

## FINAL CHECK - SCAN ALL COLORED DATES:
Before returning your answer, scan the calendar image and identify EVERY date that has ANY color/shading (not white).
For February specifically, check: Is Feb 13 colored? If YES, it's a no-school day and should be combined with Feb 16-17 for Winter Break.
Teacher Workday colors count as no-school days - combine them with adjacent holidays."""


class ImprovedCalendarScanner:
    def __init__(self):
        """Initialize scanner with Claude client."""
        self.client = None

        # Try environment variable
        api_key = os.environ.get("ANTHROPIC_API_KEY")

        if api_key:
            try:
                self.client = anthropic.Anthropic(api_key=api_key)
                print("  Claude client initialized from ANTHROPIC_API_KEY")
                return
            except Exception as e:
                print(f"  Warning: Failed to initialize Claude client: {e}")

        # Provide helpful message if no key found
        print("\n" + "="*60)
        print("ERROR: Anthropic API key not found!")
        print("="*60)
        print("\nTo use this scanner, you need to configure an Anthropic API key.")
        print("\nGet your API key at: https://console.anthropic.com/")
        print("\nOption 1: Set environment variable")
        print("  export ANTHROPIC_API_KEY='your-api-key-here'")
        print("\nOption 2: Create a .env file in the project root")
        print(f"  echo 'ANTHROPIC_API_KEY=your-api-key-here' > {PROJECT_ROOT}/.env")
        print("="*60 + "\n")

    def _merge_weekend_separated_holidays(self, holidays: List[Dict]) -> List[Dict]:
        """
        Merge holidays that are separated by only a weekend.
        E.g., if we have a holiday ending Friday and another starting Monday, merge them.
        """
        if not holidays:
            return holidays

        from datetime import timedelta

        # Sort by start date
        sorted_holidays = sorted(holidays, key=lambda h: h.get('start_date', ''))

        merged = []
        for h in sorted_holidays:
            try:
                start = datetime.strptime(h.get('start_date', ''), '%Y-%m-%d').date()
                end = datetime.strptime(h.get('end_date', ''), '%Y-%m-%d').date()
            except (ValueError, TypeError):
                merged.append(h)
                continue

            # Check if this can be merged with the previous holiday
            if merged:
                prev = merged[-1]
                try:
                    prev_end = datetime.strptime(prev.get('end_date', ''), '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    merged.append(h)
                    continue

                # Check if they're connected (consecutive days or weekend gap)
                days_gap = (start - prev_end).days

                # Merge if: same holiday type and gap is 1-3 days (accounts for weekend)
                if prev.get('name') == h.get('name') and 1 <= days_gap <= 3:
                    # Merge by extending the previous holiday's end date
                    prev['end_date'] = h.get('end_date')
                    prev['confidence'] = min(prev.get('confidence', 0.8), h.get('confidence', 0.8))
                    continue

                # Also merge if gap is exactly weekend (Friday to Monday = 3 days)
                # and both are same general break category
                if days_gap == 3 and prev_end.weekday() == 4 and start.weekday() == 0:
                    # Friday to Monday gap - merge if same break type
                    if prev.get('name') == h.get('name'):
                        prev['end_date'] = h.get('end_date')
                        continue

            merged.append(h)

        return merged

    def _verify_adjacent_days(self, image_bytes: bytes, holidays: List[Dict]) -> List[Dict]:
        """
        Pass 2: For each multi-day holiday, verify if adjacent days (Friday before Monday, Monday after Friday)
        are also colored and should extend the break.

        Single-day holidays (like MLK Day) are NOT extended.
        Only multi-day breaks are checked for adjacent colored days.
        """
        if not self.client or not image_bytes or not holidays:
            return holidays

        from datetime import timedelta

        verified = []
        for h in holidays:
            name = h.get('name', '')

            try:
                start = datetime.strptime(h.get('start_date', ''), '%Y-%m-%d').date()
                end = datetime.strptime(h.get('end_date', ''), '%Y-%m-%d').date()
            except (ValueError, TypeError):
                verified.append(h)
                continue

            # Only verify adjacent days for multi-day breaks or breaks that start/end on Mon/Fri
            duration = (end - start).days + 1

            new_start = start
            new_end = end

            # If holiday starts on Monday, check if Friday before is colored
            if start.weekday() == 0:  # Monday
                friday_before = start - timedelta(days=3)
                print(f"    Checking if {friday_before.strftime('%b %d')} is colored...")
                if self._is_date_colored(image_bytes, friday_before):
                    print(f"    -> YES, extending {name} start to {friday_before}")
                    new_start = friday_before

            # If holiday ends on Friday, check if Monday after is colored
            if end.weekday() == 4:  # Friday
                monday_after = end + timedelta(days=3)
                print(f"    Checking if {monday_after.strftime('%b %d')} is colored...")
                if self._is_date_colored(image_bytes, monday_after):
                    print(f"    -> YES, extending {name} end to {monday_after}")
                    new_end = monday_after

            # If we extended to Monday, also check Tuesday
            if new_end.weekday() == 0:  # Ends Monday, check Tuesday
                tuesday = new_end + timedelta(days=1)
                print(f"    Checking if {tuesday.strftime('%b %d')} is colored...")
                if self._is_date_colored(image_bytes, tuesday):
                    print(f"    -> YES, extending end to {tuesday}")
                    new_end = tuesday

            h['start_date'] = new_start.strftime('%Y-%m-%d')
            h['end_date'] = new_end.strftime('%Y-%m-%d')
            verified.append(h)

        return verified

    def _is_date_colored(self, image_bytes: bytes, check_date: date) -> bool:
        """
        Ask Claude if a specific date cell is colored (not white) on the calendar.
        Uses explicit YES/NO format for reliable detection.
        """
        if not self.client:
            return False

        base64_image = base64.standard_b64encode(image_bytes).decode("utf-8")

        # Format the date for the prompt
        month_name = check_date.strftime("%B")
        day = check_date.day
        day_of_week = check_date.strftime("%A")

        prompt = f"""Look at this school calendar image. Find {month_name} {day} ({day_of_week}).

Is the cell for {month_name} {day} colored or shaded (any color that is NOT white/plain)?

Answer ONLY with: YES or NO"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=10,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64_image}},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )

            answer = response.content[0].text.strip().upper()
            return answer.startswith("YES")

        except Exception as e:
            print(f"    Error checking date {check_date}: {e}")
            return False

    def pdf_to_images(self, pdf_path: str) -> List[bytes]:
        """Convert PDF pages to images for vision analysis."""
        try:
            from pdf2image import convert_from_path
            import io

            # Explicitly set poppler path for macOS Homebrew installation
            # Use higher DPI (200) for better color detection
            images = convert_from_path(pdf_path, dpi=200, poppler_path='/opt/homebrew/bin')
            image_bytes_list = []

            for img in images:
                buffer = io.BytesIO()
                img.save(buffer, format='PNG')
                image_bytes_list.append(buffer.getvalue())

            return image_bytes_list
        except Exception as e:
            print(f"  Error converting PDF to images: {e}")
            return []

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text from PDF using pdfplumber."""
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text(x_tolerance=3, y_tolerance=3)
                    if text:
                        text_parts.append(text)
            return "\n\n".join(text_parts)
        except Exception as e:
            print(f"  Error extracting text: {e}")
            return ""

    def analyze_with_vision(self, image_bytes_list: List[bytes], school_year: str = None) -> Dict:
        """Analyze calendar images with Claude's vision."""
        if not self.client:
            return {"error": "Claude client not initialized"}

        if not image_bytes_list:
            return {"error": "No images to analyze"}

        prompt = EXTRACTION_PROMPT
        if school_year:
            prompt += f"\n\nNote: This calendar is for the {school_year} school year."

        # Build content with images
        content = []
        for i, img_bytes in enumerate(image_bytes_list[:5]):  # Limit to 5 pages
            base64_image = base64.standard_b64encode(img_bytes).decode("utf-8")
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64_image
                }
            })

        content.append({
            "type": "text",
            "text": """Extract holidays using this step-by-step process:

STEP 1: Scan the calendar and list ALL colored/shaded dates (any color that isn't white).

STEP 2: For each colored date, note what day of week it is (Mon-Fri).

STEP 3: COMBINE dates into breaks using these rules:
- If a Friday is colored AND the following Monday is colored → combine them (weekend bridges them)
- If a Monday is colored AND the Friday before was colored → combine them
- Teacher Workdays adjacent to holidays extend the holiday

STEP 4: Name each combined break (Fall Break, Thanksgiving Break, Christmas Break, MLK Day, Winter Break, March Break, Spring Break).

STEP 5: Return ONLY the final JSON with the combined breaks."""
        })

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[
                    {"role": "user", "content": content}
                ],
                system=prompt
            )

            # Extract text from response
            response_text = response.content[0].text

            # Try to parse JSON from response - multiple strategies
            # Strategy 1: Look for markdown code blocks
            json_match = re.search(r'```(?:json)?\s*(.*?)```', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(1)

            # Strategy 2: Find JSON object boundaries
            if not response_text.strip().startswith('{'):
                start = response_text.find('{')
                if start != -1:
                    # Find matching closing brace
                    depth = 0
                    end = start
                    for i, c in enumerate(response_text[start:], start):
                        if c == '{':
                            depth += 1
                        elif c == '}':
                            depth -= 1
                            if depth == 0:
                                end = i + 1
                                break
                    response_text = response_text[start:end]

            return json.loads(response_text.strip())

        except json.JSONDecodeError as e:
            print(f"  JSON parsing error: {e}")
            # Try one more extraction attempt
            try:
                # Find any JSON-like structure
                json_match = re.search(r'\{[\s\S]*"holidays"[\s\S]*\}', response_text)
                if json_match:
                    return json.loads(json_match.group(0))
            except:
                pass
            return {"error": "Failed to parse response as JSON"}
        except Exception as e:
            print(f"  Vision analysis error: {e}")
            return {"error": str(e)}

    def analyze_with_text(self, text: str, school_year: str = None) -> Dict:
        """Analyze extracted text with Claude (fallback if vision fails)."""
        if not self.client:
            return {"error": "Claude client not initialized"}

        prompt = EXTRACTION_PROMPT
        if school_year:
            prompt += f"\n\nNote: This calendar is for the {school_year} school year."

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[
                    {"role": "user", "content": f"Extract all holidays from this school calendar text:\n\n{text}\n\nReturn ONLY valid JSON."}
                ],
                system=prompt
            )

            response_text = response.content[0].text

            # Handle markdown code blocks
            json_match = re.search(r'```(?:json)?\s*(.*?)```', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(1)

            # Find JSON object boundaries if needed
            if not response_text.strip().startswith('{'):
                start = response_text.find('{')
                if start != -1:
                    depth = 0
                    end = start
                    for i, c in enumerate(response_text[start:], start):
                        if c == '{':
                            depth += 1
                        elif c == '}':
                            depth -= 1
                            if depth == 0:
                                end = i + 1
                                break
                    response_text = response_text[start:end]

            return json.loads(response_text.strip())

        except json.JSONDecodeError as e:
            print(f"  JSON parsing error: {e}")
            try:
                json_match = re.search(r'\{[\s\S]*"holidays"[\s\S]*\}', response_text)
                if json_match:
                    return json.loads(json_match.group(0))
            except:
                pass
            return {"error": "Failed to parse response"}
        except Exception as e:
            print(f"  Text analysis error: {e}")
            return {"error": str(e)}

    def validate_extraction(self, extracted: Dict, school_year: str) -> Dict:
        """Validate extracted data against known patterns."""
        if not school_year or '-' not in school_year:
            return {"valid": True, "corrections": [], "validation_notes": "Could not validate - missing school year"}

        years = school_year.split('-')
        fall_year = int(years[0])
        spring_year = int(years[1]) if len(years[1]) == 4 else int(f"20{years[1]}")

        holidays = extracted.get('holidays', [])
        corrections = []
        issues = []

        for h in holidays:
            name = h.get('name', '')
            start = h.get('start_date', '')
            end = h.get('end_date', '')

            if not start:
                continue

            try:
                start_date = datetime.strptime(start, '%Y-%m-%d')
                start_month = start_date.month
                start_year = start_date.year

                # Validate date logic
                if 'Fall Break' in name and start_month != 10:
                    issues.append(f"Fall Break should be in October, got month {start_month}")
                elif 'Thanksgiving' in name and start_month != 11:
                    issues.append(f"Thanksgiving should be in November, got month {start_month}")
                elif 'Christmas' in name and start_month not in [12, 1]:
                    issues.append(f"Christmas Break should be Dec/Jan, got month {start_month}")
                elif 'MLK' in name and start_month != 1:
                    issues.append(f"MLK Day should be in January, got month {start_month}")
                elif 'Winter Break' in name and 'Christmas' not in name and start_month != 2:
                    issues.append(f"Winter Break (Feb) should be in February, got month {start_month}")
                elif 'Spring Break' in name and start_month not in [3, 4]:
                    issues.append(f"Spring Break should be March/April, got month {start_month}")

                # Validate year consistency
                if start_month >= 8:  # Fall semester
                    if start_year != fall_year:
                        issues.append(f"{name} has year {start_year}, expected {fall_year}")
                else:  # Spring semester
                    if start_year != spring_year:
                        issues.append(f"{name} has year {start_year}, expected {spring_year}")

            except ValueError:
                issues.append(f"Invalid date format for {name}: {start}")

        # Check for missing expected holidays
        found_names = [h.get('name', '').lower() for h in holidays]
        expected = ['fall break', 'thanksgiving', 'christmas', 'mlk', 'spring break']
        missing = []
        for exp in expected:
            if not any(exp in n for n in found_names):
                missing.append(exp.title())

        return {
            "valid": len(issues) == 0,
            "corrections": [{"issue": i} for i in issues],
            "missing_holidays": missing,
            "validation_notes": f"Found {len(holidays)} holidays. {len(issues)} issues detected."
        }

    def scan_calendar(self, pdf_path: str, school_year: str = None) -> Dict:
        """
        Main scanning function - multi-pass extraction with validation.

        Returns dict with:
        - holidays: list of extracted holidays
        - school_name: detected school name
        - school_year: detected or provided school year
        - confidence_avg: average confidence across all holidays
        - validation: validation results
        """
        print(f"Scanning: {pdf_path}")

        # Detect school year from filename if not provided
        if not school_year:
            year_match = re.search(r'20(\d{2})\s*[-–]?\s*20?(\d{2})', os.path.basename(pdf_path))
            if year_match:
                y1, y2 = year_match.groups()
                school_year = f"20{y1}-20{y2}"
                print(f"  Detected school year from filename: {school_year}")

        # Pass 1: Convert PDF to images
        print("  Pass 1: Converting PDF to images...")
        images = self.pdf_to_images(pdf_path)
        first_image = images[0] if images else None  # Keep for pass 2 verification

        result = None

        # Pass 2: Try vision analysis first (best accuracy)
        if images:
            print(f"  Pass 2: Vision analysis ({len(images)} pages)...")
            result = self.analyze_with_vision(images, school_year)

        # Pass 3: Fallback to text extraction if vision failed
        if not result or "error" in result:
            print("  Pass 3: Falling back to text extraction...")
            text = self.extract_text_from_pdf(pdf_path)

            if not text:
                return {"error": "Could not extract content from PDF", "source_file": os.path.basename(pdf_path)}

            # Detect school year from text if still not found
            if not school_year:
                year_match = re.search(r'20(\d{2})\s*[-–]\s*20?(\d{2})', text)
                if year_match:
                    y1, y2 = year_match.groups()
                    school_year = f"20{y1}-20{y2}"
                    print(f"  Detected school year from text: {school_year}")

            result = self.analyze_with_text(text, school_year)

        if "error" in result:
            return {"error": result["error"], "source_file": os.path.basename(pdf_path)}

        # Pass 4: Validation and filtering
        print("  Pass 4: Validation...")
        detected_year = result.get('school_year', school_year)
        validation = self.validate_extraction(result, detected_year) if detected_year else {}

        # Post-processing: Filter and merge holidays
        holidays = result.get('holidays', [])

        # First, merge any holidays that are separated by only a weekend
        holidays = self._merge_weekend_separated_holidays(holidays)

        # Pass 5: Verify adjacent days (check Friday before Monday holidays, etc.)
        if first_image and holidays:
            print("  Pass 5: Verifying adjacent days...")
            holidays = self._verify_adjacent_days(first_image, holidays)

        filtered_holidays = []
        today = date.today()

        for h in holidays:
            name = h.get('name', '')
            start_str = h.get('start_date', '')
            end_str = h.get('end_date', '')

            # Filter 1: Only allow valid holiday types
            if name not in TARGET_HOLIDAYS:
                continue

            # Filter 2: Skip past dates
            try:
                start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
                if start_date < today:
                    continue
            except (ValueError, TypeError):
                continue

            # Filter 3: Spring Break must be 5+ days
            if name == "Spring Break":
                try:
                    end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
                    duration = (end_date - start_date).days + 1
                    if duration < 5:
                        # Flag as potentially incomplete
                        h['confidence'] = min(h.get('confidence', 0.8), 0.6)
                        h['extraction_notes'] = f"Spring Break only {duration} days - may be incomplete"
                except:
                    pass

            filtered_holidays.append(h)

        # Calculate average confidence
        if filtered_holidays:
            avg_conf = sum(h.get('confidence', 0.8) for h in filtered_holidays) / len(filtered_holidays)
        else:
            avg_conf = 0.0

        return {
            "school_name": result.get('school_name'),
            "school_year": detected_year,
            "holidays": filtered_holidays,
            "confidence_avg": round(avg_conf, 3),
            "validation": validation,
            "source_file": os.path.basename(pdf_path)
        }


def main():
    """Test scanner on a sample PDF."""
    if len(sys.argv) < 2:
        # Default: scan a sample calendar
        sample_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'Official_Calendars', 'Public', 'Bibb'
        )

        if os.path.exists(sample_dir):
            pdfs = [f for f in os.listdir(sample_dir) if f.endswith('.pdf')]
            if pdfs:
                pdf_path = os.path.join(sample_dir, pdfs[0])
            else:
                print("No PDFs found in sample directory")
                return
        else:
            print(f"Sample directory not found: {sample_dir}")
            print("Usage: python improved_calendar_scanner.py <pdf_path>")
            return
    else:
        pdf_path = sys.argv[1]

    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        return

    scanner = ImprovedCalendarScanner()

    if not scanner.client:
        return

    result = scanner.scan_calendar(pdf_path)

    print("\n" + "=" * 60)
    print("EXTRACTION RESULTS")
    print("=" * 60)
    print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    main()

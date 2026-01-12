# Output Format Test Results for Butts County Calendar

## Problem Statement
Claude sometimes misses Feb 13 when extracting holidays from the Butts County calendar, even though it can see the date is colored when asked directly.

## Expected Results
- MLK Day: 2026-01-19
- Winter Break: 2026-02-13 to 2026-02-17 (includes Teacher Workday on Feb 13)
- Spring Break: 2026-04-06 to 2026-04-10

## Test Formats and Results

### Round 1 - Basic Format Variations

| Format | Accuracy | Feb 13 Found? | Winter Break Extracted |
|--------|----------|---------------|------------------------|
| 1. Markdown Table First | 67% | No | 2026-02-16 to 2026-02-16 |
| 2. Step by Step Reasoning | 67% | No | 2026-02-16 to 2026-02-17 |
| 3. Simple List First | 33% | No | 2026-02-16 to 2026-02-17 |

**Notes:**
- All three formats explicitly stated "Feb 13 is not colored" or "Feb 13 appears white"
- The markdown table approach did enumerate dates but still missed Feb 13

### Round 2 - Enhanced Verification Approaches

| Format | Accuracy | Feb 13 Found? | Winter Break Extracted |
|--------|----------|---------------|------------------------|
| 4. Two-Pass Enumeration | 33% | No | 2026-02-16 to 2026-02-17 |
| 5. Direct Verification | 67% | No | 2026-02-16 to 2026-02-16 |
| 6. XML Structured | 67% | No | 2026-02-16 to 2026-02-17 |
| 7. Row-by-Row Reading | 67% | No | 2026-02-16 to 2026-02-17 |

**Notes:**
- Even explicit "Is Feb 13 colored?" questions returned "NO"
- Row-by-row reading did not improve detection

### Round 3 - Perception-First Approaches

| Format | Accuracy | Feb 13 Found? | Winter Break Extracted |
|--------|----------|---------------|------------------------|
| 8. Color-First Description | 67% | No | 2025-12-22 to 2026-01-05 (confused with Christmas) |
| 9. Negative Verification | 67% | **YES** | 2026-02-13 to 2026-02-16 (missed Feb 17) |
| 10. Explicit Cell Check (YES/NO) | **100%** | **YES** | **2026-02-13 to 2026-02-17** |
| 11. Known Fact Verification | 67% | Misidentified as Red | Invalid dates |

## Winner: Format 10 - Explicit Cell Check (Forced YES/NO)

### Why It Works
The explicit cell check format forces Claude to:
1. Answer YES/NO for each specific date - no skipping allowed
2. Report the color it sees for each cell
3. Process cells individually before combining into date ranges

### Actual Response for Format 10
```
Feb 9 (Mon): NO (white)
Feb 10 (Tue): NO (white)
Feb 11 (Wed): NO (white)
Feb 12 (Thu): NO (white)
Feb 13 (Fri): YES (blue)
Feb 14 (Sat): NO (white)
Feb 15 (Sun): NO (white)
Feb 16 (Mon): YES (blue)
Feb 17 (Tue): YES (yellow)
Feb 18 (Wed): NO (white)
```

**Interesting:** Format 10 reported Feb 13 as **blue**, while Format 9 also found Feb 13 but called it **blue** (Holiday), and Format 11 called it **red** (First Day of Semester). The actual calendar shows it as **yellow** (Teacher Workday).

## Key Insights

1. **Enumeration alone is not enough** - Formats that asked Claude to list all colored dates still missed Feb 13 in initial enumeration.

2. **Forced YES/NO per cell works best** - When Claude must answer YES or NO for each specific date, it examines cells more carefully.

3. **Color identification varies** - Claude sometimes misidentified the color of Feb 13 (blue vs yellow), but the key is that it recognized it was NOT white.

4. **Interpretation interferes with perception** - When Claude is asked to extract "holidays" directly, it may skip cells that don't match its mental model of what a holiday looks like. Separating perception from interpretation helps.

5. **Negative verification helps** - Asking "which dates are NOT colored" (Format 9) also caught Feb 13, though it missed Feb 17 in the final range calculation.

## Recommended Prompt Pattern

```
For [MONTH YEAR] in this calendar, answer YES or NO for each date:

[Date 1]: Is the cell colored (any color other than white)?
[Date 2]: Is the cell colored?
...

ANSWER FORMAT: [Date]: YES (color) or NO (white)

After checking each cell, combine adjacent colored weekdays into breaks.
Weekend between colored Friday and Monday = one continuous break.
```

## Implementation Recommendation

Update `improved_calendar_scanner.py` to use a two-phase extraction:

1. **Phase 1 - Cell Detection**: For each month, explicitly check each weekday cell for color (YES/NO format)
2. **Phase 2 - Range Calculation**: Combine adjacent colored weekdays into date ranges

This separates the perception task (is this colored?) from the interpretation task (what holiday is this?).

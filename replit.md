# Georgia Parenting Time Calendar Tool

## Overview
This Flask-based web application calculates parenting time percentages for Georgia family law cases, generates calendar visualizations from custody schedules, and offers advanced document analysis for parenting plans. Its core purpose is to streamline legal processes, ensure compliance, and assist with audit report generation, providing a comprehensive tool for legal professionals.

## User Preferences
I prefer iterative development with a focus on clear communication. Please ask for clarification if any instructions are unclear. I value detailed explanations for complex features or architectural decisions. Do not make changes to the `auth.py`, `payments.py`, `models.py`, `config.py`, or `extensions.py` files without explicit approval.

## System Architecture

### UI/UX Decisions
The application features a modern, responsive design with a clean, card-based UI and a clear navigation structure. Key UI elements include a circular profile dropdown for logged-in users, an admin-only date override toggle for testing, and a comprehensive footer. Calendar visualizations use distinct cell backgrounds for Parent A (white) and Parent B (grey) and are optimized for print with stacked months and dual-precision percentage displays. AI-adjusted fields are highlighted with a pulse animation. Legal and SEO-focused pages (Privacy Policy, Terms of Service, Contact, Sitemap) have been added, along with a Georgia Parenting Time Definition box, Methodology Transparency section, and a comprehensive FAQ.

### Technical Implementations
The core is a Flask application using Blueprint separation. PostgreSQL is used for data storage, managed with Flask-SQLAlchemy and Flask-Migrate. User authentication is handled via Flask-Login. Stripe is integrated for subscription management. AI capabilities, primarily for document analysis, date correction, school calendar extraction, and audit report generation, leverage OpenAI (via Replit AI Integrations or direct API). A guest access system tracks unauthenticated users via IP-based tokens, linking data upon registration. Calendar configurations can be saved, managed, and retrieved. PDF processing utilizes `pdfplumber` for native text extraction and `pytesseract` for OCR.

### Feature Specifications

#### Calendar Generation
The tool supports various weekly schedules (first-third, second-fourth, alternating, every weekend), configurable recurring daytime periods, and comprehensive handling of breaks (Spring, Fall, Thanksgiving, Christmas, Winter) including split breaks and even/odd year assignments. Holiday and summer schedules are also configurable by year. Calendar layering applies rules in a specific order: Weekly -> Daytime -> Breaks -> Holidays -> Summer -> Cell backgrounds -> Totals.

#### School Calendar Extractor
This AI-powered feature extracts holiday and break dates from uploaded school calendar PDFs OR images (PNG, JPG, JPEG) using OpenAI. For PDF files, it employs a two-pass extraction process (raw AI extraction followed by Python logic for merging and normalization).

**Image Analysis Pipeline (Dec 2025 - OCR+AI Approach):**
For image files (PNG, JPG), the system uses a two-stage OCR+AI pipeline that is more reliable than Vision API for date extraction:

1. **Stage 1 - OCR Text Extraction:** Uses Tesseract (pytesseract) with image preprocessing (grayscale, denoising, adaptive thresholding) to extract all text from the calendar image. This reliably captures footer annotations like "5-8 - Fall Break" and "22-26 - Thanksgiving Break".

2. **Stage 2 - AI Text Interpretation:** The extracted OCR text is sent to GPT-4o with a specialized prompt that:
   - Parses date annotations EXACTLY as written (e.g., "5-8" = Oct 5-8, NOT Oct 5-11)
   - Includes explicit WRONG/RIGHT examples to prevent AI misreading
   - Identifies the month context for each annotation
   - Marks teacher workdays as student days off when "students do not report"

3. **Stage 3 - Python Merge Logic:** Post-processes raw dates to:
   - Merge adjacent dates (e.g., Oct 4 teacher workday + Oct 5-8 Fall Break = Oct 4-8 Fall Break)
   - Apply Georgia-specific naming conventions
   - Handle month boundary crossings (Dec-Jan for Christmas Break)

**Georgia-Specific Naming Conventions:**
- December breaks = "Christmas Break" (even if source says "Winter Break")
- February breaks = "Winter Break" (even if source says "February Break")
- October multi-day breaks = "Fall Break"
- November multi-day breaks = "Thanksgiving Break"

**Teacher Workday Handling:**
Teacher Workdays / Professional Development days where "Students do not report" are treated as student days off and merged with adjacent breaks. Detection triggers:
- Category = "teacher_day" or "teacher_planning"
- Notes contain "students do not report"
- Label contains "workday" or "work day"

**Thanksgiving Fallback (Dec 2025):**
If OCR fails to extract Thanksgiving Break (common due to garbled text), the system infers dates from the school year:
- Calculates 4th Thursday of November
- Creates Mon-Fri break range (e.g., Nov 22-26 for 2027)
- Marks as "Inferred from school year (OCR may have missed this)"

**Merge Rules for Adjacent Dates:**
- Gap ≤ 1 day: Always merge
- Gap ≤ 3 days with weekend: Merge if Friday→Monday or similar pattern
- Month boundary: Merge if end of month→start of next month (e.g., Dec 31→Jan 3)
- Prefer "break" labels over "teacher workday" labels when naming merged entries

Both methods include specific rules for classifying breaks (e.g., Christmas, Winter, Fall) and critical logic for Christmas break extension into January. For complex PDFs, it supplements text extraction with visual shading detection, using weekend-aware gap bridging. Strict rules ensure accurate date range boundary interpretation and exclusion of non-student holidays (e.g., "Teacher Planning," "Independent Learning Days"). The system includes logic to handle ongoing breaks and deduplicate Fall Break entries. An Admin Calendar Database, with `SchoolEntity` and `SchoolCalendar` models, stores uploaded calendars and analysis results, supported by an Admin GUI for full management.

#### Document Analyzer (Parenting Plan Analyzer)
AI analyzes uploaded PDF parenting plans to populate forms, apply date correction rules (e.g., "Spring Break starts 1 day before school's scheduled date"), and auto-populate split break fields. This feature is gated until school calendar data is available and includes comprehensive value normalization.

**Premium Feature Gating (Jan 2026):**
The Parenting Plan Analyzer is now exclusive to Premium Attorney Plan subscribers ($19.84/month). Free users and guests see a disabled overlay with a "Subscribe to Premium Attorney Plan" button directing them to the subscription page. The backend `/analyze_document` endpoint also enforces this restriction.

**Free User Branding:**
For free users (non-subscribers), the firm branding displays: "Georgia Parenting Time Calendar Tool Developed by Russell Taylor, Georgia Divorce Attorney. parentingtimecalendartool.com". Premium subscribers can customize this via their `custom_h4` profile setting.

#### Drafting Audit Report
Generates detailed audit reports for parenting plans, identifying novel provisions, ambiguities, drafting errors, omissions, and areas for clarity, with categorized findings and suggested revisions.

#### Documentation & SEO
The application includes a User Guide and Technical Documentation. Legal pages (Privacy Policy, Terms of Service, Contact) and SEO enhancements (sitemap, robots.txt, meta tags, structured data) are implemented. A "How Georgia Counts Parenting Time Days" pillar page and embedded FAQ sections provide legal context and optimize for search.

## External Dependencies
- **Flask Ecosystem:** Flask, Flask-Login, Flask-Mail, Flask-SQLAlchemy, Flask-Migrate
- **PDF Processing:** `pdfplumber`, `pytesseract`, `pdf2image`, `Pillow`
- **AI Integration:** `openai` (via Replit AI Integrations)
- **Payment Processing:** `stripe`
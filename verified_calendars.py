"""
Verified School Calendar Data Store

Pre-verified holiday dates for Georgia school systems.
When a calendar is uploaded, we check against these known schools first
to avoid unnecessary AI analysis.

Auto-generated from: Georgia Private and Public School Calendars.csv
"""

import re
from typing import Optional, List, Dict
from datetime import date, timedelta

# Normalized school names (lowercase) mapped to display names
VERIFIED_SCHOOLS = {
    "baldwin county schools": "Baldwin County Schools",
    "barrow county school system": "Barrow County School System",
    "cherokee county school district": "Cherokee County School District",
    "clarke county school district": "Clarke County School District",
    "clayton county public schools": "Clayton County Public Schools",
    "cobb county school district": "Cobb County School District",
    "dawson county schools": "Dawson County Schools",
    "dekalb county school district": "Dekalb County School District",
    "douglas county school system": "Douglas County School System",
    "forsyth county schools": "Forsyth County Schools",
    "fulton county schools": "Fulton County Schools",
    "greater atlanta christian school": "Greater Atlanta Christian School",
    "greene county school system": "Greene County School System",
    "gwinnett county public schools": "Gwinnett County Public Schools",
    "hall county schools": "Hall County Schools",
    "hancock county schools": "Hancock County Schools",
    "henry county schools": "Henry County Schools",
    "houston county school district": "Houston County School District",
    "jackson county school system": "Jackson County School System",
    "jasper county charter system": "Jasper County Charter System",
    "jones county school system": "Jones County School System",
    "lumpkin county school system": "Lumpkin County School System",
    "madison county school system": "Madison County School System",
    "morgan county charter schools": "Morgan County Charter Schools",
    "newton county schools": "Newton County Schools",
    "oconee county schools": "Oconee County Schools",
    "oglethorpe county schools": "Oglethorpe County Schools",
    "putnam county charter school system": "Putnam County Charter School System",
    "rockdale county public schools": "Rockdale County Public Schools",
    "walton county school district": "Walton County School District",
    "washington county schools": "Washington County Schools",
    "wilkinson county schools": "Wilkinson County Schools",
}

# County name keywords for fuzzy matching
COUNTY_KEYWORDS = {
    "baldwin": "baldwin county schools",
    "barrow": "barrow county school system",
    "cherokee": "cherokee county school district",
    "clarke": "clarke county school district",
    "clayton": "clayton county public schools",
    "cobb": "cobb county school district",
    "dawson": "dawson county schools",
    "dekalb": "dekalb county school district",
    "douglas": "douglas county school system",
    "forsyth": "forsyth county schools",
    "fulton": "fulton county schools",
    "greater atlanta christian": "greater atlanta christian school",
    "greene": "greene county school system",
    "gwinnett": "gwinnett county public schools",
    "hall": "hall county schools",
    "hancock": "hancock county schools",
    "henry": "henry county schools",
    "houston": "houston county school district",
    "jackson": "jackson county school system",
    "jasper": "jasper county charter system",
    "jones": "jones county school system",
    "lumpkin": "lumpkin county school system",
    "madison": "madison county school system",
    "morgan": "morgan county charter schools",
    "newton": "newton county schools",
    "oconee": "oconee county schools",
    "oglethorpe": "oglethorpe county schools",
    "putnam": "putnam county charter school system",
    "rockdale": "rockdale county public schools",
    "walton": "walton county school district",
    "washington": "washington county schools",
    "wilkinson": "wilkinson county schools",
}

# Verified holiday data organized by school year, then by school
VERIFIED_HOLIDAYS = {
    "2025-2026": {
        "baldwin county schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-13", "endDate": "2026-02-16"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "barrow county school system": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-13", "endDate": "2026-02-13"},
            {"name": "March Break", "startDate": "2026-03-13", "endDate": "2026-03-16"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "cherokee county school district": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-20"},
            {"name": "March Break", "startDate": "2026-03-13", "endDate": "2026-03-13"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "clarke county school district": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-16"},
            {"name": "March Break", "startDate": "2026-03-12", "endDate": "2026-03-13"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "clayton county public schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-20"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "cobb county school district": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-20"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "dawson county schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-17"},
            {"name": "March Break", "startDate": "2026-03-13", "endDate": "2026-03-13"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "dekalb county school district": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-20"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "douglas county school system": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-20"},
            {"name": "March Break", "startDate": "2026-03-09", "endDate": "2026-03-09"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "forsyth county schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-13", "endDate": "2026-02-17"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "fulton county schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-17"},
            {"name": "March Break", "startDate": "2026-03-16", "endDate": "2026-03-16"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "greater atlanta christian school": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-20"},
            {"name": "March Break", "startDate": "2026-03-09", "endDate": "2026-03-09"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "greene county school system": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-17", "endDate": "2026-02-20"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "gwinnett county public schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-12", "endDate": "2026-02-16"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "hall county schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-17"},
            {"name": "March Break", "startDate": "2026-03-20", "endDate": "2026-03-20"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "hancock county schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-13", "endDate": "2026-02-16"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "henry county schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-20"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "houston county school district": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-16"},
            {"name": "Spring Break", "startDate": "2026-03-30", "endDate": "2026-04-06"},
        ],
        "jackson county school system": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-16"},
            {"name": "March Break", "startDate": "2026-03-13", "endDate": "2026-03-13"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "jasper county charter system": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-13", "endDate": "2026-02-17"},
            {"name": "March Break", "startDate": "2026-03-16", "endDate": "2026-03-16"},
            {"name": "Spring Break", "startDate": "2026-03-30", "endDate": "2026-04-03"},
        ],
        "jones county school system": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-16"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "lumpkin county school system": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-20"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "madison county school system": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-16"},
            {"name": "March Break", "startDate": "2026-03-13", "endDate": "2026-03-13"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "morgan county charter schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-17"},
            {"name": "March Break", "startDate": "2026-03-13", "endDate": "2026-03-13"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "newton county schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-17"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "oconee county schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-13", "endDate": "2026-02-16"},
            {"name": "March Break", "startDate": "2026-03-16", "endDate": "2026-03-16"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "oglethorpe county schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-20"},
            {"name": "March Break", "startDate": "2026-03-13", "endDate": "2026-03-13"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "putnam county charter school system": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-13", "endDate": "2026-02-16"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "rockdale county public schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-17", "endDate": "2026-02-20"},
            {"name": "March Break", "startDate": "2026-03-27", "endDate": "2026-03-27"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "walton county school district": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-16"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "washington county schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-16", "endDate": "2026-02-16"},
            {"name": "March Break", "startDate": "2026-03-13", "endDate": "2026-03-13"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
        "wilkinson county schools": [
            {"name": "MLK Day", "startDate": "2026-01-19", "endDate": "2026-01-19"},
            {"name": "Winter Break", "startDate": "2026-02-19", "endDate": "2026-02-20"},
            {"name": "Spring Break", "startDate": "2026-04-06", "endDate": "2026-04-10"},
        ],
    },
    "2026-2027": {
        "baldwin county schools": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-05", "endDate": "2026-10-09"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-12", "endDate": "2027-02-15"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "barrow county school system": [
            {"name": "Labor Day", "startDate": "2026-09-04", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-05", "endDate": "2026-10-09"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-05"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-12", "endDate": "2027-02-15"},
            {"name": "March Break", "startDate": "2027-03-12", "endDate": "2027-03-12"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "cherokee county school district": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-09-21", "endDate": "2026-09-25"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-19"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "clarke county school district": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-15", "endDate": "2026-10-19"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-01"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-15"},
            {"name": "March Break", "startDate": "2027-03-11", "endDate": "2027-03-12"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "clayton county public schools": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-12", "endDate": "2026-10-16"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-19"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "cobb county school district": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-09-21", "endDate": "2026-09-25"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-19"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "dawson county schools": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-09-28", "endDate": "2026-10-02"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-05"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-16"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "dekalb county school district": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-05", "endDate": "2026-10-09"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-19"},
            {"name": "March Break", "startDate": "2027-03-15", "endDate": "2027-03-15"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "douglas county school system": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-08"},
            {"name": "Fall Break", "startDate": "2026-10-12", "endDate": "2026-10-16"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-19"},
            {"name": "March Break", "startDate": "2027-03-08", "endDate": "2027-03-08"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "forsyth county schools": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-09-28", "endDate": "2026-10-02"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-12", "endDate": "2027-02-16"},
            {"name": "March Break", "startDate": "2027-03-15", "endDate": "2027-03-15"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "fulton county schools": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-09-21", "endDate": "2026-09-25"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-19"},
            {"name": "March Break", "startDate": "2027-03-15", "endDate": "2027-03-15"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "gwinnett county public schools": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-12", "endDate": "2026-10-16"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-12", "endDate": "2027-02-16"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "hall county schools": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-12", "endDate": "2026-10-14"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-16"},
            {"name": "March Break", "startDate": "2027-03-19", "endDate": "2027-03-19"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "henry county schools": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-05", "endDate": "2026-10-09"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-05"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-19"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "houston county school district": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-09", "endDate": "2026-10-16"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-15"},
            {"name": "Spring Break", "startDate": "2027-03-26", "endDate": "2027-04-02"},
        ],
        "jackson county school system": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-08", "endDate": "2026-10-13"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-17", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-15"},
            {"name": "March Break", "startDate": "2027-03-12", "endDate": "2027-03-12"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "jasper county charter system": [
            {"name": "Labor Day", "startDate": "2026-09-04", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-12", "endDate": "2026-10-16"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-19"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "lumpkin county school system": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-09-28", "endDate": "2026-10-02"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-05"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-19"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "madison county school system": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-09", "endDate": "2026-10-13"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-12", "endDate": "2027-02-15"},
            {"name": "March Break", "startDate": "2027-03-12", "endDate": "2027-03-12"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "newton county schools": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-12", "endDate": "2026-10-16"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-15", "endDate": "2027-02-16"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "oconee county schools": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-12", "endDate": "2026-10-16"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-12", "endDate": "2027-02-15"},
            {"name": "March Break", "startDate": "2027-03-08", "endDate": "2027-03-08"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "oglethorpe county schools": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-12", "endDate": "2026-10-14"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-05"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-18", "endDate": "2027-02-19"},
            {"name": "March Break", "startDate": "2027-03-12", "endDate": "2027-03-15"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "putnam county charter school system": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-12", "endDate": "2026-10-16"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-05"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-12", "endDate": "2027-02-15"},
            {"name": "March Break", "startDate": "2027-03-15", "endDate": "2027-03-15"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "rockdale county public schools": [
            {"name": "Labor Day", "startDate": "2026-09-04", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-05", "endDate": "2026-10-09"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-16", "endDate": "2027-02-19"},
            {"name": "March Break", "startDate": "2027-03-26", "endDate": "2027-03-26"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
        "walton county school district": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
        ],
        "wilkinson county schools": [
            {"name": "Labor Day", "startDate": "2026-09-07", "endDate": "2026-09-07"},
            {"name": "Fall Break", "startDate": "2026-10-05", "endDate": "2026-10-09"},
            {"name": "Thanksgiving Break", "startDate": "2026-11-23", "endDate": "2026-11-27"},
            {"name": "Christmas Break", "startDate": "2026-12-21", "endDate": "2027-01-04"},
            {"name": "MLK Day", "startDate": "2027-01-18", "endDate": "2027-01-18"},
            {"name": "Winter Break", "startDate": "2027-02-18", "endDate": "2027-02-19"},
            {"name": "Spring Break", "startDate": "2027-04-05", "endDate": "2027-04-09"},
        ],
    },
    "2027-2028": {
        "barrow county school system": [
            {"name": "Labor Day", "startDate": "2027-09-03", "endDate": "2027-09-06"},
            {"name": "Fall Break", "startDate": "2027-10-04", "endDate": "2027-10-08"},
            {"name": "Thanksgiving Break", "startDate": "2027-11-22", "endDate": "2027-11-26"},
            {"name": "Christmas Break", "startDate": "2027-12-20", "endDate": "2028-01-04"},
            {"name": "MLK Day", "startDate": "2028-01-17", "endDate": "2028-01-17"},
            {"name": "Winter Break", "startDate": "2028-02-18", "endDate": "2028-02-21"},
            {"name": "March Break", "startDate": "2028-03-10", "endDate": "2028-03-10"},
            {"name": "Spring Break", "startDate": "2028-04-03", "endDate": "2028-04-07"},
        ],
        "cherokee county school district": [
            {"name": "Labor Day", "startDate": "2027-09-06", "endDate": "2027-09-06"},
            {"name": "Fall Break", "startDate": "2027-09-20", "endDate": "2027-09-24"},
            {"name": "Thanksgiving Break", "startDate": "2027-11-22", "endDate": "2027-11-26"},
            {"name": "Christmas Break", "startDate": "2027-12-20", "endDate": "2028-01-03"},
            {"name": "MLK Day", "startDate": "2028-01-17", "endDate": "2028-01-17"},
            {"name": "Winter Break", "startDate": "2028-02-14", "endDate": "2028-02-18"},
            {"name": "Spring Break", "startDate": "2028-04-03", "endDate": "2028-04-07"},
        ],
        "dawson county schools": [
            {"name": "Labor Day", "startDate": "2027-09-06", "endDate": "2027-09-06"},
            {"name": "Fall Break", "startDate": "2027-09-27", "endDate": "2027-10-01"},
            {"name": "Thanksgiving Break", "startDate": "2027-11-22", "endDate": "2027-11-26"},
            {"name": "Christmas Break", "startDate": "2027-12-20", "endDate": "2028-01-04"},
            {"name": "MLK Day", "startDate": "2028-01-17", "endDate": "2028-01-17"},
            {"name": "Winter Break", "startDate": "2028-02-11", "endDate": "2028-02-15"},
            {"name": "Spring Break", "startDate": "2028-04-03", "endDate": "2028-04-07"},
        ],
        "dekalb county school district": [
            {"name": "Labor Day", "startDate": "2027-09-06", "endDate": "2027-09-06"},
            {"name": "Fall Break", "startDate": "2027-10-04", "endDate": "2027-10-08"},
            {"name": "Thanksgiving Break", "startDate": "2027-11-22", "endDate": "2027-11-26"},
            {"name": "Christmas Break", "startDate": "2027-12-20", "endDate": "2028-01-03"},
            {"name": "MLK Day", "startDate": "2028-01-17", "endDate": "2028-01-17"},
            {"name": "Winter Break", "startDate": "2028-02-21", "endDate": "2028-02-25"},
            {"name": "March Break", "startDate": "2028-03-13", "endDate": "2028-03-13"},
            {"name": "Spring Break", "startDate": "2028-04-03", "endDate": "2028-04-07"},
        ],
        "douglas county school system": [
            {"name": "Labor Day", "startDate": "2027-09-06", "endDate": "2027-09-07"},
            {"name": "Fall Break", "startDate": "2027-10-11", "endDate": "2027-10-15"},
            {"name": "Thanksgiving Break", "startDate": "2027-11-22", "endDate": "2027-11-26"},
            {"name": "Christmas Break", "startDate": "2027-12-20", "endDate": "2028-01-03"},
            {"name": "MLK Day", "startDate": "2028-01-17", "endDate": "2028-01-17"},
            {"name": "Winter Break", "startDate": "2028-02-21", "endDate": "2028-02-25"},
            {"name": "March Break", "startDate": "2028-03-06", "endDate": "2028-03-06"},
            {"name": "Spring Break", "startDate": "2028-04-03", "endDate": "2028-04-07"},
        ],
        "forsyth county schools": [
            {"name": "Labor Day", "startDate": "2027-09-03", "endDate": "2027-09-06"},
            {"name": "Fall Break", "startDate": "2027-09-27", "endDate": "2027-10-01"},
            {"name": "Thanksgiving Break", "startDate": "2027-11-22", "endDate": "2027-11-26"},
            {"name": "Christmas Break", "startDate": "2027-12-20", "endDate": "2028-01-03"},
            {"name": "MLK Day", "startDate": "2028-01-17", "endDate": "2028-01-17"},
            {"name": "Winter Break", "startDate": "2028-02-18", "endDate": "2028-02-22"},
            {"name": "March Break", "startDate": "2028-03-20", "endDate": "2028-03-20"},
            {"name": "Spring Break", "startDate": "2028-04-03", "endDate": "2028-04-07"},
        ],
        "gwinnett county public schools": [
            {"name": "Labor Day", "startDate": "2027-09-06", "endDate": "2027-09-06"},
            {"name": "Fall Break", "startDate": "2027-10-11", "endDate": "2027-10-15"},
            {"name": "Thanksgiving Break", "startDate": "2027-11-22", "endDate": "2027-11-26"},
            {"name": "Christmas Break", "startDate": "2027-12-20", "endDate": "2028-01-03"},
            {"name": "MLK Day", "startDate": "2028-01-17", "endDate": "2028-01-17"},
            {"name": "Winter Break", "startDate": "2028-02-11", "endDate": "2028-02-15"},
            {"name": "Spring Break", "startDate": "2028-04-03", "endDate": "2028-04-07"},
        ],
        "henry county schools": [
            {"name": "Labor Day", "startDate": "2027-09-06", "endDate": "2027-09-06"},
            {"name": "Fall Break", "startDate": "2027-10-04", "endDate": "2027-10-08"},
            {"name": "Thanksgiving Break", "startDate": "2027-11-22", "endDate": "2027-11-26"},
            {"name": "Christmas Break", "startDate": "2027-12-20", "endDate": "2028-01-04"},
            {"name": "MLK Day", "startDate": "2028-01-17", "endDate": "2028-01-17"},
            {"name": "Winter Break", "startDate": "2028-02-21", "endDate": "2028-02-25"},
            {"name": "Spring Break", "startDate": "2028-04-03", "endDate": "2028-04-07"},
        ],
        "rockdale county public schools": [
            {"name": "Labor Day", "startDate": "2027-09-06", "endDate": "2027-09-06"},
            {"name": "Fall Break", "startDate": "2027-10-04", "endDate": "2027-10-08"},
            {"name": "Thanksgiving Break", "startDate": "2027-11-22", "endDate": "2027-11-26"},
            {"name": "Christmas Break", "startDate": "2027-12-20", "endDate": "2028-01-03"},
            {"name": "MLK Day", "startDate": "2028-01-17", "endDate": "2028-01-17"},
            {"name": "Winter Break", "startDate": "2028-02-14", "endDate": "2028-02-18"},
            {"name": "March Break", "startDate": "2028-03-31", "endDate": "2028-03-31"},
            {"name": "Spring Break", "startDate": "2028-04-03", "endDate": "2028-04-07"},
        ],
    },
    "2028-2029": {
        "douglas county school system": [
            {"name": "Labor Day", "startDate": "2028-09-04", "endDate": "2028-09-05"},
            {"name": "Fall Break", "startDate": "2028-10-09", "endDate": "2028-10-13"},
            {"name": "Thanksgiving Break", "startDate": "2028-11-20", "endDate": "2028-11-24"},
            {"name": "Christmas Break", "startDate": "2028-12-20", "endDate": "2029-01-02"},
            {"name": "MLK Day", "startDate": "2029-01-15", "endDate": "2029-01-15"},
            {"name": "Winter Break", "startDate": "2029-02-19", "endDate": "2029-02-23"},
            {"name": "March Break", "startDate": "2029-03-05", "endDate": "2029-03-05"},
            {"name": "Spring Break", "startDate": "2029-04-02", "endDate": "2029-04-06"},
        ],
    },
}


def find_verified_school(ocr_text: str) -> Optional[str]:
    """
    Fuzzy match OCR text against known school names.
    Matches on key terms like county name + "school"/"county".
    Returns normalized school name if found, None otherwise.
    """
    if not ocr_text:
        return None

    text_lower = ocr_text.lower()

    # First try: match on county keyword + school indicator
    for county_keyword, school_name in COUNTY_KEYWORDS.items():
        if county_keyword in text_lower:
            # Check for school-related context
            if any(word in text_lower for word in ["school", "district", "county", "system", "charter"]):
                return school_name

    # Second try: exact substring match of full school name
    for school_name in VERIFIED_SCHOOLS.keys():
        if school_name in text_lower:
            return school_name

    return None


def detect_school_year(ocr_text: str, reference_date: date = None) -> str:
    """
    Detect school year from OCR text or fall back to current school year.

    Args:
        ocr_text: The extracted text to search for year patterns
        reference_date: Optional date to use for fallback (defaults to today)

    Returns:
        School year string in format "YYYY-YYYY" (e.g., "2025-2026")
    """
    if reference_date is None:
        reference_date = date.today()

    # Pattern 1: Full year format "2025-2026" or "2025/2026"
    full_year_pattern = r'20(\d{2})[-/]20(\d{2})'
    match = re.search(full_year_pattern, ocr_text)
    if match:
        year1 = 2000 + int(match.group(1))
        year2 = 2000 + int(match.group(2))
        if year2 == year1 + 1:
            return f"{year1}-{year2}"

    # Pattern 2: Abbreviated format "2025-26" or "2025/26"
    abbrev_pattern = r'20(\d{2})[-/](\d{2})'
    match = re.search(abbrev_pattern, ocr_text)
    if match:
        year1 = 2000 + int(match.group(1))
        year2_suffix = int(match.group(2))
        year2 = 2000 + year2_suffix
        if year2 == year1 + 1:
            return f"{year1}-{year2}"

    # Fallback: infer from reference date
    if reference_date.month >= 8:
        return f"{reference_date.year}-{reference_date.year + 1}"
    else:
        return f"{reference_date.year - 1}-{reference_date.year}"


def get_verified_calendar(school_name: str, school_year: str) -> Optional[List[Dict]]:
    """
    Get pre-verified holiday dates for a school and year.

    Args:
        school_name: Normalized school name (lowercase)
        school_year: School year in format "YYYY-YYYY"

    Returns:
        List of holiday dicts with name, startDate, endDate fields, or None if not found
    """
    if school_year not in VERIFIED_HOLIDAYS:
        return None

    year_data = VERIFIED_HOLIDAYS[school_year]
    if school_name not in year_data:
        return None

    return year_data[school_name]


def get_verified_calendar_24_months(school_name: str, reference_date: date = None) -> Optional[List[Dict]]:
    """
    Get pre-verified holiday dates for a school spanning 24 months from reference_date.

    Args:
        school_name: Normalized school name (lowercase)
        reference_date: Start date for 24-month window (defaults to today)

    Returns:
        List of holiday dicts sorted by startDate, or None if school not found
    """
    if reference_date is None:
        reference_date = date.today()

    end_date = reference_date + timedelta(days=730)  # ~24 months

    all_holidays = []

    for school_year in VERIFIED_HOLIDAYS.keys():
        year_data = VERIFIED_HOLIDAYS[school_year]
        if school_name not in year_data:
            continue

        for holiday in year_data[school_name]:
            holiday_start = date.fromisoformat(holiday['startDate'])
            holiday_end = date.fromisoformat(holiday['endDate'])

            # Include if holiday overlaps with our 24-month window
            if holiday_end >= reference_date and holiday_start <= end_date:
                all_holidays.append({**holiday, 'verified': True})

    if not all_holidays:
        return None

    # Sort by start date
    all_holidays.sort(key=lambda h: h['startDate'])
    return all_holidays


def get_display_name(normalized_name: str) -> str:
    """Get the display name for a normalized school name."""
    return VERIFIED_SCHOOLS.get(normalized_name, normalized_name.title())


def list_verified_schools() -> List[str]:
    """Return list of all verified school names (display format)."""
    return list(VERIFIED_SCHOOLS.values())


def list_available_years() -> List[str]:
    """Return list of all available school years."""
    return sorted(VERIFIED_HOLIDAYS.keys())


# ===== DATABASE-BACKED FUNCTIONS =====
# These functions use the database when available, with fallback to hardcoded data

def get_verified_calendar_from_db(school_name: str, reference_date: date = None) -> Optional[List[Dict]]:
    """
    Get verified holiday dates from database for a school, spanning 24 months.

    Args:
        school_name: Normalized school name (lowercase)
        reference_date: Start date for 24-month window (defaults to today)

    Returns:
        List of holiday dicts sorted by startDate, or None if school not found
    """
    try:
        from flask import current_app
        from models import SchoolEntity, VerifiedHoliday

        if reference_date is None:
            reference_date = date.today()

        end_date = reference_date + timedelta(days=730)

        # Find the school entity by normalized name
        normalized = school_name.replace(' ', '_')
        entity = SchoolEntity.query.filter(
            SchoolEntity.normalized_name.like(f"%{normalized.split('_')[0]}%")
        ).first()

        if not entity:
            # Fallback to hardcoded data
            return get_verified_calendar_24_months(school_name, reference_date)

        # Get holidays from database
        holidays = VerifiedHoliday.query.filter_by(
            school_entity_id=entity.id
        ).filter(
            VerifiedHoliday.end_date >= reference_date,
            VerifiedHoliday.start_date <= end_date
        ).order_by(VerifiedHoliday.start_date).all()

        if not holidays:
            # Fallback to hardcoded data
            return get_verified_calendar_24_months(school_name, reference_date)

        return [
            {
                'name': h.name,
                'startDate': h.start_date.isoformat(),
                'endDate': h.end_date.isoformat(),
                'verified': True
            }
            for h in holidays
        ]

    except Exception:
        # Fallback to hardcoded data if database not available
        return get_verified_calendar_24_months(school_name, reference_date)


def get_school_entity_by_name(school_name: str):
    """
    Get SchoolEntity from database by normalized name.

    Returns the entity object or None if not found.
    """
    try:
        from models import SchoolEntity

        # Try exact match first
        normalized = school_name.replace(' ', '_')
        entity = SchoolEntity.query.filter_by(normalized_name=normalized).first()

        if not entity:
            # Try partial match
            entity = SchoolEntity.query.filter(
                SchoolEntity.normalized_name.like(f"%{normalized.split('_')[0]}%")
            ).first()

        return entity

    except Exception:
        return None

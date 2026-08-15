"""Configuration for the KITCOEK website crawler."""

# Only crawl this domain
ALLOWED_DOMAIN = "www.kitcoek.in"

# All known pages to scrape (discovered manually from site navigation)
SEED_URLS = [
    "https://www.kitcoek.in/",
    "https://www.kitcoek.in/about",
    "https://www.kitcoek.in/founder-trustees",
    "https://www.kitcoek.in/board-of-directors",
    "https://www.kitcoek.in/director",
    "https://www.kitcoek.in/office-administration",
    "https://www.kitcoek.in/milestones",
    "https://www.kitcoek.in/internal-quality-assurance-cell",
    "https://www.kitcoek.in/nirf",
    "https://www.kitcoek.in/aicte-approval",
    "https://www.kitcoek.in/manditory-disclosure",
    "https://www.kitcoek.in/admission-undergraduate",
    "https://www.kitcoek.in/admission-postgraduate",
    "https://www.kitcoek.in/scholarships",
    "https://www.kitcoek.in/apply-admission",
    # Departments
    "https://www.kitcoek.in/best-biotechnology-engineering-college-kolhapur-biotechnology-engineering-college",
    "https://www.kitcoek.in/best-civil-engineering-college-kolhapur-civil-engineering-college",
    "https://www.kitcoek.in/best-environmental-engineering-college-kolhapur-environmental-engineering-college",
    "https://www.kitcoek.in/best-cse-college-kolhapur-best-computer-science-engineering-college",
    "https://www.kitcoek.in/best-cse-college-kolhapur-best-computer-science-business-systems",
    "https://www.kitcoek.in/best-cse-college-kolhapur-best-computer-science-engineering-artificial-intelligence-machine-learning",
    "https://www.kitcoek.in/best-electrical-engineering-college-kolhapur-electrical-engineering-college",
    "https://www.kitcoek.in/best-mechanical-engineering-college-kolhapur-mechanical-engineering-college",
    "https://www.kitcoek.in/best-basic-science-and-humanities-engineering-college-kolhapur-basic-science-and-humanities-engineering-college",
    # Academics
    "https://www.kitcoek.in/online-syllabus",
    "https://www.kitcoek.in/studentClubs",
    # Exam Cell
    "https://www.kitcoek.in/administration-staff",
    "https://www.kitcoek.in/semister-exam-timetable",
    "https://www.kitcoek.in/notice",
    "https://www.kitcoek.in/results",
    "https://www.kitcoek.in/paper-setting-documents",
    "https://www.kitcoek.in/remuneration-format",
    # Placements & Admissions
    "https://www.kitcoek.in/tnp",
    "https://www.kitcoek.in/contact",
    # Extra pages discovered earlier
    "https://www.kitcoek.in/alumni",
    "https://www.kitcoek.in/alumni-profile",
    "https://www.kitcoek.in/alumni-activities",
    "https://www.kitcoek.in/alumni-achievements",
    "https://www.kitcoek.in/alumni-jobs",
    "https://www.kitcoek.in/new-vision",
    "https://www.kitcoek.in/sih2025",
]

# Be polite to the server
REQUEST_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 15
USER_AGENT = "KITCOEK-RAG-Project-Bot/1.0 (student PBL assignment)"

# Safety limits
MAX_PAGES = 300
MAX_PDFS = 100

# Where raw output goes
RAW_PAGES_DIR = "data/raw/pages"
RAW_PDFS_DIR = "data/raw/pdfs"
RAW_PDF_FILES_DIR = "data/raw/pdf_files"

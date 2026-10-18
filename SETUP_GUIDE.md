# ComplyNex CMS — Setup & Testing Guide

> Complete instructions to deploy and test on a new machine.

---

## 1. Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Python** | 3.12 or 3.13 | Download from [python.org](https://python.org). **Do NOT use 3.14** (spaCy incompatibility) |
| **pip** | Latest | Comes with Python |
| **Git** | Any | To clone the repository |
| **Redis** | 7.x (optional) | For dashboard caching. App works without it. |

### Windows-Specific
- Enable **long paths** if not already: `reg add HKLM\SYSTEM\CurrentControlSet\Control\FileSystem /v LongPathsEnabled /t REG_DWORD /d 1`
- Install [Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) if pip fails on compiled packages

---

## 2. Quick Start (5 minutes)

```powershell
# 1. Clone or copy the project
git clone <repository-url> ComplyNex_CMS
cd ComplyNex_CMS

# 2. Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1    # Windows PowerShell
# source venv/bin/activate     # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Download spaCy model (required for NLP)
python -m spacy download en_core_web_sm

# 5. Download NLTK data
python -c "import nltk; nltk.download('punkt'); nltk.download('stopwords'); nltk.download('vader_lexicon')"

# 6. Create .env file (copy from template below)
# See Section 3

# 7. Run the application
python run.py
```

The app will be available at **http://localhost:5000**

### Default Admin Credentials
```
Email:    admin@complynex.online
Password: Admin@123
```
> ⚠️ Change this password immediately after first login!

---

## 3. Environment Configuration (.env)

Create a `.env` file in the project root:

```env
# === REQUIRED ===
FLASK_ENV=development
SECRET_KEY=generate-a-random-64-char-key-here
DATABASE_URI=sqlite:///complynex_cms.db

# === OPTIONAL ===
# Redis (for dashboard caching, works without it)
REDIS_URL=redis://localhost:6379/0

# Adverse Media Screening API (for real-time news screening)
NEWSAPI_KEY=your-newsdata-api-key
NEWSAPI_ENABLED=true
NEWSAPI_RATE_LIMIT=100

# Email (for notifications, mock mode by default)
EMAIL_MOCK_MODE=true
EMAIL_USER=your-gmail@gmail.com
EMAIL_PASS=your-app-password
MAIL_DEFAULT_SENDER=noreply@complynex.online
```

### Generate a Secure SECRET_KEY
```python
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 4. Database Setup

### Option A: Fresh Database (New Installation)
The app auto-creates the database on first run via `run.py`. It will:
1. Create `complynex_cms.db` in the project root
2. Initialize all 138 tables
3. Create the default admin user

### Option B: Copy Existing Database (For Testing)
Copy `complynex_cms.db` (1.6 GB) from the main machine to the new laptop's project root. This includes all existing data, users, and screening watchlists.

```powershell
# On new machine, place the DB file
copy \\source\path\complynex_cms.db .\complynex_cms.db
```

### Option C: PostgreSQL (Production)
```env
DATABASE_URI=postgresql://user:password@localhost:5432/complynex_cms
```
Then run the schema migration scripts in `database/` and `scripts/`.

---

## 5. Docker Deployment (Alternative)

```powershell
# Build and run with Docker Compose
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f web
```

This starts:
- **Web app** on port 5000 (Gunicorn with 4 workers)
- **Redis** on port 6379

---

## 6. Verification Checklist

After starting the app, verify each module:

| # | URL | Expected |
|---|-----|----------|
| 1 | `/auth/login` | Login page loads |
| 2 | `/dashboard` | Dashboard with stats |
| 3 | `/screening/dashboard` | Screening stats (397+ screenings) |
| 4 | `/screening/screen` | Manual screening form |
| 5 | `/screening/sources` | 8 data sources listed |
| 6 | `/screening/queue` | Review queue loads |
| 7 | `/screening/reports` | Compliance reports |
| 8 | `/policies/` | Policy list |
| 9 | `/training/` | Training courses |
| 10 | `/governance/` | Governance dashboard |
| 11 | `/admin/users` | User management |
| 12 | `/whistleblowing/dashboard` | Whistleblowing cases |

**Quick Smoke Test:**
```powershell
# Test the screening engine directly
python -c "
from app import app
with app.app_context():
    from screening.complynex_engine import ComplyNexScreeningEngine
    engine = ComplyNexScreeningEngine()
    result = engine.screen_person(name='John Smith')
    print(f'Matches: {result[\"total_matches\"]}, Score: {result[\"highest_score\"]}')
    engine.close()
"
```

---

## 7. Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError` | Activate venv: `.\venv\Scripts\Activate.ps1` |
| `No such table` | Run: `python -c "from app import app; from database.db import init_db; app.app_context().push(); init_db()"` |
| Redis connection error | App works without Redis. Set `REDIS_URL=` (empty) to disable |
| spaCy model error | Run: `python -m spacy download en_core_web_sm` |
| Port 5000 in use | Run: `python run.py 8000` (uses port 8000) |
| Large DB copy slow | Use 7zip to compress the 1.6GB SQLite file (~200MB compressed) |

---

## 8. Project File Structure (Key Files Only)

```
ComplyNex_CMS/
├── app.py                  # Application factory
├── run.py                  # Entry point (python run.py)
├── config.py               # Dev/Prod configuration
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables
├── complynex_cms.db        # SQLite database (1.6GB)
├── Dockerfile              # Docker build
├── docker-compose.yml      # Docker orchestration
├── extensions.py           # Flask extensions (CSRF, Mail)
├── screening/
│   ├── routes.py           # Screening routes
│   ├── complynex_engine.py # Core screening engine
│   ├── ml_model.pkl        # ML model
│   ├── format_handlers.py  # UN/OFAC/EU/HMT/OS parsers
│   └── templates/          # Screening templates
├── database/
│   ├── db.py               # DB connection manager
│   └── *.sql               # Schema files
├── scripts/                # Migration & import scripts
│   └── batch_screening_processor.py  # New: Bulk batch processor
├── templates/              # HTML templates
└── static/                 # CSS, JS, images

---

## 9. Bulk Sanction Screening (35K+ Records)

For high-volume processing that avoids web timeouts:

1.  Place your Excel file in `Screening Reports/Data Sheet.xlsx`.
2.  Run the batch processor:
    ```bash
    python scripts/batch_screening_processor.py
    ```
3.  The script processes in batches of **100** and saves a checkpoint. You can stop and resume it anytime.
4.  Results are saved to `Screening Reports/Batch_Results/`.


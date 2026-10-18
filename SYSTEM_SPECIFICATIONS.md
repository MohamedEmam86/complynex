# ComplyNex Compliance Management System — System Specifications

> Technical specifications document for IT team deployment preparation.
> Version: 1.1 | Date: March 2026 (CBE)

---

## 1. System Overview

**ComplyNex CMS** is a full-stack compliance management platform built for ComplyNex Egypt, a fintech company regulated by the Central Bank of Egypt. The system manages sanctions screening, policy lifecycle, training compliance, governance, whistleblowing, AML/CFT, data protection, and regulatory reporting.

### Key Metrics

| Metric | Value |
|--------|-------|
| Total Modules | 19 |
| Database Tables | 138 |
| HTML Templates | 174 |
| Python Dependencies | 94 |
| ML Models | 5 (screening engine) |
| Sanctions Watchlist Records | 1,574,854 |
| Data Sources | 8 international/local lists |
| Supported Languages | Arabic (RTL) + English |

---

## 2. Technology Stack

### Backend
| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | 3.12+ |
| Framework | Flask | 3.0.0 |
| Authentication | Flask-Login | 0.6.3 |
| CSRF Protection | Flask-WTF | 1.2.1 |
| Internationalization | Flask-Babel | 4.0.0 |
| Email | Flask-Mail | 0.9.1 |
| WSGI Server (Prod) | Gunicorn | 21.2.0 |

### Database
| Component | Technology | Notes |
|-----------|-----------|-------|
| Primary DB | SQLite 3 | Development; 1.6 GB file |
| Production DB | PostgreSQL 15+ | Recommended for production |
| DB Size | ~1.6 GB | Includes 1.57M watchlist records |
| Caching | Redis 7.x | Optional; for dashboard stats |

### Machine Learning & NLP
| Component | Technology | Purpose |
|-----------|-----------|---------|
| ML Framework | scikit-learn 1.8 | Screening confidence scoring |
| NLP | spaCy, NLTK, TextBlob | Name matching, text analysis |
| Fuzzy Matching | RapidFuzz, thefuzz, jellyfish | Multi-algorithm name comparison |
| Arabic NLP | PyArabic 0.6.15 | Arabic name normalization |
| ML Models | 5 `.pkl` files (67MB total) | Trained screening classifiers |

### Frontend
| Component | Technology |
|-----------|-----------|
| CSS Framework | Bootstrap 5.3 + Custom Vanilla CSS |
| Visual Style | Modern Glassmorphism & High-Contrast Dark Mode |
| Icons | Bootstrap Icons / Google Fonts |
| JavaScript | Vanilla JS + jQuery + AJAX |
| RTL Support | Full Arabic RTL layout |
| Micro-animations | Subtle CSS transitions on hover/action |
| PDF Generation | fpdf2 |

### Infrastructure
| Component | Technology |
|-----------|-----------|
| Containerization | Docker + docker-compose |
| OS | Windows/Linux |
| Web Server | Gunicorn (4 workers, 120s timeout) |

---

## 3. Module Architecture

The system uses Flask's **Blueprint** pattern. Each module is self-contained with its own routes, templates, and models.

### 3.1 Core Compliance Modules

| Module | URL Prefix | Purpose | Key Features |
|--------|------------|---------|--------------|
| **Sanctions Screening** | `/screening/` | Real-time sanctions/PEP screening | Multi-source engine, ML scoring, bulk upload, queue workflow, SAR generation, **Batch Screening Processor** |
| **Policy Management** | `/policies/` | Policy lifecycle management | Create/edit/approve/publish, multi-attachment, gap analysis, acknowledgments |
| **Training** | `/training/` | Compliance training | Course management, quizzes, certificates, enrollment tracking, report |
| **AML/CFT** | `/aml/` | Anti-money laundering | Customer due diligence (CDD), risk scoring, transaction monitoring |
| **Data Protection** | `/data-protection/` | GDPR/data privacy | DSR management, DPIAs, breach reporting, consent management |

### 3.2 Governance & Ethics Modules

| Module | URL Prefix | Purpose | Key Features |
|--------|------------|---------|--------------|
| **Corporate Governance** | `/governance/` | Board governance | Committees, meetings, fit & proper, independence, skills matrix, CBE report |
| **GHE Declarations** | `/ghe/` | Gifts, Hospitality & Entertainment | Declaration forms, approval workflow, public declaration portal |
| **COI Declarations** | `/coi/` | Conflict of Interest | Campaign management, disclosure forms, mitigation tracking |
| **Code of Ethics** | `/cobec/` | Business ethics conduct | Annual declarations, compliance tracking |
| **Whistleblowing** | `/whistleblowing/` | Speak-up channel | Anonymous submissions, case management, investigation workflow |

### 3.3 Operational Modules

| Module | URL Prefix | Purpose | Key Features |
|--------|------------|---------|--------------|
| **Consumer Protection** | `/consumer-protection/` | Complaint handling | Complaint submission, tracking, resolution workflow |
| **Cybersecurity** | `/cyber/` | Incident management | Cyber incident hub, response tracking |
| **Regulatory Reporting** | `/reporting/` | CBE report generation | Report templates, submission tracking |
| **Internal Blacklist** | `/blacklist/` | Internal block list | Entity blacklisting, bulk import |
| **Merchant KYC** | `/merchant-kyc/` | Merchant verification | KYC directory, document management |
| **Declaration Tracker** | `/tracker/` | Unified declaration view | Cross-module declaration analytics |

### 3.4 Administration Modules

| Module | URL Prefix | Purpose | Key Features |
|--------|------------|---------|--------------|
| **Admin** | `/admin/` | System administration | User management, departments, audit logs, settings, training requirements |
| **User Management** | `/users/` | User profiles | Profile editing, password management, progress tracking |
| **Employee Portal** | `/portal/` | Public employee access | Annual COI/COBEC declarations without CMS login |

---

## 4. Sanctions Screening Engine — Technical Details

### 4.1 Data Sources

| # | Source | Type | Records | Update Method | URL |
|---|--------|------|---------|---------------|-----|
| 1 | Egypt PEP List (EMLCU) | XLSX | 7,372 | Manual upload / Auto-scrape | mlcu.org.eg |
| 2 | UN Security Council | XML | 1,003 | Auto-sync | scsanctions.un.org |
| 3 | OFAC SDN List (US Treasury) | XML | 18,671 | Auto-sync | treasury.gov |
| 4 | HM Treasury UK | JSON | 6,034 | Auto-sync | sanctionslist.fcdo.gov.uk |
| 5 | EU Consolidated Sanctions | XML | ~2,000 | Auto-sync | webgate.ec.europa.eu |
| 6 | OpenSanctions (Global) | FTJSON | ~1.5M | Auto-sync | data.opensanctions.org |
| 7 | OpenSanctions PEP | CSV | Included | Auto-sync | data.opensanctions.org |
| 8 | Internal Blacklist | CSV/XLSX | Variable | Manual upload | Internal |

### 4.2 Matching Algorithm (Ensemble)

The screening engine uses a weighted ensemble of multiple matching algorithms:

| Algorithm | Weight | Library |
|-----------|--------|---------|
| Levenshtein Fuzzy Ratio | Configurable | RapidFuzz |
| Jaro-Winkler Distance | Configurable | jellyfish |
| Partial Substring Matching | Configurable | thefuzz |
| Soundex/Metaphone Phonetic | Configurable | jellyfish |
| ML Confidence Scoring | Calibrated | scikit-learn |
| Arabic Transliteration | Built-in | PyArabic + custom |

**Threshold:** Matches ≥ 70% → sent to review queue; < 70% → auto-cleared.

### 4.3 Screening Workflow

```
Input Name → Multi-Algorithm Matching → ML Scoring → Decision
                                                        │
                                        ┌───────────────┼───────────────┐
                                        ▼               ▼               ▼
                                    CLEAR (<70%)   QUEUE (≥70%)   CONFIRMED HIT
                                    Auto-cleared   Human Review    Block + SAR
```

---

## 5. Database Schema (138 Tables)

### Key Table Groups

| Group | Tables | Purpose |
|-------|--------|---------|
| **Users & Auth** | `users`, `departments`, `user_departments` | Authentication, RBAC |
| **Screening** | `screening_watchlist`, `screening_results`, `screening_queue`, `screening_history`, `screening_whitelist`, `screening_config`, `screening_data_sources` + 10 more | Full screening lifecycle |
| **Policies** | `policies`, `policy_categories`, `policy_versions`, `policy_acknowledgments`, `policy_attachments`, `policy_review_workflow` | Policy management |
| **Training** | `training_courses`, `training_enrollments`, `training_certificates`, `training_questions`, `training_requirements` | Learning management |
| **Governance** | `board_members`, `board_committees`, `board_meetings`, `board_skills_matrix`, `fit_proper_assessments`, `independence_declarations` + 10 more | Board governance |
| **AML/CFT** | `customers`, `customer_transactions`, `customer_risk_scores`, `cdd_reviews`, `sar_reports`, `suspicious_activities` + 5 more | AML compliance |
| **Data Protection** | `data_subject_requests`, `dpias`, `data_breaches`, `consents`, `consent_purposes`, `data_processing_activities` | Privacy compliance |
| **Whistleblowing** | `whistleblowing_cases`, `whistleblowing_updates`, `whistleblowing_attachments`, `whistleblowing_assignments` + 3 more | Case management |
| **Audit** | `audit_logs`, `data_update_audit_log` | Full audit trail |

---

## 6. Security Architecture

| Feature | Implementation |
|---------|---------------|
| **Authentication** | Flask-Login with bcrypt password hashing |
| **Session Management** | Server-side sessions, 30-min timeout, HttpOnly + SameSite cookies |
| **CSRF Protection** | Flask-WTF CSRF tokens on all POST forms |
| **Authorization** | Role-based access control (Admin, Compliance Officer, Employee) |
| **Permission System** | Granular per-module permissions (view, edit, admin) |
| **Password Security** | bcrypt with automatic salting |
| **Input Validation** | Server-side validation on all forms |
| **File Upload Security** | Type checking, size limits (16MB), secure filenames |
| **Audit Logging** | All admin/compliance actions logged with user, timestamp, IP |

### User Roles
| Role | Access Level |
|------|-------------|
| `admin` | Full system access, user management, settings |
| `compliance_officer` | All compliance modules, screening, reports |
| `compliance_manager` | Department-level compliance oversight |
| `employee` | Self-service declarations, training, portal |

---

## 7. Infrastructure Requirements

### Minimum (Development/Testing)
| Resource | Requirement |
|----------|-------------|
| CPU | 2 cores |
| RAM | 4 GB |
| Storage | 5 GB (app) + 2 GB (DB) |
| Network | Internet access for sanctions sync |
| OS | Windows 10+, Ubuntu 20.04+, or macOS 12+ |

### Recommended (Production)
| Resource | Requirement |
|----------|-------------|
| CPU | 4+ cores |
| RAM | 8+ GB |
| Storage | 20 GB SSD (app + DB + uploads) |
| Database | PostgreSQL 15+ (dedicated server recommended) |
| Cache | Redis 7.x (separate instance) |
| Web Server | Gunicorn behind Nginx reverse proxy |
| SSL | TLS 1.2+ certificate required |
| Backup | Daily automated DB backups |
| Network | Outbound access to sanctions data sources |

### Network Requirements (Outbound)

The screening module downloads data from these external URLs:

| Source | Domain | Port |
|--------|--------|------|
| UN Sanctions | `scsanctions.un.org` | 443 |
| OFAC/US Treasury | `www.treasury.gov` | 443 |
| EU Sanctions | `webgate.ec.europa.eu` | 443 |
| UK Sanctions | `sanctionslist.fcdo.gov.uk` | 443 |
| OpenSanctions | `data.opensanctions.org` | 443 |
| Egypt PEP | `www.mlcu.org.eg` | 443 |
| News API | `newsdata.io` | 443 |

---

## 8. Deployment Options

### Option A: Direct Python (Simplest)
```bash
pip install -r requirements.txt
gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 120 app:app
```

### Option B: Docker Compose (Recommended)
```bash
docker-compose up -d
```
Includes web app + Redis. Add Nginx as reverse proxy.

### Option C: Kubernetes (Enterprise)
The Dockerfile supports container orchestration. Deploy with:
- 2-4 replicas of the web container
- Shared PostgreSQL database
- Redis cluster for caching
- Persistent volume for uploads

---

## 9. Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | **Yes** | Random | Flask session encryption key (must be fixed in prod) |
| `FLASK_ENV` | Yes | `development` | `development` or `production` |
| `DATABASE_URI` | Yes | `sqlite:///complynex_cms.db` | Database connection string |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis cache URL |
| `NEWSAPI_KEY` | No | None | NewsData.io API key for adverse media |
| `NEWSAPI_ENABLED` | No | `false` | Enable news screening |
| `EMAIL_USER` | No | None | SMTP username |
| `EMAIL_PASS` | No | None | SMTP password |
| `EMAIL_MOCK_MODE` | No | `true` | Skip actual email sending |
| `MAIL_DEFAULT_SENDER` | No | `noreply@complynex.online` | Default from address |
| `PORT` | No | `5000` | Application port |

---

## 10. Backup & Recovery

### Database Backup
```bash
# SQLite backup
python create_backup.py

# Or manually
cp complynex_cms.db complynex_cms.db.backup.$(date +%Y%m%d)
```

### Critical Files to Back Up
| Path | Size | Contents |
|------|------|----------|
| `complynex_cms.db` | 1.6 GB | All application data |
| `screening/ml_model*.pkl` | 67 MB | Trained ML models |
| `uploads/` | Variable | User-uploaded files |
| `.env` | < 1 KB | Configuration |
| `screening/model_metadata*.json` | < 10 KB | Model version info |

---

## 11. API Endpoints (For Integration)

| Endpoint | Method | Purpose | Auth |
|----------|--------|---------|------|
| `/api/screening/stats` | GET | Screening statistics | Login |
| `/screening/api/scrape-source` | POST | Trigger source sync | Admin |
| `/screening/api/scrape-all` | POST | Sync all sources | Admin |
| `/screening/api/upload-source` | POST | Upload sanctions file | Admin |
| `/screening/api/task_status/<id>` | GET | Check async task | Login |
| `/screening/bulk-upload-status/<id>` | GET | Bulk upload progress | Login |
| `/admin/departments/create-ajax` | POST | Create department | Admin |

---

## 12. Monitoring & Logs

| Log Location | Contents |
|-------------|----------|
| `logs/` | Application logs |
| `error.log` | Error traces |
| `verification.log` | ML verification logs |
| Audit Logs (in DB) | All user actions via `/admin/audit-logs` |
| Screening History (in DB) | All screenings via `/screening/history-full` |

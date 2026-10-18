# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================

import sys, os, json, time, traceback, re
sys.path.insert(0, "/opt/complynex")
os.chdir("/opt/complynex")
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.getcwd(), '.env'))
except ImportError:
    pass
from config import Config

PASS, FAIL, WARN = [], [], []

def ok(label, detail=""):
    PASS.append((label, detail))
    print(f"  \033[32m✓\033[0m {label}" + (f" — {detail}" if detail else ""))

def fail(label, detail=""):
    FAIL.append((label, detail))
    print(f"  \033[31m✗\033[0m {label}" + (f" — {detail}" if detail else ""))

def warn(label, detail=""):
    WARN.append((label, detail))
    print(f"  \033[33m⚠\033[0m {label}" + (f" — {detail}" if detail else ""))

def section(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")

# ── 1. MODULE IMPORTS ─────────────────────────────────────────
section("1. MODULE IMPORTS")
import importlib
modules = {
    "name_normalizer":       "screening.name_normalizer",
    "complynex_engine":      "screening.complynex_engine",
    "internal_pep_service":  "screening.internal_pep_service",
    "internal_blacklist":    "screening.internal_blacklist_service",
    "multi_source_screener": "screening.multi_source_screener",
    "arabic_utils":          "screening.arabic_utils",
}
loaded = {}
for name, mod_path in modules.items():
    try:
        loaded[name] = importlib.import_module(mod_path)
        ok(f"import {mod_path}")
    except Exception as e:
        fail(f"import {mod_path}", str(e))

# ── 2. NORMALIZER UNIT TESTS ──────────────────────────────────
section("2. NAME NORMALIZER")
try:
    from screening.name_normalizer import normalise, score_match, EQUIV_TABLE

    norm_cases = [
        ("Mohamed",     "muhammad",  "Mohamed->muhammad EQUIV"),
        ("Mohammed",    "muhammad",  "Mohammed->muhammad EQUIV"),
        ("Nashwa",      "ncwy",      "Nashwa->ncwy post-phonetic EQUIV"),
        ("Noshwa",      "ncwy",      "Noshwa->ncwy post-phonetic EQUIV"),
        ("Akl",         "aql",       "Akl->aql EQUIV"),
        ("Khalid",      "xalid",     "kh->x phonetic rule"),
        ("Elsayed",     "sayed",     "El prefix stripped"),
        ("",            "",          "Empty string safe"),
    ]
    for inp, expected, label in norm_cases:
        result = normalise(inp)
        if result == expected:
            ok(label, f"{inp} -> {result}")
        else:
            fail(label, f"{inp} -> {result} (expected {expected})")

    score_cases = [
        ("Nourhan El Sayed Abdulhameed", "NWRHAN ALSYD ABD ALHMYD ALSHYKH", 0.80, True,  "Nourhan variants match"),
        ("Norhan Elsaid Abdelhamid",     "NWRHAN ALSYD ABD ALHMYD ALSHYKH", 0.80, True,  "Norhan alt spelling"),
        ("Nashwa Aql",                   "NSHWY SLYMAN MOHAMED AQL",        0.80, True,  "Nashwa Aql matches"),
        ("Noshwa Akl",                   "NSHWY SLYMAN MOHAMED AQL",        0.80, True,  "Noshwa Akl matches"),
        ("Ahmed Mohamed Ali",            "HLMY AHMED MOHAMED ALY GAWYSH",   0.40, False, "Common names no FP"),
        ("John Smith",                   "NWRHAN ALSYD ABD ALHMYD ALSHYKH", 0.20, False, "Unrelated names"),
    ]
    for q, c, thresh, should_exceed, label in score_cases:
        s = score_match(q, c)
        if should_exceed and s >= thresh:
            ok(label, f"{s:.3f} >= {thresh}")
        elif not should_exceed and s < thresh:
            ok(label, f"{s:.3f} < {thresh}")
        else:
            fail(label, f"{s:.3f} (should_exceed={should_exceed}, thresh={thresh})")

except Exception as e:
    fail("Normalizer suite crashed", traceback.format_exc().split("\n")[-2])

# ── 3. PEP SERVICE ────────────────────────────────────────────
section("3. INTERNAL PEP SERVICE")
try:
    from screening.internal_pep_service import InternalPEPService
    svc = InternalPEPService()
    try:
        stats = svc.get_statistics()
        total = stats.get("total", 0)
        ok("DB connection", f"{total} active PEP records")
        if total == 0:
            warn("PEP list is empty")
    except Exception as e:
        fail("PEP DB connection", str(e))

    pep_tests = [
        ("نشوي عقل",         True,  "Arabic 2-token search"),
        ("Nashwa Aql",        True,  "English transliteration"),
        ("Noshwa Akl",        True,  "Alt spelling"),
        ("Ahmed Mohamed Ali", False, "Common-name guard"),
        ("John Smith",        False, "Unrelated name"),
        ("",                  False, "Empty string safe"),
        ("A",                 False, "Single char safe"),
        ("x" * 200,          False,  "Very long input safe"),
    ]
    for name, should_hit, label in pep_tests:
        try:
            r = svc.search_by_name(name)
            hit = len(r) >= 1
            if hit == should_hit:
                detail = f"score={r[0].get('_match_score',0):.3f} | {r[0].get('full_name','')}" if r else "0 hits"
                ok(label, detail)
            else:
                detail = f"{len(r)} hits" + (f" top={r[0].get('full_name','')}" if r else "")
                fail(label, detail)
        except Exception as e:
            fail(label, f"EXCEPTION: {e}")

except Exception as e:
    fail("PEP service suite crashed", str(e))

# ── 4. BLACKLIST SERVICE ──────────────────────────────────────
section("4. INTERNAL BLACKLIST SERVICE")
try:
    from screening.internal_blacklist_service import InternalBlacklistService
    bsvc = InternalBlacklistService()
    for name, label in [("test","Normal search"),("","Empty"),("   ","Whitespace"),("123","Numeric")]:
        try:
            r = bsvc.search_by_name(name)
            ok(f"Blacklist: {label}", f"{len(r)} hits")
        except Exception as e:
            fail(f"Blacklist crashes on: {label}", str(e))
except Exception as e:
    fail("Blacklist service unavailable", str(e))

# ── 5. MAIN ENGINE ────────────────────────────────────────────
section("5. SCREENING ENGINE — screen_person()")
try:
    try:
        from screening.routes import _engine_instance as engine
        ok("Engine reused from routes._engine_instance")
    except Exception as _ei:
        from screening.complynex_engine import ComplyNexScreeningEngine
        from app import create_app as _ca
        _ca().app_context().push()
        engine = ComplyNexScreeningEngine(db_config={})

    engine_tests = [
        ("Nashwa Aql",        "EG", None, "English PEP check"),
        ("نشوي عقل",          "EG", None, "Arabic PEP check"),
        ("Ahmed Mohamed Ali", "EG", None, "Common name low match"),
        ("John Smith",        "US", None, "Unrelated English"),
        ("",                  "EG", None, "Empty name no crash"),
        ("A B C D E F G H I J K L M N O", "EG", None, "15-word truncation"),
    ]
    for name, nat, dob, label in engine_tests:
        try:
            t = time.time()
            result = engine.screen_person(name, nationality=nat, date_of_birth=dob)
            elapsed = round((time.time()-t)*1000)
            if not isinstance(result, dict):
                fail(label, f"returned {type(result)}")
                continue
            sr = result.get("screening_result", "MISSING")
            matches = result.get("matches", [])
            highest = result.get("highest_score", 0)
            if sr == "MISSING":
                fail(label, "screening_result key missing")
            elif elapsed > 30000:
                warn(label, f"{sr} in {elapsed}ms — too slow")
            else:
                ok(label, f"{sr} | {len(matches)} matches | {highest:.1f}% | {elapsed}ms")
            for m in matches[:3]:
                for key in ["match_score","full_name","source","list_type"]:
                    if key not in m:
                        fail(f"Match missing key [{key}]", f"in result for {repr(name)}")
        except Exception as e:
            fail(label, traceback.format_exc().split("\n")[-2])
except Exception as e:
    fail("Engine suite crashed", traceback.format_exc().split("\n")[-2])

# ── 6. MULTI-SOURCE SCREENER ──────────────────────────────────
section("6. MULTI-SOURCE SCREENER")
try:
    from screening.multi_source_screener import MultiSourceScreener
    try:
        db_config
    except NameError:
        db_config = {
            "host": Config.POSTGRES_CONFIG['host'],
            "dbname": Config.POSTGRES_CONFIG['database'],
            "user": Config.POSTGRES_CONFIG['user'],
            "password": Config.POSTGRES_CONFIG['password'],
        }
    mss = MultiSourceScreener(db_config)
    t = time.time()
    result = mss.screen_person("John Smith", nationality="US")
    elapsed = round((time.time()-t)*1000)
    ok("screen_person()", f"{result.get('screening_result')} | {elapsed}ms")
except Exception as e:
    fail("MultiSourceScreener", str(e))

# ── 7. ARABIC UTILITIES ───────────────────────────────────────
section("7. ARABIC UTILITIES")
try:
    from screening.arabic_utils import generate_arabic_variants
    from screening.complynex_engine import transliterate_arabic
    for text, label in [("نشوي عقل","Female name"),("محمد علي","Common name"),("","Empty")]:
        try:
            v = generate_arabic_variants(text) if text else []
            tr = transliterate_arabic(text) if text else ""
            ok(label, f"variants={len(v)} translit=\"{tr[:30]}\"")
        except Exception as e:
            fail(label, str(e))
except Exception as e:
    fail("Arabic utilities crashed", str(e))

# ── 8. DATABASE INTEGRITY ─────────────────────────────────────
section("8. DATABASE INTEGRITY")
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(
        host=Config.POSTGRES_CONFIG['host'],
        dbname=Config.POSTGRES_CONFIG['database'],
        user=Config.POSTGRES_CONFIG['user'],
        password=Config.POSTGRES_CONFIG['password'],
        cursor_factory=RealDictCursor,
    )
    cur = conn.cursor()
    checks = [
        ("SELECT COUNT(*) as c FROM internal_pep WHERE is_active=1", "Active PEP records", 1),
        ("SELECT COUNT(*) as c FROM internal_pep WHERE full_name IS NULL AND original_name IS NULL", "PEP with no name", 0),
        ("SELECT COUNT(*) as c FROM screening_watchlist WHERE is_active=1", "Active watchlist records", 0),
    ]
    for sql, label, min_exp in checks:
        cur.execute(sql)
        c = cur.fetchone()["c"]
        if c >= min_exp:
            ok(label, f"{c} records")
        else:
            warn(label, f"{c} (expected >={min_exp})")
    cur.execute("SELECT full_name, COUNT(*) as c FROM internal_pep WHERE is_active=1 AND full_name IS NOT NULL GROUP BY full_name HAVING COUNT(*)>1 LIMIT 5")
    dupes = cur.fetchall()
    if dupes:
        warn("Duplicate names in PEP", f"{len(dupes)} found e.g. {dupes[0]['full_name']}")
    else:
        ok("No duplicate names in PEP list")
    conn.close()
except Exception as e:
    fail("Database integrity", str(e))

# ── 9. HTTP ENDPOINT SMOKE TEST ───────────────────────────────
section("9. HTTP ENDPOINT SMOKE TEST")
import http.client

def http_get(path):
    try:
        conn = http.client.HTTPConnection("localhost", 5000, timeout=10)
        conn.request("GET", path, headers={"User-Agent": "screening-agent"})
        r = conn.getresponse()
        h = {k.lower():v for k,v in r.getheaders()}
        conn.close()
        return r.status, h
    except:
        return None, {}

endpoints = [
    ("/",                         302, "Root redirects to login"),
    ("/auth/login",               200, "Login page loads"),
    ("/screening/screen",         302, "Screening requires auth"),
    ("/aml/alerts/1",             302, "AML alerts require auth"),
    ("/aml/customers/1",          302, "AML customers require auth"),
    ("/blacklist/pep/view/1",     302, "Blacklist requires auth"),
    ("/whistleblowing/submit",    200, "Whistleblowing submit public"),
    ("/whistleblowing/track",     200, "Whistleblowing track public"),
    ("/whistleblowing/anonymous", 200, "Whistleblowing info public"),
    ("/nonexistent-xyz-page",     404, "404 handler works"),
]
for path, expected, label in endpoints:
    status, _ = http_get(path)
    if status is None:
        fail(label, "Connection refused")
    elif status == expected:
        ok(label, f"HTTP {status}")
    else:
        fail(label, f"HTTP {status} (expected {expected})")

_, headers = http_get("/")
for hdr in ["x-frame-options","x-content-type-options","content-security-policy","x-xss-protection"]:
    if hdr in headers:
        ok(f"Header: {hdr}", headers[hdr][:50])
    else:
        fail(f"Header missing: {hdr}")

# ── 10. EDGE CASES ────────────────────────────────────────────
section("10. EDGE CASES & INJECTION RESISTANCE")
try:
    from screening.name_normalizer import score_match
    edge = [
        ("\'; DROP TABLE internal_pep; --", "SQL injection"),
        ("<script>alert(1)</script>",          "XSS attempt"),
        ("../../etc/passwd",                   "Path traversal"),
        ("\x00\x01\x02",                    "Null bytes"),
        ("A"*500,                              "500-char input"),
        ("   spaces   ",                       "Whitespace padding"),
        ("名前テスト",                           "Japanese chars"),
    ]
    for name, label in edge:
        try:
            s = score_match(name, "TEST NAME")
            ok(label, f"score={s:.3f} no crash")
        except Exception as e:
            fail(label, f"CRASHED: {e}")
except Exception as e:
    fail("Edge case suite crashed", str(e))

# ── FINAL REPORT ──────────────────────────────────────────────
section("FINAL REPORT")
total = len(PASS)+len(FAIL)+len(WARN)
print(f"  Total  : {total}")
print(f"  \033[32mPassed\033[0m : {len(PASS)}")
print(f"  \033[31mFailed\033[0m : {len(FAIL)}")
print(f"  \033[33mWarnings\033[0m: {len(WARN)}")
if FAIL:
    print("\n  \033[31mFAILURES:\033[0m")
    for l,d in FAIL:
        print(f"    ✗ {l}")
        if d: print(f"      -> {d}")
if WARN:
    print("\n  \033[33mWARNINGS:\033[0m")
    for l,d in WARN:
        print(f"    ⚠ {l}")
        if d: print(f"      -> {d}")
score = round(len(PASS)/total*100) if total else 0
print(f"\n  Health score: {score}%\n")
os.makedirs("/opt/pentest/results", exist_ok=True)
with open("/opt/pentest/results/screening_agent_report.json","w") as f:
    json.dump({"timestamp":time.strftime("%Y-%m-%d %H:%M:%S"),"total":total,"passed":len(PASS),"failed":len(FAIL),"warnings":len(WARN),"health_score":score,"failures":[{"check":l,"detail":d} for l,d in FAIL],"warnings_list":[{"check":l,"detail":d} for l,d in WARN]},f,indent=2)
print("  Report: /opt/pentest/results/screening_agent_report.json")

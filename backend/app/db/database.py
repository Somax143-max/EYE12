"""
DRISHTI AI: Clinical SQLite Screening Database & Longitudinal Tracking (Items 57, 58, 59, 60)
Provides:
- Relational schema for patients, fundus screenings, clinician reviews, and audit trail
- Patient longitudinal progression tracking (detecting rapid progression >= +1 grade / 12 months)
- Ophthalmologist review & override logging
- Second-opinion tele-consultation queue management
- Population screening analytics for District Health Officials
"""

import os, sqlite3, datetime, json

DB_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "data", "drishti_clinical.db")

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes SQLite schema and performance indices."""
    conn = get_connection()
    c = conn.cursor()

    # 1. Patients Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS patients (
        patient_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        age INTEGER NOT NULL,
        gender TEXT,
        contact TEXT,
        diabetes_type TEXT DEFAULT 'Type 2',
        diabetes_duration_years REAL DEFAULT 5.0,
        hba1c REAL DEFAULT 7.5,
        phc_center TEXT DEFAULT 'District Primary Health Centre',
        registered_at TEXT NOT NULL
    )
    """)

    # 2. Screenings Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS screenings (
        screening_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id TEXT NOT NULL,
        eye TEXT NOT NULL, -- 'OD' or 'OS'
        image_path TEXT,
        image_sha256 TEXT,
        is_gradable INTEGER NOT NULL,
        quality_grade TEXT,
        focus_score REAL,
        glare_pct REAL,
        grade INTEGER NOT NULL,
        grade_name TEXT NOT NULL,
        referable INTEGER NOT NULL,
        dr_damage_percentage REAL NOT NULL,
        lesion_burden_score REAL,
        confidence_pct REAL,
        entropy REAL,
        high_uncertainty INTEGER,
        num_mas INTEGER,
        num_hemo INTEGER,
        num_ex INTEGER,
        num_cws INTEGER,
        csme_status TEXT,
        screened_at TEXT NOT NULL,
        status TEXT DEFAULT 'AUTO_TRIAGED', -- 'AUTO_TRIAGED', 'REFERRED', 'CONFIRMED', 'OVERRIDDEN'
        FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
    )
    """)

    # 3. Clinician Reviews & Overrides Table (Item 59)
    c.execute("""
    CREATE TABLE IF NOT EXISTS clinician_reviews (
        review_id INTEGER PRIMARY KEY AUTOINCREMENT,
        screening_id INTEGER NOT NULL,
        clinician_name TEXT NOT NULL,
        clinician_grade INTEGER NOT NULL,
        clinician_action TEXT NOT NULL, -- 'CONFIRMED', 'OVERRIDDEN', 'ESCALATED', 'RECAPTURE_ORDERED'
        reviewed_at TEXT NOT NULL,
        notes TEXT,
        FOREIGN KEY (screening_id) REFERENCES screenings(screening_id)
    )
    """)

    # Indices
    c.execute("CREATE INDEX IF NOT EXISTS idx_screenings_patient ON screenings(patient_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_screenings_referable ON screenings(referable)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_screenings_date ON screenings(screened_at)")

    conn.commit()
    conn.close()

def register_patient(data):
    """Registers a new patient into the database."""
    conn = get_connection()
    c = conn.cursor()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    pid = data.get("patient_id") or f"PAT_{int(datetime.datetime.now().timestamp()*1000)%1000000:06d}"
    
    c.execute("""
    INSERT OR REPLACE INTO patients 
    (patient_id, name, age, gender, contact, diabetes_type, diabetes_duration_years, hba1c, phc_center, registered_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pid,
        data.get("name", "Anonymous Patient"),
        int(data.get("age", 50)),
        data.get("gender", "Other"),
        data.get("contact", ""),
        data.get("diabetes_type", "Type 2"),
        float(data.get("diabetes_duration_years", 5.0)),
        float(data.get("hba1c", 7.5)),
        data.get("phc_center", "District Rural Health Center"),
        now_iso
    ))
    conn.commit()
    conn.close()
    return pid

def save_screening(patient_id, eye, analysis_result, image_path=None):
    """Saves a retinal screening analysis to the database."""
    conn = get_connection()
    c = conn.cursor()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    grade = analysis_result.get("grade", 0)
    referable = 1 if analysis_result.get("referable", False) else 0
    is_gradable = 1 if analysis_result.get("is_gradable", True) else 0
    status = "REFERRED" if referable else ("UNGRADABLE" if not is_gradable else "AUTO_TRIAGED")

    c.execute("""
    INSERT INTO screenings
    (patient_id, eye, image_path, image_sha256, is_gradable, quality_grade, focus_score, glare_pct,
     grade, grade_name, referable, dr_damage_percentage, lesion_burden_score, confidence_pct,
     entropy, high_uncertainty, num_mas, num_hemo, num_ex, num_cws, csme_status, screened_at, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        patient_id,
        eye.upper(),
        image_path or "",
        analysis_result.get("image_sha256_prefix", ""),
        is_gradable,
        analysis_result.get("quality_assessment", {}).get("quality_grade", "N/A"),
        float(analysis_result.get("focus_score", 0.0)),
        float(analysis_result.get("glare_pct", 0.0)),
        grade,
        analysis_result.get("grade_name", "UNKNOWN"),
        referable,
        float(analysis_result.get("dr_damage_percentage", 0.0)),
        float(analysis_result.get("lesion_burden_score", 0.0)),
        float(analysis_result.get("dl_confidence_pct", 0.0)),
        float(analysis_result.get("normalized_entropy", 0.0)),
        1 if analysis_result.get("high_uncertainty", False) else 0,
        int(analysis_result.get("mas_count", 0)),
        int(analysis_result.get("hemo_count", 0)),
        int(analysis_result.get("exudates_count", 0)),
        int(analysis_result.get("cws_count", 0)),
        str(analysis_result.get("icdr_criteria", {}).get("csme_status", "N/A")),
        now_iso,
        status
    ))
    screening_id = c.lastrowid
    conn.commit()
    conn.close()
    return screening_id

def record_clinician_override(screening_id, clinician_name, clinician_grade, clinician_action, notes=""):
    """Logs an ophthalmologist review, agreement, or diagnostic override (Item 59)."""
    conn = get_connection()
    c = conn.cursor()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    c.execute("""
    INSERT INTO clinician_reviews
    (screening_id, clinician_name, clinician_grade, clinician_action, reviewed_at, notes)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (screening_id, clinician_name, clinician_grade, clinician_action, now_iso, notes))

    # Update screening status
    new_status = "OVERRIDDEN" if clinician_action == "OVERRIDDEN" else "CONFIRMED"
    c.execute("UPDATE screenings SET status = ? WHERE screening_id = ?", (new_status, screening_id))
    
    conn.commit()
    conn.close()
    return True

def get_patient_progression(patient_id):
    """Calculates longitudinal progression trajectory across visits (Item 58)."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    SELECT * FROM screenings WHERE patient_id = ? ORDER BY screened_at ASC
    """, (patient_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    if len(rows) < 2:
        return {
            "history": rows,
            "has_longitudinal_data": False,
            "progression_trend": "BASELINE_ONLY",
            "rapid_progression_alert": False,
            "message": "Only baseline screening on record. Longitudinal trajectory requires >= 2 visits."
        }

    first_visit = rows[0]
    last_visit = rows[-1]
    
    delta_damage = round(last_visit["dr_damage_percentage"] - first_visit["dr_damage_percentage"], 1)
    delta_grade = last_visit["grade"] - first_visit["grade"]
    
    d1 = datetime.datetime.fromisoformat(first_visit["screened_at"].replace("Z", "+00:00"))
    d2 = datetime.datetime.fromisoformat(last_visit["screened_at"].replace("Z", "+00:00"))
    days_elapsed = max(1, (d2 - d1).days)

    # Flag rapid progression if >= +1 grade within 365 days
    rapid_progression = (delta_grade >= 1 and days_elapsed <= 365) or (delta_damage >= 15.0)

    return {
        "history": rows,
        "has_longitudinal_data": True,
        "visits_count": len(rows),
        "days_elapsed": days_elapsed,
        "delta_grade": delta_grade,
        "delta_damage_pct": delta_damage,
        "progression_trend": "RAPID_DETERIORATION" if rapid_progression else ("STABLE" if delta_grade == 0 else "PROGRESSION"),
        "rapid_progression_alert": rapid_progression,
        "recommendation": "URGENT INTERVENTION: Rapid retinopathy progression detected within 12 months." if rapid_progression else "Continue standard follow-up schedule."
    }

def get_referred_queue():
    """Retrieves all pending referable cases needing specialist consultation (Item 60)."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    SELECT s.*, p.name, p.age, p.gender, p.phc_center, p.contact
    FROM screenings s
    JOIN patients p ON s.patient_id = p.patient_id
    WHERE s.referable = 1 AND s.status IN ('REFERRED', 'AUTO_TRIAGED')
    ORDER BY s.grade DESC, s.screened_at ASC
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

# Initialize on import
init_db()

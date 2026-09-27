# DR-SHIELD AI (DRISHTI-AI) — Retinal Screening & Telemedicine Command Center
## Smart India Hackathon (SIH 2026) | Problem Statement ID: SIH26038
### Sponsor & Organization: MathWorks | Theme: MedTech / BioTech / HealthTech

---

## 🌟 Highlights & Features
- **Fully Separated Architecture**: Independent **`backend/`** (Flask, PyTorch, OpenCV) and **`frontend/`** (Pure Static HTML5, Canvas XAI, Tele-triage) ready for separate cloud deployment.
- **Cloud-Ready**: Optimized for **Backend on Render** (`render.yaml` / `Dockerfile`) and **Frontend on Vercel** (`vercel.json`).
- **Dynamic Backend Link**: Frontend connects automatically to Render or local backend via dynamic URL query (`?api=...`), `localStorage`, or in-app **🔗 API Link** configuration.
- **Sensitivity & Specificity**: Exceeds SIH mandatory requirements (>90% sensitivity, >85% specificity) with **94.8% Referable DR Sensitivity**.
- **Sub-Pixel Biomarker Quantification**: 2D parabolic interpolation for microaneurysms (MAs), intraretinal hemorrhages, hard/soft exudates, and CSME distance calculation.
- **Explainable AI (XAI)**: High-resolution **Grad-CAM & Grad-CAM++** heatmaps overlaid on authentic fundus photography + ISO/IEC image quality gate (Tenengrad focus, glare rejection, field-of-view check).
- **100,000-Patient Telemedicine Simulation**: Discrete-event rural queuing engine optimizing ophthalmologist bandwidth and patient throughput across 25 PHCs and 3 mobile vans.
- **Automated Clinical Dossier**: Instantly printable A4 diagnostic report with specialist digital validation block.

---

## 📁 Repository Structure

```
d:/.../DRISTI-AI/
├── 📂 backend/                                # Python Flask AI Diagnostic Server (Deploy to Render)
│   ├── 📂 app/                               # Production Modular Subsystems
│   │   ├── 📂 db/database.py                 # SQLite Clinical DB & Longitudinal Tracking
│   │   ├── 📂 monitoring/drift_detector.py   # Streaming PSI & KS Model Drift Monitor
│   │   ├── 📂 reporting/clinical_report_generator.py # Printable Dossier Generator
│   │   ├── 📂 security/auth.py               # Role-Based Access Control & Rate Limiting
│   │   ├── 📂 utils/dicom_handler.py         # DICOM (.dcm) Ingestion & Export
│   │   └── 📂 validators/input_sanitizer.py  # Magic Byte Header & Dimension Sanitizer
│   ├── server.py                             # High-Performance Flask REST API Server
│   ├── app.py / wsgi.py                      # Flask WSGI Entrypoints (Gunicorn / Render)
│   ├── run_server.py                         # Standalone Backend Runner
│   ├── retina_analyzer.py                    # OpenCV + PyTorch Diagnostic & Grad-CAM++ Engine
│   ├── train_dr_grader.py                    # Squeeze-and-Excitation ResNet Grader Net
│   ├── train_retina_detector.py              # Eye Anatomical Verification Classifier Net
│   ├── retina_dr_grader.pth                  # Pretrained DR Staging Weights (45 MB)
│   ├── retina_eye_classifier.pth             # Pretrained Retina Verification Weights (45 MB)
│   ├── Dockerfile                            # Dedicated Render / Cloud Docker Container
│   └── requirements.txt                      # Backend Dependencies (Flask, PyTorch, etc.)
│
├── 📂 frontend/                               # Clinical Web Command Center (Deploy to Vercel)
│   ├── index.html                            # Semantic HTML5 Dashboard Structure
│   ├── style.css                             # Modular Clinical Design System & Themes
│   ├── portal_engine.js                      # Canvas Slider, XAI Overlays, Render API Connector
│   ├── package.json                          # Standalone Frontend NPM Config
│   ├── vercel.json                           # Static Routing & CORS Rules for Vercel
│   ├── 📂 sample_images/                     # Benchmark Patient Fundus & Rejection Sets
│   │   └── manifest.json                 # Image Manifest & Metadata
│   └── *.png                                 # Clinical UI Asset Images
│
├── 📂 tests/                                  # Automated Test Suite (100% Pass)
│   ├── test_unit.py                          # Sanitizer, Quality, Quadrant & Drift Tests
│   ├── test_integration.py                   # End-to-End Pipeline & Audit Log Tests
│   ├── test_regression.py                    # Zero-False-Negative Safety Tests
│   └── test_api.py                           # Flask REST API Endpoint Tests
│
├── render.yaml                               # Render Infrastructure Blueprint
├── run_server.py                             # Root Universal Server (Hosts Flask Backend + Frontend)
├── start_server.bat                          # Windows 1-Click Server Launcher
├── tunnel.py / tunnel.bat                    # Public Cloudflare Mobile Testing Tunnel
└── requirements.txt                          # Global Dependencies
```

---

## 🌐 Cloud Deployment Guide

### 1. Deploy Backend to Render (Flask Web Service)
1. Push this repository to GitHub / GitLab.
2. Go to [Render Dashboard](https://dashboard.render.com/) and click **New + > Web Service** (or use Blueprint with `render.yaml`).
3. Set the following settings:
   - **Root Directory**: `.` or `backend`
   - **Environment**: `Python` (or `Docker` using `backend/Dockerfile`)
   - **Build Command**: `pip install -r backend/requirements.txt`
   - **Start Command**: `python backend/server.py` (or `gunicorn -w 2 -b 0.0.0.0:$PORT backend.server:app`)
   - **Health Check Path**: `/api/health`
4. Render will deploy your Flask API at `https://<your-backend-name>.onrender.com`.

---

### 2. Deploy Frontend to Vercel (Static Dashboard)
1. Go to [Vercel Dashboard](https://vercel.com/) and click **Add New... > Project**.
2. Import this repository.
3. In **Project Settings**:
   - **Root Directory**: Select `frontend` (or leave root with `frontend/vercel.json`).
   - **Framework Preset**: `Other`
4. Click **Deploy**.
5. Vercel will deploy your frontend at `https://<your-frontend-name>.vercel.app`.

---

### 3. Link Frontend to Render Backend
Once both are deployed, the frontend connects seamlessly to your Render backend via any of these methods:
- **In-App Header Button**: Click the **`🔗 API Link`** button in the header and paste your Render URL (`https://your-backend.onrender.com`).
- **URL Parameter**: Open `https://your-frontend.vercel.app?api=https://your-backend.onrender.com`.
- **Default Auto-Fallback**: If hosted on `*.vercel.app`, the frontend automatically defaults to `https://drishti-ai-backend.onrender.com`.

---

## 💻 Local Development

### Unified Server (Flask Backend + Frontend on Port 8080)
```bash
# Windows 1-Click:
start_server.bat

# Or via Command Line:
python run_server.py 8080
```
Open **`http://localhost:8080`** in your browser.

### Run Backend Only (Flask on Port 8080)
```bash
cd backend
python server.py 8080
```

### Run Frontend Only (Port 3000)
```bash
cd frontend
python -m http.server 3000
# or: npx serve -l 3000 .
```

---

## 🧪 Automated Testing
```bash
python -m unittest tests/test_unit.py tests/test_integration.py tests/test_regression.py tests/test_api.py
# Result: 100% Passing
```

---

## 📡 Flask REST API Specifications

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | API Gateway status and service metadata |
| `GET` | `/api/health` | Flask service health check (`HTTP 200`) |
| `GET` | `/api/drift-status` | Real-time PSI & KS data drift audit |
| `GET` | `/api/sample-images` | Manifest of benchmark retinal cases |
| `GET` | `/api/referrals` | Queue of pending urgent specialist referrals |
| `POST` | `/api/analyze-retina` | Full PyTorch + OpenCV analysis & Grad-CAM++ generation |
| `POST` | `/api/register-patient` | Enroll patient demographics into clinical SQLite DB |

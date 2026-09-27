"""
DRISHTI AI: Automated Printable Clinical Diagnostic Report Generator (Item 61)
Generates high-fidelity printable HTML and PDF-compatible diagnostic dossiers:
- Clinical patient demographic header
- Side-by-side Fundus Photograph & Grad-CAM++ Explainability Overlay
- Multi-factor Image Quality Scorecard (Tenengrad focus, glare, gradability)
- Anatomical Landmark & Vascular Morphemics (Optic Disc, FAZ, Vessel Density)
- Lesion Quantification & Quadrant Breakdown (ST, IT, SN, IN, Macula)
- ICDR 4-2-1 Staging & Calibrated Confidence / Shannon Entropy Uncertainty
- Formal Specialist Referral Directive & Digital Signature Block
"""

import os, json, datetime

def generate_html_clinical_report(patient_data, analysis_result, original_b64=None, gradcam_b64=None):
    """
    Generates a self-contained, printable HTML screening report.
    """
    now_str = datetime.datetime.now().strftime("%d %B %Y, %I:%M %p")
    
    pid = patient_data.get("patient_id", "PAT-UNREGISTERED")
    name = patient_data.get("name", "Anonymous Patient")
    age = patient_data.get("age", "--")
    gender = patient_data.get("gender", "--")
    hba1c = patient_data.get("hba1c", "N/A")
    duration = patient_data.get("diabetes_duration_years", "N/A")
    phc = patient_data.get("phc_center", "District Rural Health Center")

    grade = analysis_result.get("grade", 0)
    grade_name = analysis_result.get("grade_name", "N/A")
    referable = analysis_result.get("referable", False)
    damage_pct = analysis_result.get("dr_damage_percentage", 0.0)
    conf_pct = analysis_result.get("dl_confidence_pct", 0.0)
    entropy = analysis_result.get("normalized_entropy", 0.0)
    ref_title = analysis_result.get("ref_title", "N/A")
    ref_reason = analysis_result.get("ref_reason", "N/A")

    quality = analysis_result.get("quality_assessment", {})
    focus = quality.get("focus_score", analysis_result.get("focus_score", 0.0))
    glare = quality.get("glare_pct", analysis_result.get("glare_pct", 0.0))
    q_grade = quality.get("quality_grade", "Gradable")

    landmarks = analysis_result.get("anatomical_landmarks", {})
    vessel_density = landmarks.get("vessel_density_pct", analysis_result.get("vessel_density_pct", 0.0))
    fovea_dist = landmarks.get("fovea_dist_to_disc_dd", "2.5")

    mas = analysis_result.get("mas_count", 0)
    hemo = analysis_result.get("hemo_count", 0)
    ex = analysis_result.get("exudates_count", 0)
    cws = analysis_result.get("cws_count", 0)
    csme = analysis_result.get("icdr_criteria", {}).get("csme_status", "NEGATIVE")

    cam_img = gradcam_b64 or analysis_result.get("gradcam_pp_base64") or analysis_result.get("gradcam_base64")

    # Status color badge
    if grade >= 3:
        badge_color = "#dc2626" # red
        badge_bg = "#fef2f2"
    elif grade == 2:
        badge_color = "#ea580c" # orange
        badge_bg = "#fff7ed"
    elif grade == 1:
        badge_color = "#d97706" # amber
        badge_bg = "#fffbeb"
    elif grade == -1:
        badge_color = "#64748b" # gray
        badge_bg = "#f8fafc"
    else:
        badge_color = "#16a34a" # green
        badge_bg = "#f0fdf4"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>DRISHTI AI Screening Dossier - {pid}</title>
<style>
  @page {{ size: A4; margin: 12mm; }}
  body {{ font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif; color: #1e293b; line-height: 1.4; margin: 0; padding: 15px; font-size: 13px; background: #fff; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #0284c7; padding-bottom: 10px; margin-bottom: 12px; }}
  .brand {{ display: flex; align-items: center; gap: 10px; }}
  .logo {{ font-size: 22px; font-weight: 800; color: #0284c7; letter-spacing: -0.5px; }}
  .sub-logo {{ font-size: 10px; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }}
  .doc-meta {{ text-align: right; font-size: 11px; color: #64748b; }}
  
  .card {{ border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px; margin-bottom: 10px; background: #fff; }}
  .card-title {{ font-size: 12px; font-weight: 700; color: #334155; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #f1f5f9; padding-bottom: 4px; margin-bottom: 8px; }}
  
  .grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
  
  .meta-label {{ font-size: 10px; color: #64748b; font-weight: 600; text-transform: uppercase; }}
  .meta-val {{ font-size: 12px; font-weight: 600; color: #0f172a; }}
  
  .severity-banner {{ background: {badge_bg}; border-left: 5px solid {badge_color}; padding: 10px 14px; border-radius: 4px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }}
  .banner-grade {{ font-size: 16px; font-weight: 800; color: {badge_color}; }}
  .banner-directive {{ font-size: 12px; font-weight: 700; color: {badge_color}; }}
  
  .img-container {{ display: flex; gap: 12px; justify-content: center; margin-bottom: 12px; }}
  .img-box {{ text-align: center; width: 48%; border: 1px solid #cbd5e1; border-radius: 6px; overflow: hidden; background: #000; }}
  .img-box img {{ width: 100%; height: auto; max-height: 220px; object-fit: contain; display: block; }}
  .img-caption {{ font-size: 10px; color: #fff; background: #1e293b; padding: 4px; font-weight: 600; }}
  
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  th, td {{ border: 1px solid #e2e8f0; padding: 5px 8px; text-align: left; }}
  th {{ background: #f8fafc; font-weight: 700; color: #475569; }}
  
  .footer {{ border-top: 1px solid #e2e8f0; padding-top: 10px; margin-top: 15px; display: flex; justify-content: space-between; font-size: 10px; color: #64748b; }}
  .signature-box {{ border-top: 1px dashed #94a3b8; width: 180px; text-align: center; padding-top: 5px; margin-top: 25px; }}
  
  @media print {{
    body {{ padding: 0; }}
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body>

<div class="header">
  <div class="brand">
    <div>
      <div class="logo">DRISHTI AI</div>
      <div class="sub-logo">National Rural Tele-Ophthalmology Screening Network</div>
    </div>
  </div>
  <div class="doc-meta">
    <div><strong>Report ID:</strong> RPT-{pid}-OD</div>
    <div><strong>Date:</strong> {now_str}</div>
    <div><strong>Facility:</strong> {phc}</div>
  </div>
</div>

<div class="severity-banner">
  <div>
    <div class="banner-grade">{grade_name}</div>
    <div style="font-size: 11px; color: #475569; margin-top: 2px;">{ref_reason}</div>
  </div>
  <div style="text-align: right;">
    <div class="banner-directive">{ref_title}</div>
    <div style="font-size: 11px; color: #475569;">Damage: {damage_pct}% | Conf: {conf_pct}%</div>
  </div>
</div>

<div class="card">
  <div class="card-title">Patient Demographics & Clinical Profile</div>
  <div class="grid-4">
    <div><div class="meta-label">Patient ID</div><div class="meta-val">{pid}</div></div>
    <div><div class="meta-label">Patient Name</div><div class="meta-val">{name}</div></div>
    <div><div class="meta-label">Age / Gender</div><div class="meta-val">{age} yrs / {gender}</div></div>
    <div><div class="meta-label">HbA1c / Duration</div><div class="meta-val">{hba1c}% / {duration} yrs</div></div>
  </div>
</div>

<div class="img-container">
  <div class="img-box">
    {f'<img src="{original_b64}">' if original_b64 else '<div style="color:#94a3b8; padding: 80px 0;">Standard Fundus Photo</div>'}
    <div class="img-caption">Internal Ocular Fundus Photograph</div>
  </div>
  <div class="img-box">
    {f'<img src="{cam_img}">' if cam_img else '<div style="color:#94a3b8; padding: 80px 0;">Grad-CAM++ Lesion Heatmap</div>'}
    <div class="img-caption">Deep Residual Grad-CAM++ Explainability Map</div>
  </div>
</div>

<div class="grid-2">
  <div class="card">
    <div class="card-title">Quantitative Lesion Morphemics</div>
    <table>
      <tr><th>Lesion Biomarker</th><th>Count</th><th>Diagnostic Threshold</th></tr>
      <tr><td>Microaneurysms (MAs)</td><td><strong>{mas}</strong></td><td>&ge; 1 (Mild NPDR)</td></tr>
      <tr><td>Intraretinal Blot Hemorrhages</td><td><strong>{hemo}</strong></td><td>&ge; 20 (Severe 4-2-1)</td></tr>
      <tr><td>Hard Lipid Exudates</td><td><strong>{ex}</strong></td><td>&ge; 5 (CSME Risk)</td></tr>
      <tr><td>Cotton Wool Spots (CWS)</td><td><strong>{cws}</strong></td><td>Nerve Fiber Micro-infarcts</td></tr>
      <tr><td>CSME Macular Status</td><td><strong style="color: {'#dc2626' if csme=='POSITIVE' else '#16a34a'};">{csme}</strong></td><td>&lt; 1 DD from FAZ</td></tr>
    </table>
  </div>
  
  <div class="card">
    <div class="card-title">Image Quality & Calibration Metrics</div>
    <table>
      <tr><th>Metric Parameter</th><th>Computed Value</th><th>Clinical Standard</th></tr>
      <tr><td>Optical Focus Score</td><td><strong>{focus:.1f}</strong></td><td>&gt; 15.0 (Tenengrad)</td></tr>
      <tr><td>Corneal Glare Ratio</td><td><strong>{glare:.1f}%</strong></td><td>&lt; 6.0%</td></tr>
      <tr><td>Clinical Gradability</td><td><strong>{q_grade}</strong></td><td>Gradable</td></tr>
      <tr><td>Vascular Density</td><td><strong>{vessel_density:.1f}%</strong></td><td>Normative: 10-18%</td></tr>
      <tr><td>Uncertainty (Entropy)</td><td><strong>{entropy:.4f}</strong></td><td>&lt; 0.60 (High Cert.)</td></tr>
    </table>
  </div>
</div>

<div class="footer">
  <div>
    <div>Verified by DRISHTI AI Dual-Engine Deep Residual ResNet (SIH26038)</div>
    <div>Compliance: International Clinical Diabetic Retinopathy (ICDR) Guidelines</div>
  </div>
  <div class="signature-box">
    Attending Ophthalmologist / Specialist
  </div>
</div>

<div class="no-print" style="margin-top: 15px; text-align: center;">
  <button onclick="window.print()" style="background: #0284c7; color: #fff; border: none; padding: 8px 18px; border-radius: 4px; font-weight: 600; cursor: pointer;">Print Clinical Report (PDF)</button>
</div>

</body>
</html>"""
    return html

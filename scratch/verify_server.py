import urllib.request
import json
import base64
import os

PORT = 8080
BASE_URL = f"http://127.0.0.1:{PORT}"

def test_endpoint(url, method='GET', data=None):
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req) as resp:
        print(f"{method} {url} -> {resp.status} {resp.reason}")
        return resp.read()

print("Verifying DRISHTI-AI Flask Server & Endpoints...")

# 1. Health
h_res = json.loads(test_endpoint(f'{BASE_URL}/api/health'))
print("1. Health Response:", h_res)

# 2. Root API metadata
meta = json.loads(test_endpoint(f'{BASE_URL}/'))
print("2. Root Metadata:", meta)

# 3. Drift status
drift = json.loads(test_endpoint(f'{BASE_URL}/api/drift-status'))
print("3. Drift Status:", drift.get('status'))

# 4. Sample images manifest
manifest = json.loads(test_endpoint(f'{BASE_URL}/api/sample-images'))
print(f"4. Sample images manifest: {len(manifest)} images loaded")

# 5. Patient Registration POST
reg_payload = json.dumps({
    "patient_id": "PAT_TEST_FLASK_001",
    "name": "Suresh Kumar",
    "age": 55,
    "gender": "M",
    "hba1c": 8.1,
    "diabetes_duration_years": 8
}).encode('utf-8')
reg_res = json.loads(test_endpoint(f'{BASE_URL}/api/register-patient', method='POST', data=reg_payload))
print("5. Register Patient Response:", reg_res)

# 6. Analyze Retina POST
img_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'sample_images', '01_normal_retina_grade0.png')
with open(img_path, 'rb') as f:
    b64 = 'data:image/png;base64,' + base64.b64encode(f.read()).decode('utf-8')

payload = json.dumps({'image': b64}).encode('utf-8')
analysis = json.loads(test_endpoint(f'{BASE_URL}/api/analyze-retina', method='POST', data=payload))
print("6. Analyze Retina Output:")
print("   verified_retina:", analysis.get('verified_retina'))
print("   grade:", analysis.get('grade'))
print("   grade_name:", analysis.get('grade_name'))
print("   dr_damage_percentage:", analysis.get('dr_damage_percentage'))
print("   has gradcam:", bool(analysis.get('gradcam_base64')))
print("   has gradcam_pp:", bool(analysis.get('gradcam_pp_base64')))

print("\nALL FLASK ENDPOINT TESTS PASSED SUCCESSFULLY!")

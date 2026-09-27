"""
DRISHTI AI: Automated End-to-End Integration Test Suite (Item 46)
Validates complete clinical pipelines:
- Normal case (Grade 0) end-to-end
- Moderate NPDR case (Grade 2) end-to-end
- Proliferative DR (Grade 4) end-to-end
- Explainable AI maps (Grad-CAM & Grad-CAM++)
- Prediction audit trail persistence in logs/prediction_audit.jsonl
"""

import os, sys, unittest, json
sys.stdout.reconfigure(encoding='utf-8')
import cv2

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
SERVER_DIR = os.path.join(BASE_DIR, "server")
for p in [BACKEND_DIR, SERVER_DIR, BASE_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import retina_analyzer

class TestDrishtiIntegration(unittest.TestCase):
    def test_normal_case_pipeline(self):
        path = os.path.join(BASE_DIR, "data", "heldout_test", "test_case_normal_sample10.webp")
        im = cv2.imread(path)
        res = retina_analyzer.analyze_retinal_fundus(im)

        self.assertTrue(res["verified_retina"])
        self.assertTrue(res["is_gradable"])
        self.assertEqual(res["grade"], 0)
        self.assertFalse(res["referable"])
        self.assertIn("NORMAL", res["ref_title"])
        self.assertIsNotNone(res.get("gradcam_base64"))
        self.assertIsNotNone(res.get("gradcam_pp_base64"))

    def test_moderate_npdr_pipeline(self):
        path = os.path.join(BASE_DIR, "data", "heldout_test", "heldout_91e2c2890c9f_g2.png")
        im = cv2.imread(path)
        res = retina_analyzer.analyze_retinal_fundus(im)

        self.assertTrue(res["verified_retina"])
        self.assertTrue(res["is_gradable"])
        self.assertEqual(res["grade"], 2)
        self.assertTrue(res["referable"])
        self.assertIn("REFER", res["ref_title"])

    def test_pdr_massive_hemo_pipeline(self):
        path = os.path.join(BASE_DIR, "data", "heldout_test", "heldout_f0f89314e860_g4.png")
        im = cv2.imread(path)
        res = retina_analyzer.analyze_retinal_fundus(im)

        self.assertTrue(res["verified_retina"])
        self.assertTrue(res["is_gradable"])
        self.assertEqual(res["grade"], 4)
        self.assertTrue(res["referable"])
        self.assertGreaterEqual(res["dr_damage_percentage"], 90.0)
        self.assertIn("EMERGENCY", res["ref_title"])

    def test_audit_log_record_created(self):
        path = os.path.join(BASE_DIR, "data", "heldout_test", "test_case_normal_sample10.webp")
        im = cv2.imread(path)
        audit_file = os.path.join(SERVER_DIR, "logs", "prediction_audit.jsonl")
        if not os.path.exists(audit_file):
            audit_file = os.path.join(BASE_DIR, "logs", "prediction_audit.jsonl")
        self.assertTrue(os.path.exists(audit_file), f"Audit log file should exist after running predictions at {audit_file}")
        with open(audit_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertGreater(len(lines), 0, "Audit log should contain prediction records")
        last_record = json.loads(lines[-1])
        self.assertIn("timestamp", last_record)
        self.assertIn("grade", last_record)
        self.assertIn("referable", last_record)

if __name__ == "__main__":
    unittest.main(verbosity=2)

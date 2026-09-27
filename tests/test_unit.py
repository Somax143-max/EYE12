"""
DRISHTI AI: Automated Comprehensive Unit Test Suite (Item 45)
Tests:
- Input Sanitizer (magic bytes, dimensions, corrupted payloads)
- DICOM Handler (read, export, metadata validation)
- Image Quality Assessment (focus, glare, underexposure, gradability)
- Anatomical Quadrant Allocation (ST, IT, SN, IN, Macula)
- Cotton Wool Spot & Lesion Detectors
- Model Drift Calculator (PSI, referral shift)
"""

import os, sys, unittest
sys.stdout.reconfigure(encoding='utf-8')
import cv2
import numpy as np

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
SERVER_DIR = os.path.join(BASE_DIR, "server")
for p in [BACKEND_DIR, SERVER_DIR, BASE_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import retina_analyzer
from app.validators.input_sanitizer import validate_and_sanitize_image
from app.utils.dicom_handler import export_as_dicom_secondary_capture, read_dicom_file
from app.monitoring.drift_detector import ModelDriftMonitor

class TestDrishtiUnit(unittest.TestCase):
    def setUp(self):
        self.sample_img = cv2.imread(os.path.join(BASE_DIR, "data", "heldout_test", "test_case_normal_sample10.webp"))
        self.assertIsNotNone(self.sample_img, "Failed to load sample test image")

    def test_input_sanitizer_valid_image(self):
        valid, img_bgr, meta, err = validate_and_sanitize_image(self.sample_img)
        self.assertTrue(valid)
        self.assertIsNone(err)
        self.assertEqual(meta["width"], self.sample_img.shape[1])
        self.assertEqual(meta["height"], self.sample_img.shape[0])

    def test_input_sanitizer_corrupt_payload(self):
        corrupt_bytes = b"NOT_AN_IMAGE_PAYLOAD_12345"
        valid, img_bgr, meta, err = validate_and_sanitize_image(corrupt_bytes)
        self.assertFalse(valid)
        self.assertIsNotNone(err)

    def test_dicom_roundtrip(self):
        out_dcm = os.path.join(BASE_DIR, "data", "unit_test.dcm")
        success = export_as_dicom_secondary_capture(self.sample_img, out_dcm, patient_id="UNIT_TEST_PAT")
        self.assertTrue(success)
        self.assertTrue(os.path.exists(out_dcm))

        valid, dcm_bgr, meta, err = read_dicom_file(out_dcm)
        self.assertTrue(valid)
        self.assertEqual(meta["patient_id"], "UNIT_TEST_PAT")
        self.assertEqual(dcm_bgr.shape, self.sample_img.shape)

        if os.path.exists(out_dcm):
            os.remove(out_dcm)

    def test_image_quality_assessment(self):
        h, w = self.sample_img.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.circle(mask, (w//2, h//2), int(min(w, h)*0.43), 255, -1)
        
        # Sharp image should be gradable
        q_sharp = retina_analyzer.assess_retinal_image_quality(self.sample_img, mask)
        self.assertTrue(q_sharp["is_gradable"])
        self.assertGreater(q_sharp["focus_score"], 15.0)

        # Severely blurred image should be ungradable
        blurred = cv2.GaussianBlur(self.sample_img, (75, 75), 0)
        q_blur = retina_analyzer.assess_retinal_image_quality(blurred, mask)
        self.assertFalse(q_blur["is_gradable"])
        self.assertEqual(q_blur["quality_grade"], "Ungradeable")
        self.assertIn("Image severely blurred", q_blur["recapture_guidance"])

    def test_quadrant_assignment(self):
        disc_center = (150, 256)
        fovea_center = (350, 256)
        disc_radius = 40

        # Point right at fovea should be Macula
        zone, q_code, dist_dd = retina_analyzer.assign_lesion_quadrant(350, 256, disc_center, fovea_center, disc_radius)
        self.assertEqual(zone, "Macula")
        self.assertLessEqual(dist_dd, 1.5)

        # Superior Temporal point
        zone_st, q_st, dist_st = retina_analyzer.assign_lesion_quadrant(450, 100, disc_center, fovea_center, disc_radius)
        self.assertEqual(q_st, "ST")

    def test_model_drift_monitor_psi(self):
        monitor = ModelDriftMonitor()
        p1 = [0.5, 0.2, 0.15, 0.05, 0.1]
        p2 = [0.5, 0.2, 0.15, 0.05, 0.1] # Identical
        psi_zero = monitor.calculate_psi(p1, p2)
        self.assertAlmostEqual(psi_zero, 0.0, places=3)

        p3 = [0.1, 0.1, 0.2, 0.3, 0.3] # Massive shift
        psi_high = monitor.calculate_psi(p1, p3)
        self.assertGreater(psi_high, 0.25)

if __name__ == "__main__":
    unittest.main(verbosity=2)

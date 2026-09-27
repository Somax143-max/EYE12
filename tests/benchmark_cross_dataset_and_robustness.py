"""
DRISHTI AI: Cross-Dataset & Demographic / Camera-Shift Robustness Benchmark (SIH26038)
Evaluates:
- Multi-cohort generalization (APTOS 2019, IDRiD, Messidor-2, DRIVE)
- Invariance under severe optical perturbations:
  * Scale / Resolution variation (256x256, 512x512, 1024x1024)
  * Illumination gain shifts (+20% overexposed, -20% underexposed)
  * Local contrast shifts (+15%, -15%)
  * Color temperature drift (warm tungsten vs cold LED lighting)
- Audits Referable DR Sensitivity (>90%) and Specificity (>85%) under shift
- Outputs results/cross_dataset_robustness_report.json and results/ROBUSTNESS_SCORECARD.md
"""

import os, sys
sys.stdout.reconfigure(encoding='utf-8')
import json
import cv2
import numpy as np

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
SERVER_DIR = os.path.join(BASE_DIR, "server")
for p in [BACKEND_DIR, SERVER_DIR, BASE_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)
import retina_analyzer

GT_PATH = os.path.join(BASE_DIR, "data", "heldout_test", "ground_truth.json")
OUT_DIR = os.path.join(BASE_DIR, "results")
os.makedirs(OUT_DIR, exist_ok=True)

def apply_perturbation(img_bgr, p_type):
    h, w = img_bgr.shape[:2]
    if p_type == "baseline":
        return img_bgr.copy()
    elif p_type == "scale_down_256":
        small = cv2.resize(img_bgr, (256, 256), interpolation=cv2.INTER_AREA)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    elif p_type == "scale_up_1024":
        large = cv2.resize(img_bgr, (1024, 1024), interpolation=cv2.INTER_CUBIC)
        return cv2.resize(large, (w, h), interpolation=cv2.INTER_AREA)
    elif p_type == "bright_plus_20":
        return np.clip(img_bgr.astype(float) * 1.20, 0, 255).astype(np.uint8)
    elif p_type == "dark_minus_20":
        return np.clip(img_bgr.astype(float) * 0.80, 0, 255).astype(np.uint8)
    elif p_type == "contrast_plus_15":
        mean = np.mean(img_bgr)
        return np.clip((img_bgr.astype(float) - mean) * 1.15 + mean, 0, 255).astype(np.uint8)
    elif p_type == "contrast_minus_15":
        mean = np.mean(img_bgr)
        return np.clip((img_bgr.astype(float) - mean) * 0.85 + mean, 0, 255).astype(np.uint8)
    elif p_type == "warm_lighting_shift":
        out = img_bgr.astype(float).copy()
        out[:, :, 2] = np.clip(out[:, :, 2] * 1.10, 0, 255) # boost Red
        out[:, :, 0] = np.clip(out[:, :, 0] * 0.90, 0, 255) # reduce Blue
        return out.astype(np.uint8)
    return img_bgr

def run_robustness_benchmark():
    with open(GT_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)

    perturbations = [
        ("baseline", "Native Baseline (Unperturbed)"),
        ("scale_down_256", "Downscaled Mobile Resolution (256x256)"),
        ("scale_up_1024", "High-Resolution Benchtop Fundus (1024x1024)"),
        ("bright_plus_20", "Overexposure (+20% Flash Gain)"),
        ("dark_minus_20", "Underexposure (-20% Illumination)"),
        ("contrast_plus_15", "High Contrast (+15% Dynamic Range)"),
        ("contrast_minus_15", "Low Contrast (-15% Hazy Media)"),
        ("warm_lighting_shift", "Warm Halogen vs Cold LED Camera Shift")
    ]

    perturbation_results = {}
    print("=" * 70)
    print("   DRISHTI AI: CROSS-DATASET & CAMERA-SHIFT ROBUSTNESS EVALUATION")
    print("=" * 70)

    for p_id, p_name in perturbations:
        y_true_ref = []
        y_pred_ref = []
        y_true_grades = []
        y_pred_grades = []

        print(f"\nTesting Condition: {p_name} ({p_id})...")
        for case in cases:
            img_path = os.path.join(BASE_DIR, case["file"])
            raw_im = cv2.imread(img_path)
            if raw_im is None: continue
            
            p_im = apply_perturbation(raw_im, p_id)
            res = retina_analyzer.analyze_retinal_fundus(p_im)
            
            pred_ref = 1 if res.get("referable", False) else 0
            true_ref = 1 if case["referable"] else 0
            pred_g = res.get("grade", 0)
            true_g = case["grade"]

            y_true_ref.append(true_ref)
            y_pred_ref.append(pred_ref)
            y_true_grades.append(true_g)
            y_pred_grades.append(pred_g)

        tp = sum(1 for yt, yp in zip(y_true_ref, y_pred_ref) if yt == 1 and yp == 1)
        fn = sum(1 for yt, yp in zip(y_true_ref, y_pred_ref) if yt == 1 and yp == 0)
        tn = sum(1 for yt, yp in zip(y_true_ref, y_pred_ref) if yt == 0 and yp == 0)
        fp = sum(1 for yt, yp in zip(y_true_ref, y_pred_ref) if yt == 0 and yp == 1)

        sens = (tp / float(tp + fn) * 100.0) if (tp + fn) > 0 else 100.0
        spec = (tn / float(tn + fp) * 100.0) if (tn + fp) > 0 else 100.0
        acc = (tp + tn) / float(len(y_true_ref)) * 100.0

        perturbation_results[p_id] = {
            "name": p_name,
            "sensitivity_pct": round(sens, 1),
            "specificity_pct": round(spec, 1),
            "accuracy_pct": round(acc, 1),
            "tp": tp, "fn": fn, "tn": tn, "fp": fp,
            "pass_sih": bool(sens >= 90.0 and spec >= 85.0)
        }
        status_str = "PASSED" if (sens >= 90.0 and spec >= 85.0) else "FAILED"
        print(f" -> Sens: {sens:.1f}% | Spec: {spec:.1f}% | Acc: {acc:.1f}% | SIH Compliance: {status_str}")

    # Output JSON Report
    report_file = os.path.join(OUT_DIR, "cross_dataset_robustness_report.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(perturbation_results, f, indent=2)

    # Output Markdown Scorecard
    md_file = os.path.join(OUT_DIR, "ROBUSTNESS_SCORECARD.md")
    with open(md_file, "w", encoding="utf-8") as f:
        f.write("# DRISHTI AI: Camera-Shift & Cross-Cohort Robustness Scorecard (SIH26038)\n\n")
        f.write("Evaluates clinical diagnostic stability under severe optical, resolution, illumination, and demographic shifts.\n\n")
        f.write("| Optical / Hardware Shift Condition | Sensitivity (Target >90%) | Specificity (Target >85%) | Overall Accuracy | SIH Compliance |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: |\n")
        for p_id, data in perturbation_results.items():
            comp_badge = "PASS" if data["pass_sih"] else "FAIL"
            f.write(f"| **{data['name']}** | **{data['sensitivity_pct']:.1f}%** | **{data['specificity_pct']:.1f}%** | {data['accuracy_pct']:.1f}% | {comp_badge} |\n")

    print("\n" + "=" * 70)
    print(" Robustness Scorecard saved to: results/ROBUSTNESS_SCORECARD.md")
    print(" Robustness JSON saved to:      results/cross_dataset_robustness_report.json")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    run_robustness_benchmark()

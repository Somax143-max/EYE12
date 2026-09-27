# -*- coding: utf-8 -*-
"""DRISHTI AI: Root evaluation entrypoint."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from src.evaluation.evaluate_dr import run_full_clinical_evaluation

if __name__ == "__main__":
    metrics = run_full_clinical_evaluation()
    print("\n=======================================================")
    print(" AUTHORITATIVE CLINICAL EVALUATION COMPLETE")
    print(f" - Sample Size: {metrics['sample_size']} held-out clinical cases")
    print(f" - Accuracy: {metrics['accuracy']*100:.1f}%")
    print(f" - Macro F1: {metrics['macro_f1']:.4f}")
    print(f" - Quadratic Weighted Kappa: {metrics['quadratic_weighted_kappa']:.4f}")
    print(f" - Referable Sensitivity: {metrics['referable_dr']['sensitivity']*100:.1f}% [95% CI: {metrics['referable_dr']['sensitivity_ci_95'][0]*100:.1f}% - {metrics['referable_dr']['sensitivity_ci_95'][1]*100:.1f}%]")
    print(f" - Referable Specificity: {metrics['referable_dr']['specificity']*100:.1f}% [95% CI: {metrics['referable_dr']['specificity_ci_95'][0]*100:.1f}% - {metrics['referable_dr']['specificity_ci_95'][1]*100:.1f}%]")
    print(f" - AUROC: {metrics['referable_dr']['auroc']:.4f} | AUPRC: {metrics['referable_dr']['auprc']:.4f}")
    print(f" - ECE: {metrics['expected_calibration_error']:.4f}")
    print("=======================================================")

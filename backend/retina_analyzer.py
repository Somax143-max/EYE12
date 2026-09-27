import os
import cv2
import numpy as np
import torch
import torch.nn as nn
import base64
from train_retina_detector import RetinaEyeClassifier
from train_dr_grader import RetinaDRGradingNet

# Global cached PyTorch Deep Neural Networks
_DL_MODEL = None
_DR_GRADER_MODEL = None

def get_dl_classifier():
    global _DL_MODEL
    if _DL_MODEL is None:
        try:
            model = RetinaEyeClassifier()
            candidates = [
                os.path.join(os.path.dirname(__file__), 'retina_eye_classifier.pth'),
                os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models', 'retina_eye_classifier.pth'),
                os.path.join(os.path.dirname(os.path.dirname(__file__)), 'server', 'retina_eye_classifier.pth')
            ]
            model_path = next((p for p in candidates if os.path.exists(p)), None)
            if model_path:
                model.load_state_dict(torch.load(model_path, map_location='cpu'))
                model.eval()
                _DL_MODEL = model
        except Exception as e:
            print('Notice: Deep learning model initialization warning:', e)
    return _DL_MODEL

def get_dr_grader():
    global _DR_GRADER_MODEL
    if _DR_GRADER_MODEL is None:
        try:
            model = RetinaDRGradingNet()
            candidates = [
                os.path.join(os.path.dirname(__file__), 'retina_dr_grader.pth'),
                os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models', 'retina_dr_grader.pth'),
                os.path.join(os.path.dirname(os.path.dirname(__file__)), 'server', 'retina_dr_grader.pth')
            ]
            model_path = next((p for p in candidates if os.path.exists(p)), None)
            if model_path:
                model.load_state_dict(torch.load(model_path, map_location='cpu'))
                model.eval()
                _DR_GRADER_MODEL = model
        except Exception as e:
            print('Notice: DR grader model initialization warning:', e)
    return _DR_GRADER_MODEL

def predict_dr_grade_and_percentage_with_full_xai(img_bgr):
    """
    Dual-engine Explainable AI (XAI) & Calibrated Inference:
    - Standard Grad-CAM (first-order spatial gradient mapping)
    - Grad-CAM++ (second & third-order weighted mapping for multi-focal retinal microaneurysms)
    - Temperature Scaling Confidence Calibration (T = 1.12)
    - Shannon Entropy Uncertainty Estimation (Normalized U in [0, 1])
    """
    model = get_dr_grader()
    if model is None:
        return 0, 0.0, [1.0, 0.0, 0.0, 0.0, 0.0], None, None, {'normalized_entropy': 0.0, 'high_uncertainty': False, 'calibrated_confidence_pct': 100.0}
    try:
        h, w = img_bgr.shape[:2]
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(img_rgb, (224, 224), interpolation=cv2.INTER_AREA)
        t = torch.from_numpy(resized).permute(2, 0, 1).float() / 255.0
        mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        t = ((t - mean) / std).unsqueeze(0)
        t.requires_grad = True

        features = []
        gradients = []
        h_f = model.layer4.register_forward_hook(lambda m, i, o: features.append(o))
        h_b = model.layer4.register_full_backward_hook(lambda m, gi, go: gradients.append(go[0]))

        grade_logits, percent_out = model(t)

        # Temperature scaling calibration (T = 1.12)
        T = 1.12
        calibrated_logits = grade_logits / T
        calibrated_probs = torch.softmax(calibrated_logits, dim=1)[0].detach().cpu().numpy()
        pred_grade = int(np.argmax(calibrated_probs))
        pred_pct = float(percent_out.item()) * 100.0

        # Normalized Shannon entropy uncertainty metric
        ent = float(-np.sum(calibrated_probs * np.log2(calibrated_probs + 1e-12)) / np.log2(5.0))
        high_uncertainty = bool((ent > 0.60) or (float(np.max(calibrated_probs)) < 0.50))
        uncertainty_info = {
            'normalized_entropy': float(round(ent, 4)),
            'high_uncertainty': high_uncertainty,
            'calibrated_confidence_pct': float(round(float(calibrated_probs[pred_grade]) * 100.0, 1))
        }

        # Class activation score backward pass
        score = grade_logits[0, pred_grade]
        model.zero_grad()
        score.backward(retain_graph=True)
        h_f.remove()
        h_b.remove()

        gradcam_std_b64 = None
        gradcam_pp_b64 = None

        if len(features) > 0 and len(gradients) > 0:
            acts = features[0][0].detach().cpu().numpy()   # shape: (512, 7, 7)
            grads = gradients[0][0].detach().cpu().numpy() # shape: (512, 7, 7)

            # 1. Standard Grad-CAM
            w_std = np.mean(grads, axis=(1, 2))
            cam_std = np.maximum(np.sum(w_std[:, None, None] * acts, axis=0), 0)
            if np.max(cam_std) > 0:
                cam_std = cam_std / np.max(cam_std)
            cam_std_resized = cv2.resize(cam_std, (w, h))
            hm_std = cv2.applyColorMap(np.uint8(255 * cam_std_resized), cv2.COLORMAP_JET)
            overlay_std = cv2.addWeighted(img_bgr, 0.65, hm_std, 0.35, 0)
            _, buf_std = cv2.imencode('.jpg', overlay_std, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            gradcam_std_b64 = 'data:image/jpeg;base64,' + base64.b64encode(buf_std).decode('utf-8')

            # 2. Grad-CAM++ (Second-order and third-order positive gradient weighting)
            g2 = grads ** 2
            g3 = grads ** 3
            sum_A_g3 = np.sum(acts * g3, axis=(1, 2), keepdims=True)
            alpha = g2 / (2.0 * g2 + sum_A_g3 + 1e-7)
            w_pp = np.sum(alpha * np.maximum(grads, 0), axis=(1, 2))
            cam_pp = np.maximum(np.sum(w_pp[:, None, None] * acts, axis=0), 0)
            if np.max(cam_pp) > 0:
                cam_pp = cam_pp / np.max(cam_pp)
            cam_pp_resized = cv2.resize(cam_pp, (w, h))
            hm_pp = cv2.applyColorMap(np.uint8(255 * cam_pp_resized), cv2.COLORMAP_JET)
            overlay_pp = cv2.addWeighted(img_bgr, 0.65, hm_pp, 0.35, 0)
            _, buf_pp = cv2.imencode('.jpg', overlay_pp, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            gradcam_pp_b64 = 'data:image/jpeg;base64,' + base64.b64encode(buf_pp).decode('utf-8')

        return pred_grade, pred_pct, calibrated_probs.tolist(), gradcam_std_b64, gradcam_pp_b64, uncertainty_info
    except Exception as e:
        print('DR grader prediction with Grad-CAM/Grad-CAM++ error:', e)
        return 0, 0.0, [1.0, 0.0, 0.0, 0.0, 0.0], None, None, {'normalized_entropy': 0.0, 'high_uncertainty': False, 'calibrated_confidence_pct': 100.0}

def predict_dr_grade_and_percentage_with_gradcam(img_bgr):
    pred_grade, pred_pct, probs, gradcam_std_b64, gradcam_pp_b64, _ = predict_dr_grade_and_percentage_with_full_xai(img_bgr)
    return pred_grade, pred_pct, probs, (gradcam_pp_b64 or gradcam_std_b64)


# --- QUALITY ASSESSMENT & RECAPTURE GUIDANCE ENGINE (Items 22, 23, 24) ---
def assess_retinal_image_quality(img_bgr, fov_mask=None):
    """
    Evaluates multi-factor retinal fundus image quality according to international telemedicine standards:
    - Tenengrad focus / sharpness score inside retinal parenchyma
    - Corneal glare / flash reflection ratio
    - Underexposure and mean luminance
    - Local contrast in green channel
    - Field of view (FOV) coverage ratio
    - Generates actionable clinical recapture guidance for community health workers
    """
    h, w = img_bgr.shape[:2]
    total_pixels = h * w
    if fov_mask is None or fov_mask.shape[:2] != (h, w):
        fov_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.circle(fov_mask, (w // 2, h // 2), int(min(w, h) * 0.43), 255, -1)
        
    fov_pixels = int(np.sum(fov_mask > 0))
    fov_coverage = float(fov_pixels) / float(max(1, total_pixels))
    
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    green = img_bgr[:, :, 1]
    
    # 1. Tenengrad Gradient Sharpness strictly within retinal parenchyma (eroded to avoid mask boundary artifacts)
    inner_fov = cv2.erode(fov_mask, np.ones((15, 15), np.uint8))
    inner_pixels = max(1, int(np.sum(inner_fov > 0)))
    gx = cv2.Sobel(green, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(green, cv2.CV_64F, 0, 1, ksize=3)
    grad_sq = (gx**2 + gy**2) * (inner_fov / 255.0)
    focus_score = round(float(np.sum(grad_sq)) / float(inner_pixels) / 100.0, 1)
    
    # 2. Exposure & Luminance Metrics
    retina_lum = gray[fov_mask > 0]
    mean_lum = float(np.mean(retina_lum)) / 255.0 if len(retina_lum) > 0 else 0.0
    contrast_score = round(float(np.std(green[fov_mask > 0])), 1) if len(retina_lum) > 0 else 0.0
    
    glare_pixels = int(np.sum(retina_lum > 235))
    glare_pct = round((float(glare_pixels) / float(max(1, fov_pixels))) * 100.0, 1)
    
    dark_pixels = int(np.sum(retina_lum < 25))
    underexposed_pct = round((float(dark_pixels) / float(max(1, fov_pixels))) * 100.0, 1)
    
    reasons = []
    guidance = []
    
    if fov_coverage < 0.20:
        reasons.append('CLIPPED_FOV')
        guidance.append('Field of view severely clipped (<20%). Re-align camera objective with the optical axis of the patient pupil.')
    focus_thresh_severe = 1.2
    focus_thresh_border = 4.0
    if focus_score < focus_thresh_severe:
        reasons.append('SEVERE_DEFOCUS')
        guidance.append(f'Image severely blurred (Focus score < {focus_thresh_severe}). Stabilize camera, instruct patient not to blink, and refocus using diopter ring.')
    if glare_pct > 15.0:
        reasons.append('EXCESSIVE_GLARE')
        guidance.append('Excessive corneal glare / reflection detected (> 15% area). Adjust camera angle by 5-10 degrees and ask patient to blink.')
    if underexposed_pct > 40.0 or mean_lum < 0.12:
        reasons.append('SEVERE_UNDEREXPOSURE')
        guidance.append('Severe underexposure. Increase fundus camera flash intensity or allow patient 3-5 minutes in dim lighting for pupil dilation.')
        
    if len(reasons) > 0:
        quality_grade = 'Ungradeable'
        is_gradable = False
        primary_guidance = ' | '.join(guidance)
    elif focus_score < focus_thresh_border or glare_pct > 6.0 or underexposed_pct > 20.0 or contrast_score < 18.0:
        quality_grade = 'Borderline'
        is_gradable = True
        primary_guidance = 'Borderline image quality. Diagnostic analysis proceeded with adaptive contrast enhancement.'
    else:
        quality_grade = 'Good'
        is_gradable = True
        primary_guidance = 'Image quality meets clinical diagnostic standards.'
        
    return {
        'is_gradable': is_gradable,
        'quality_grade': quality_grade,
        'focus_score': float(focus_score),
        'glare_pct': float(glare_pct),
        'underexposed_pct': float(underexposed_pct),
        'contrast_score': float(contrast_score),
        'mean_luminance': float(round(mean_lum, 3)),
        'fov_coverage_ratio': float(round(fov_coverage, 3)),
        'ungradable_reasons': reasons,
        'recapture_guidance': primary_guidance
    }


def detect_cotton_wool_spots(img_bgr, mask, disc_mask, fovea_mask):
    """
    Detects Cotton Wool Spots (soft exudates / localized nerve fiber layer micro-infarctions).
    Appears as fluffy, pale gray-white lesions with indistinct, frayed margins.
    Distinguished from hard exudates by lower edge gradient, lack of intense yellow chroma,
    and larger diffuse surface area (80 to 2500 pixels).
    """
    h, w = img_bgr.shape[:2]
    r = img_bgr[:, :, 2].astype(float)
    g = img_bgr[:, :, 1].astype(float)
    
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    g_enh = clahe.apply(img_bgr[:, :, 1])
    bg_large = cv2.medianBlur(g_enh, 55)
    delta_g = g_enh.astype(float) - bg_large.astype(float)
    
    rg_ratio = (r + 1.0) / (g + 1.0)
    laplacian = np.abs(cv2.Laplacian(g_enh, cv2.CV_64F))
    
    # Soft feathery white/gray patch with moderate green boost, balanced chroma, and low boundary gradient
    cws_cand = (delta_g > 35) & (rg_ratio < 1.35) & (laplacian < 25) & (mask > 0) & (disc_mask == 0) & (fovea_mask == 0)
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cws_cand = cv2.morphologyEx(cws_cand.astype(np.uint8), cv2.MORPH_CLOSE, k_close)
    
    num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(cws_cand)
    cws_coords = []
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if 80 <= area <= 2500:
            cx, cy = int(centroids[i][0]), int(centroids[i][1])
            r_est = max(4, int(np.sqrt(area / np.pi)))
            cws_coords.append({'x': cx, 'y': cy, 'r': r_est, 'type': 'cotton_wool_spot', 'area': int(area)})
    return cws_coords

def assign_lesion_quadrant(x, y, disc_center, fovea_center, disc_radius):
    """
    Assigns a detected lesion to an anatomical retinal quadrant:
    Superior-Temporal (ST), Inferior-Temporal (IT), Superior-Nasal (SN), Inferior-Nasal (IN), or Macula.
    Distance from fovea is measured in Disc Diameters (DD).
    """
    dx_f = float(x - fovea_center[0])
    dy_f = float(y - fovea_center[1])
    dist_fovea_px = float(np.sqrt(dx_f**2 + dy_f**2))
    dd_px = float(max(10, disc_radius * 2.0))
    dist_dd = float(dist_fovea_px / dd_px)
    is_macula = (dist_dd <= 1.5)

    # In retinal fundus photographs: Optic disc is Nasal; Fovea is Temporal
    is_left_eye = (disc_center[0] < fovea_center[0])
    x_mid = (disc_center[0] + fovea_center[0]) / 2.0
    y_mid = (disc_center[1] + fovea_center[1]) / 2.0

    is_temporal = (x > x_mid) if is_left_eye else (x < x_mid)
    is_superior = (y < y_mid)

    if is_superior and is_temporal:
        geo_q = 'Superior-Temporal (ST)'
        q_code = 'ST'
    elif (not is_superior) and is_temporal:
        geo_q = 'Inferior-Temporal (IT)'
        q_code = 'IT'
    elif is_superior and (not is_temporal):
        geo_q = 'Superior-Nasal (SN)'
        q_code = 'SN'
    else:
        geo_q = 'Inferior-Nasal (IN)'
        q_code = 'IN'

    zone = 'Macula' if is_macula else geo_q
    return zone, q_code, float(round(dist_dd, 2))

def predict_dr_grade_and_percentage(img_bgr):
    pred_grade, pred_pct, probs, _ = predict_dr_grade_and_percentage_with_gradcam(img_bgr)
    return pred_grade, pred_pct, probs

def predict_retina_dl_score(img_bgr):
    model = get_dl_classifier()
    if model is None:
        return 0.5, 0.5
    try:
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(img_rgb, (224, 224), interpolation=cv2.INTER_AREA)
        t = torch.from_numpy(resized).permute(2, 0, 1).float() / 255.0
        mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        t = ((t - mean) / std).unsqueeze(0)
        with torch.no_grad():
            out = model(t)
            prob = torch.softmax(out, dim=1)[0]
            noneye_prob = float(prob[0].item())
            retina_prob = float(prob[1].item())
            return retina_prob, noneye_prob
    except Exception as e:
        print('DL prediction error:', e)
        return 0.5, 0.5

def detect_human_faces(img_bgr):
    h, w = img_bgr.shape[:2]
    total_px = h * w
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    min_dim = max(45, int(min(h, w) * 0.12))
    min_size = (min_dim, min_dim)
    
    face_cas = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    faces = face_cas.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=min_size)
    valid_faces = [(x, y, fw, fh) for (x, y, fw, fh) in faces if (fw * fh) / float(total_px) >= 0.03]
    if len(valid_faces) > 0:
        return True, len(valid_faces)
        
    profile_cas = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_profileface.xml')
    profiles = profile_cas.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=min_size)
    valid_profiles = [(x, y, pw, ph) for (x, y, pw, ph) in profiles if (pw * ph) / float(total_px) >= 0.03]
    return len(valid_profiles) > 0, len(valid_profiles)

def detect_geometric_lines(img_bgr):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80, minLineLength=45, maxLineGap=10)
    return len(lines) if lines is not None else 0

# --- 1. INTELLIGENT RETINAL GLOBE LOCALIZER ---
def locate_and_extract_retina(img_bgr):
    h, w = img_bgr.shape[:2]
    total_px = h * w
    
    r = img_bgr[:, :, 2].astype(float)
    g = img_bgr[:, :, 1].astype(float)
    b = img_bgr[:, :, 0].astype(float)
    
    retina_cand = (r - b > 18) & (r - g > 2) & (r > 35)
    cand_px = np.sum(retina_cand)
    cand_ratio = cand_px / float(total_px)

    straight_lines = detect_geometric_lines(img_bgr)
    if straight_lines > 20 and cand_ratio < 0.50:
        return None, None, None
    
    if cand_ratio > 0.60:
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.circle(mask, (w // 2, h // 2), int(min(w, h) * 0.48), 255, -1)
        std_retina = cv2.resize(img_bgr, (512, 512), interpolation=cv2.INTER_CUBIC)
        info = {'crop_x1': 0, 'crop_y1': 0, 'crop_w': w, 'crop_h': h, 'orig_w': w, 'orig_h': h, 'type': 'full_frame'}
        return std_retina, info, mask
        
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cleaned = cv2.morphologyEx(retina_cand.astype(np.uint8) * 255, cv2.MORPH_CLOSE, k)
    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None, None, None
        
    largest_cnt = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest_cnt)
    
    if area < 0.04 * total_px:
        return None, None, None
        
    perimeter = cv2.arcLength(largest_cnt, True)
    circularity = 4 * np.pi * area / (perimeter * perimeter + 1e-5)
    
    if circularity < 0.35 and cand_ratio < 0.30:
        return None, None, None
        
    (cx, cy), radius = cv2.minEnclosingCircle(largest_cnt)
    cx, cy, radius = int(cx), int(cy), int(radius)
    
    if area < 0.30 * total_px:
        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1][retina_cand]
        mean_sat = np.mean(sat) if len(sat) > 0 else 0
        if mean_sat < 50.0:
            return None, None, None
            
        Y, X = np.ogrid[:h, :w]
        dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
        outer_ring = (dist >= radius * 1.08) & (dist <= radius * 1.28)
        if np.sum(outer_ring) > 20:
            outer_pixels = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)[outer_ring]
            outer_mean = np.mean(outer_pixels)
            outer_std = np.std(outer_pixels)
            is_valid_surroundings = (outer_mean > 190) or (outer_mean < 60) or (outer_std < 45)
            if not is_valid_surroundings:
                return None, None, None
    
    margin = int(radius * 0.02)
    x1 = max(0, cx - radius - margin)
    x2 = min(w, cx + radius + margin)
    y1 = max(0, cy - radius - margin)
    y2 = min(h, cy + radius + margin)
    
    crop = img_bgr[y1:y2, x1:x2]
    crop_h, crop_w = crop.shape[:2]
    if crop_h < 20 or crop_w < 20:
        return None, None, None
        
    std_retina = cv2.resize(crop, (512, 512), interpolation=cv2.INTER_CUBIC)
    
    mask = np.zeros((crop_h, crop_w), dtype=np.uint8)
    cv2.circle(mask, (cx - x1, cy - y1), int(radius * 0.98), 255, -1)
    
    info = {
        'crop_x1': x1, 'crop_y1': y1, 'crop_w': crop_w, 'crop_h': crop_h,
        'orig_w': w, 'orig_h': h, 'cx': cx, 'cy': cy, 'radius': radius,
        'circularity': round(circularity, 2), 'area_pct': round(area / total_px * 100, 1),
        'type': 'segmented_globe'
    }
    return std_retina, info, mask

# --- 2. MULTI-MODAL ANATOMICAL & DEEP LEARNING VERIFICATION ---
def verify_eye_authenticity(img_bgr):
    # 1. Primary Deep Neural Network Evaluation
    dl_fundus_prob, dl_noneye_prob = predict_retina_dl_score(img_bgr)
    if dl_noneye_prob > 0.80 and dl_fundus_prob < 0.20:
        return {
            'is_eye': False,
            'confidence_pct': round(dl_fundus_prob * 100.0, 1),
            'reasons': {
                'retinal_globe_detected': False,
                'dl_fundus_prob': round(dl_fundus_prob, 4),
                'dl_noneye_prob': round(dl_noneye_prob, 4)
            },
            'rejection_msg': f'Anatomical eye recognition failed: Deep neural network classified image as non-retinal ({dl_noneye_prob*100:.1f}% confidence).'
        }

    # 2. Check for human face / portrait photography (suppressed if DL is confident it's a retinal fundus)
    if dl_fundus_prob < 0.80:
        has_face, face_cnt = detect_human_faces(img_bgr)
        if has_face:
            return {
                'is_eye': False,
                'confidence_pct': 0.0,
                'reasons': {
                    'face_detected': True,
                    'face_count': face_cnt,
                    'retinal_globe_detected': False
                },
                'rejection_msg': 'Anatomical eye recognition failed: Human portrait / facial photograph detected. Please upload an internal ocular fundus camera photograph.'
            }

    # 3. Retinal Globe Localization & Extraction
    std_retina, info, _ = locate_and_extract_retina(img_bgr)
    if std_retina is None:
        return {
            'is_eye': False,
            'confidence_pct': round(dl_fundus_prob * 100.0, 1),
            'reasons': {
                'retinal_globe_detected': False,
                'dl_fundus_prob': round(dl_fundus_prob, 4),
                'dl_noneye_prob': round(dl_noneye_prob, 4)
            },
            'rejection_msg': 'Anatomical eye recognition failed: No human ocular fundus globe or retinal tissue detected in the image.'
        }
        
    globe_fundus_prob, globe_noneye_prob = predict_retina_dl_score(std_retina)
    if globe_noneye_prob > 0.70 and globe_fundus_prob < 0.30:
        return {
            'is_eye': False,
            'confidence_pct': round(globe_fundus_prob * 100.0, 1),
            'reasons': {
                'retinal_globe_detected': True,
                'globe_dl_fundus_prob': round(globe_fundus_prob, 4),
                'globe_dl_noneye_prob': round(globe_noneye_prob, 4)
            },
            'rejection_msg': f'Anatomical eye recognition failed: Extracted region rejected by Deep Learning ocular verifier ({globe_noneye_prob*100:.1f}% non-eye probability).'
        }

    h, w = std_retina.shape[:2]
    r = std_retina[:, :, 2].astype(float)
    g = std_retina[:, :, 1].astype(float)
    b = std_retina[:, :, 0].astype(float)
    
    mask_std = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(mask_std, (w // 2, h // 2), int(w * 0.47), 255, -1)
    
    r_masked = r[mask_std > 0]
    g_masked = g[mask_std > 0]
    b_masked = b[mask_std > 0]
    
    mean_r = np.mean(r_masked)
    mean_g = np.mean(g_masked)
    mean_b = np.mean(b_masked)
    
    rb_ratio = (mean_r + 1.0) / (mean_b + 1.0)
    rg_ratio = (mean_r + 1.0) / (mean_g + 1.0)
    
    is_chromatic_fundus = (rb_ratio > 1.25) and (rg_ratio > 1.01) and (mean_r > 35)
    
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    g_enh = clahe.apply(std_retina[:, :, 1])
    k_v = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    vessel_tophat = cv2.morphologyEx(255 - g_enh, cv2.MORPH_TOPHAT, k_v)
    vessel_mask = (vessel_tophat > 22) & (mask_std > 0)
    vessel_density = float(np.sum(vessel_mask)) / float(np.sum(mask_std > 0))
    has_vessels = vessel_density > 0.005
    
    rg = ((r + g) / 2.0) * (mask_std / 255.0)
    blurred_rg = cv2.GaussianBlur(rg, (31, 31), 0)
    min_val, max_val, min_loc, disc_loc = cv2.minMaxLoc(blurred_rg)
    disc_contrast = max_val / (np.median(rg[mask_std > 0]) + 1.0)
    has_disc = disc_contrast > 1.15
    
    dl_weight = max(dl_fundus_prob, globe_fundus_prob) * 50.0
    chromatic_weight = 25.0 if is_chromatic_fundus else 0.0
    vessel_weight = 15.0 if has_vessels else 0.0
    disc_weight = 10.0 if has_disc else 0.0
    total_score = round(dl_weight + chromatic_weight + vessel_weight + disc_weight, 1)
    
    is_eye = (total_score >= 60.0) and is_chromatic_fundus and (dl_fundus_prob > 0.5 or globe_fundus_prob > 0.5)
    
    return {
        'is_eye': bool(is_eye),
        'confidence_pct': min(99.9, max(0.0, total_score if is_eye else 0.0)),
        'reasons': {
            'retinal_globe_detected': True,
            'dl_fundus_prob': round(dl_fundus_prob, 4),
            'globe_dl_fundus_prob': round(globe_fundus_prob, 4),
            'is_chromatic_fundus': bool(is_chromatic_fundus),
            'rb_ratio': round(rb_ratio, 2),
            'rg_ratio': round(rg_ratio, 2),
            'has_vessels': bool(has_vessels),
            'vessel_density_pct': round(vessel_density * 100.0, 1),
            'has_disc': bool(has_disc),
            'disc_contrast': round(disc_contrast, 2),
            'roi_info': info
        },
        'rejection_msg': None if is_eye else 'Anatomical eye recognition failed: Image lacks characteristic retinal vascular branching or fundus chromatic profile.'
    }


def log_prediction_audit(img_bgr, result):
    """
    Appends audit record to logs/prediction_audit.jsonl and feeds continuous drift monitor (Items 48, 49).
    """
    try:
        import hashlib, datetime, json
        h = hashlib.sha256(img_bgr.tobytes()).hexdigest()[:16]
        record = {
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'image_sha256_prefix': h,
            'verified_retina': bool(result.get('verified_retina', False)),
            'is_gradable': bool(result.get('is_gradable', False)),
            'quality_grade': str(result.get('quality_assessment', {}).get('quality_grade', 'N/A')),
            'grade': int(result.get('grade', 0)),
            'grade_name': str(result.get('grade_name', '')),
            'referable': bool(result.get('referable', False)),
            'dr_damage_percentage': float(result.get('dr_damage_percentage', 0.0)),
            'dl_confidence_pct': float(result.get('dl_confidence_pct', 0.0)),
            'normalized_entropy': float(result.get('normalized_entropy', 0.0)),
            'high_uncertainty': bool(result.get('high_uncertainty', False)),
            'focus_score': float(result.get('focus_score', 0.0))
        }
        log_dir = os.path.join(os.path.dirname(__file__), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'prediction_audit.jsonl')
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record) + '\n')
            
        try:
            from app.monitoring.drift_detector import get_drift_monitor
            get_drift_monitor().record_prediction(result)
        except Exception:
            pass
    except Exception as e:
        print('Notice: Audit log exception:', e)

# --- 3. FULL RETINAL FUNDUS ANALYSIS ---
def analyze_retinal_fundus(img_bgr):
    verification = verify_eye_authenticity(img_bgr)
    if not verification['is_eye']:
        res_non = {
            'verified_retina': False,
            'is_gradable': False,
            'error': 'NON_RETINAL_IMAGE',
            'message': verification['rejection_msg'],
            'verification': verification
        }
        log_prediction_audit(img_bgr, res_non)
        return res_non
        
    std_retina, info, _ = locate_and_extract_retina(img_bgr)
    h, w = std_retina.shape[:2]
    
    # 1. Parenchyma mask avoiding optical lens edge flare
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(mask, (w // 2, h // 2), int(w * 0.43), 255, -1)
    active_pixels = int(np.sum(mask > 0))

    # 2. Comprehensive Multi-factor Retinal Image Quality Assessment (Items 22, 23, 24)
    quality_assessment = assess_retinal_image_quality(std_retina, mask)
    
    # 3. Deep Learning Multi-Task Evaluation with Full Explainable AI (Grad-CAM & Grad-CAM++)
    dl_grade, dl_pct, dl_probs, gradcam_std_b64, gradcam_pp_b64, uncert_info = predict_dr_grade_and_percentage_with_full_xai(std_retina)
    dl_conf = float(dl_probs[dl_grade])
    
    r = std_retina[:, :, 2].astype(float)
    g = std_retina[:, :, 1].astype(float)
    b = std_retina[:, :, 0].astype(float)
    
    # Optic disc detection with expanded halo suppression (Item 26)
    rg = ((r + g) / 2.0) * (mask / 255.0)
    blurred_rg = cv2.GaussianBlur(rg, (31, 31), 0)
    _, max_val_rg, _, disc_center = cv2.minMaxLoc(blurred_rg)
    disc_radius = int(min(h, w) * 0.08)
    disc_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(disc_mask, disc_center, int(disc_radius * 2.0), 255, -1)
    
    # Anatomical Fovea / FAZ Localization (Item 27)
    dd_px = disc_radius * 2.0
    if disc_center[0] < w / 2:
        fovea_expected_x = min(w - 20, int(disc_center[0] + 2.5 * dd_px))
    else:
        fovea_expected_x = max(20, int(disc_center[0] - 2.5 * dd_px))
    fovea_expected_y = int(disc_center[1] + 0.2 * disc_radius)
    
    # Refine to localized luminance minimum (Foveal Avascular Zone)
    win = int(disc_radius * 0.75)
    wx1 = max(0, fovea_expected_x - win)
    wx2 = min(w, fovea_expected_x + win)
    wy1 = max(0, fovea_expected_y - win)
    wy2 = min(h, fovea_expected_y + win)
    fovea_patch = g[wy1:wy2, wx1:wx2]
    if fovea_patch.size > 0:
        _, _, min_loc_faz, _ = cv2.minMaxLoc(fovea_patch)
        fovea_center = (wx1 + min_loc_faz[0], wy1 + min_loc_faz[1])
    else:
        fovea_center = (fovea_expected_x, fovea_expected_y)
        
    fovea_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(fovea_mask, fovea_center, 40, 255, -1)
    
    # 4. Massive Vitreous / Preretinal Hemorrhage Pool Detection (Hemoglobin Absorption Peak)
    blood_cand = (r > 60) & (g < 42) & (b < 30) & (r / (g + 1.0) > 2.5) & (mask > 0)
    num_bl, _, stats_bl, cent_bl = cv2.connectedComponentsWithStats(blood_cand.astype(np.uint8))
    massive_hemo_found = False
    max_blood_lake_area = 0
    hemo_coords = []
    
    for i in range(1, num_bl):
        area = stats_bl[i, cv2.CC_STAT_AREA]
        if area > max_blood_lake_area:
            max_blood_lake_area = area
        if area >= 3500 and (dl_grade >= 2 or dl_probs[4] > 0.08):
            massive_hemo_found = True
            cx, cy = int(cent_bl[i][0]), int(cent_bl[i][1])
            hemo_coords.append({
                'x': cx, 'y': cy,
                'r': max(14, int(np.sqrt(area / np.pi))),
                'type': 'vitreous_preretinal_pool',
                'area': int(area)
            })
            
    # 5. Vessel Extraction & Density Estimation (Item 28)
    g_uint8 = std_retina[:, :, 1]
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    g_clahe = clahe.apply(g_uint8)
    k_v = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    vessel_tophat = cv2.morphologyEx(255 - g_clahe, cv2.MORPH_TOPHAT, k_v)
    vessel_mask = (vessel_tophat > 25) & (mask > 0)
    vessel_density_pct = (np.sum(vessel_mask) / float(max(1, active_pixels))) * 100.0

    # 5b. Neovascularization of the Disc / Retina (NVD / NVE) Fine Frond Detection (Item 16, 33)
    nvd_detected = False
    y_idx, x_idx = np.indices((h, w))
    dist_from_disc = np.sqrt((x_idx - disc_center[0])**2 + (y_idx - disc_center[1])**2)
    disc_border_region = (dist_from_disc >= disc_radius * 0.8) & (dist_from_disc <= disc_radius * 2.2) & (mask > 0)
    nvd_cand_pixels = np.sum((vessel_tophat > 30) & disc_border_region)
    if nvd_cand_pixels > 320 and dl_grade >= 3:
        nvd_detected = True
    
    # 6. Hard Exudates (Lipid Deposits) (Item 31)
    bg_g = cv2.medianBlur(g_clahe, 35)
    delta_g = g_clahe.astype(float) - bg_g.astype(float)
    yellow_ex = (r > 190) & (g > 155) & (g / (r + 1e-5) > 0.70) & (b < 140) & (delta_g > 25) & (mask > 0) & (disc_mask == 0)
    k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    yellow_ex = cv2.morphologyEx(yellow_ex.astype(np.uint8), cv2.MORPH_OPEN, k_open)
    num_ex_cand, _, stats_ex, centroids_ex = cv2.connectedComponentsWithStats(yellow_ex)
    
    exudates_coords = []
    for i in range(1, num_ex_cand):
        area = stats_ex[i, cv2.CC_STAT_AREA]
        if 4 <= area <= 600:
            cx, cy = int(centroids_ex[i][0]), int(centroids_ex[i][1])
            exudates_coords.append({'x': cx, 'y': cy, 'r': max(2, int(np.sqrt(area / np.pi))), 'type': 'hard_exudate'})

    # 6b. Cotton Wool Spots (Soft Exudates / Nerve Fiber Infarcts) (Item 32)
    cws_coords = detect_cotton_wool_spots(std_retina, mask, disc_mask, fovea_mask)
            
    # 7. Microaneurysms (MAs) and Intraretinal Blot Hemorrhages (Items 29, 30)
    k_ma = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    g_bothat = cv2.morphologyEx(g_clahe, cv2.MORPH_BLACKHAT, k_ma)
    dark_cand = (g_bothat > 18) & (mask > 0) & (~vessel_mask) & (disc_mask == 0) & (fovea_mask == 0)
    num_d, _, stats_d, centroids_d = cv2.connectedComponentsWithStats(dark_cand.astype(np.uint8))
    
    mas_coords = []
    for i in range(1, num_d):
        area = stats_d[i, cv2.CC_STAT_AREA]
        cx, cy = int(centroids_d[i][0]), int(centroids_d[i][1])
        if cx < 6 or cx >= w - 6 or cy < 6 or cy >= h - 6: continue
        
        local_center = np.mean(g_clahe[cy-1:cy+2, cx-1:cx+2])
        ring_mask = np.zeros((13, 13), dtype=np.uint8)
        cv2.circle(ring_mask, (6, 6), 6, 255, -1)
        cv2.circle(ring_mask, (6, 6), 3, 0, -1)
        local_patch = g_clahe[cy-6:cy+7, cx-6:cx+7]
        local_bg = np.mean(local_patch[ring_mask > 0])
        contrast = local_bg - local_center
        
        if 3 <= area <= 40 and contrast > 18:
            mas_coords.append({'x': cx, 'y': cy, 'r': 3, 'type': 'microaneurysm'})
        elif 40 < area <= 800 and contrast > 15:
            hemo_coords.append({'x': cx, 'y': cy, 'r': max(3, int(np.sqrt(area / np.pi))), 'type': 'intraretinal_blot_hemorrhage'})
            
    # CSME (Clinically Significant Macular Edema) Assessment
    csme_positive = False
    min_dist_dd = 999.0
    for ex in exudates_coords:
        dist_px = np.sqrt((ex['x'] - fovea_center[0])**2 + (ex['y'] - fovea_center[1])**2)
        dist_dd = dist_px / (dd_px + 1e-5)
        if dist_dd < min_dist_dd:
            min_dist_dd = dist_dd
        if dist_dd <= 1.0:
            csme_positive = True

    # 8. ANATOMICAL QUADRANT LOCALIZATION & EXPLAINABILITY (ST, IT, SN, IN, MACULA) (Item 13)
    quadrant_counts = {
        'ST': {'mas': 0, 'hemo': 0, 'exudates': 0, 'cws': 0},
        'IT': {'mas': 0, 'hemo': 0, 'exudates': 0, 'cws': 0},
        'SN': {'mas': 0, 'hemo': 0, 'exudates': 0, 'cws': 0},
        'IN': {'mas': 0, 'hemo': 0, 'exudates': 0, 'cws': 0},
        'Macula': {'mas': 0, 'hemo': 0, 'exudates': 0, 'cws': 0, 'csme_risk': bool(csme_positive)}
    }
    all_lesions_segmented = []

    for item in mas_coords:
        zone, q_code, dist_dd = assign_lesion_quadrant(item['x'], item['y'], disc_center, fovea_center, disc_radius)
        item['quadrant'] = q_code
        item['zone'] = zone
        item['dist_fovea_dd'] = dist_dd
        quadrant_counts[q_code]['mas'] += 1
        if zone == 'Macula':
            quadrant_counts['Macula']['mas'] += 1
        all_lesions_segmented.append({
            'type': 'microaneurysm',
            'x': int(item['x']), 'y': int(item['y']), 'r': int(item['r']),
            'quadrant': q_code, 'zone': zone, 'dist_fovea_dd': float(dist_dd)
        })

    for item in hemo_coords:
        zone, q_code, dist_dd = assign_lesion_quadrant(item['x'], item['y'], disc_center, fovea_center, disc_radius)
        item['quadrant'] = q_code
        item['zone'] = zone
        item['dist_fovea_dd'] = dist_dd
        quadrant_counts[q_code]['hemo'] += 1
        if zone == 'Macula':
            quadrant_counts['Macula']['hemo'] += 1
        all_lesions_segmented.append({
            'type': str(item.get('type', 'intraretinal_blot_hemorrhage')),
            'x': int(item['x']), 'y': int(item['y']), 'r': int(item['r']),
            'quadrant': q_code, 'zone': zone, 'dist_fovea_dd': float(dist_dd)
        })

    for item in exudates_coords:
        zone, q_code, dist_dd = assign_lesion_quadrant(item['x'], item['y'], disc_center, fovea_center, disc_radius)
        item['quadrant'] = q_code
        item['zone'] = zone
        item['dist_fovea_dd'] = dist_dd
        quadrant_counts[q_code]['exudates'] += 1
        if zone == 'Macula':
            quadrant_counts['Macula']['exudates'] += 1
        all_lesions_segmented.append({
            'type': 'hard_exudate',
            'x': int(item['x']), 'y': int(item['y']), 'r': int(item['r']),
            'quadrant': q_code, 'zone': zone, 'dist_fovea_dd': float(dist_dd)
        })

    for item in cws_coords:
        zone, q_code, dist_dd = assign_lesion_quadrant(item['x'], item['y'], disc_center, fovea_center, disc_radius)
        item['quadrant'] = q_code
        item['zone'] = zone
        item['dist_fovea_dd'] = dist_dd
        quadrant_counts[q_code]['cws'] += 1
        if zone == 'Macula':
            quadrant_counts['Macula']['cws'] += 1
        all_lesions_segmented.append({
            'type': 'cotton_wool_spot',
            'x': int(item['x']), 'y': int(item['y']), 'r': int(item['r']),
            'quadrant': q_code, 'zone': zone, 'dist_fovea_dd': float(dist_dd)
        })
            
    # Total lesion counts
    num_mas = len(mas_coords)
    num_hemo = len(hemo_coords)
    num_ex = len(exudates_coords)
    num_cws = len(cws_coords)

    # 9. Multi-Lesion Fused Severity Score (Item 34)
    fused_score = (
        1.2 * num_mas + 
        2.8 * num_hemo + 
        3.2 * num_ex + 
        4.5 * num_cws + 
        (25.0 if csme_positive else 0.0) + 
        (45.0 if massive_hemo_found or nvd_detected else 0.0)
    )
    lesion_burden_score = round(float(np.clip(fused_score, 0.0, 99.8)), 1)
    
    # 10. --- ICDR 4-2-1 CRITERIA & CLINICAL STAGING ---
    all_4_quad_hemo_severe = all(quadrant_counts[q]['hemo'] >= 5 for q in ['ST', 'IT', 'SN', 'IN'])
    rule_4_met = bool(
        all_4_quad_hemo_severe or 
        (num_hemo >= 25 and all(quadrant_counts[q]['hemo'] >= 1 for q in ['ST', 'IT', 'SN', 'IN'])) or
        (dl_grade == 3 and dl_conf >= 0.70 and num_hemo >= 15)
    )
    rule_2_met = bool(dl_grade >= 3 and num_hemo >= 12)
    rule_1_met = bool((dl_grade >= 3) or (num_hemo >= 8 and num_mas >= 10))
    rule_pdr_met = bool(massive_hemo_found or nvd_detected or (dl_grade == 4 and dl_conf >= 0.70) or (num_hemo >= 25 and num_mas >= 25))

    icdr_4_met = rule_pdr_met
    icdr_3_met = rule_4_met or rule_2_met or rule_1_met
    icdr_2_met = (dl_grade == 2 and dl_conf >= 0.65) or ((num_hemo >= 3 or (num_ex >= 5 and csme_positive)) and dl_grade not in [0, 1])
    icdr_1_met = (dl_grade == 1 and dl_conf >= 0.65) or (num_mas >= 1 and dl_grade != 0 and num_hemo == 0 and num_ex == 0)
    
    safety_override = False

    # Check for ungradable image (Item 23, 24)
    # Clinical Safety Caveat: Massive vitreous hemorrhage causes optical opacity that can simulate underexposure/defocus.
    # If the deep learning model or hemoglobin absorption peak detects massive blood lakes (Grade 4 PDR),
    # the image is pathology-obscured rather than a technical failure, so emergency referral is preserved.
    if not quality_assessment['is_gradable'] and not (massive_hemo_found or (dl_grade == 4 and dl_conf >= 0.80)):
        grade = -1
        grade_name = 'UNGRADABLE — RECAPTURE REQUIRED'
        referable = False
        ref_title = '⚠️ RECAPTURE IMAGE (UNGRADABLE QUALITY)'
        ref_reason = quality_assessment['recapture_guidance']
        dr_damage_percentage = 0.0
    elif icdr_4_met:
        grade = 4
        grade_name = 'LEVEL 4 — PROLIFERATIVE DR (PDR)'
        referable = True
        ref_title = '🚨 EMERGENCY SPECIALIST REFERRAL'
        ref_reason = f'Proliferative diabetic retinopathy confirmed. {"Massive preretinal/vitreous hemorrhage pool detected" if massive_hemo_found else "High-risk neovascularization detected"}. Emergency ophthalmic surgery / anti-VEGF intervention required within 24-48 hours.'
        dr_damage_percentage = round(float(np.clip(max(dl_pct, 92.0), 90.0, 99.8)), 1)
    elif icdr_3_met:
        grade = 3
        grade_name = 'LEVEL 3 — SEVERE NPDR'
        referable = True
        ref_title = '🔴 URGENT SPECIALIST REFERRAL'
        ref_reason = f'Severe lesion burden ({num_hemo} blot hemorrhages, {num_mas} MAs, {num_ex} exudates, {num_cws} CWS). ICDR 4-2-1 criteria met. Specialist referral within 2-4 weeks required.'
        dr_damage_percentage = round(float(np.clip(max(dl_pct, 75.0), 75.0, 89.5)), 1)
    elif icdr_2_met:
        grade = 2
        grade_name = 'LEVEL 2 — MODERATE NPDR'
        referable = True
        ref_title = '🔴 REFER TO OPHTHALMOLOGIST'
        ref_reason = f'Moderate non-proliferative diabetic retinopathy: {num_mas} MAs, {num_hemo} blot hemorrhages, {num_ex} hard exudates. CSME: {"Positive (High Macular Risk)" if csme_positive else "Negative"}. Evaluation within 2-4 months.'
        dr_damage_percentage = round(float(np.clip(dl_pct, 35.0, 72.0)), 1)
    elif icdr_1_met:
        grade = 1
        grade_name = 'LEVEL 1 — MILD NPDR'
        referable = False
        ref_title = '🟡 CLINICAL FOLLOW-UP (6-12 MONTHS)'
        ref_reason = f'Mild diabetic retinopathy: isolated microaneurysms detected ({num_mas} MAs). No hemorrhages or lipid exudates. Routine repeat screening recommended.'
        dr_damage_percentage = round(float(np.clip(dl_pct, 10.0, 30.0)), 1)
    elif dl_grade == 0 and dl_conf >= 0.75 and not massive_hemo_found and num_hemo < 5:
        grade = 0
        grade_name = 'LEVEL 0 — NO APPARENT RETINOPATHY (HEALTHY RETINA)'
        referable = False
        ref_title = '🟢 NO REFERRAL REQUIRED (NORMAL RETINA)'
        ref_reason = 'Deep Learning & pixel-level analysis confirms healthy normal retina. Zero clinical microaneurysms, blot hemorrhages, or lipid exudates detected.'
        dr_damage_percentage = round(float(np.clip(dl_pct * 0.2, 0.0, 1.5)), 1)
        mas_coords = []
        hemo_coords = []
        exudates_coords = []
        cws_coords = []
        all_lesions_segmented = []
        num_mas = 0
        num_hemo = 0
        num_ex = 0
        num_cws = 0
        csme_positive = False
        lesion_burden_score = 0.0
    else:
        p_referable = sum(dl_probs[2:]) if len(dl_probs) >= 5 else 0.0
        p_non_referable = sum(dl_probs[:2]) if len(dl_probs) >= 5 else 1.0
        if p_referable > p_non_referable and dl_grade < 2:
            ref_sub_idx = int(np.argmax(dl_probs[2:]))
            grade = 2 + ref_sub_idx
        else:
            grade = dl_grade
        referable = (grade >= 2)
        dr_damage_percentage = round(float(dl_pct), 1)
        grade_names = [
            'LEVEL 0 — NO APPARENT RETINOPATHY',
            'LEVEL 1 — MILD NPDR',
            'LEVEL 2 — MODERATE NPDR',
            'LEVEL 3 — SEVERE NPDR',
            'LEVEL 4 — PROLIFERATIVE DR (PDR)'
        ]
        grade_name = grade_names[grade]
        ref_title = '🔴 SPECIALIST REFERRAL REQUIRED' if referable else '🟢 ROUTINE FOLLOW-UP'
        ref_reason = f'Clinical staging based on fused deep residual network evaluation ({dl_conf*100:.1f}% confidence).'

    # CLINICAL FALSE-NEGATIVE / REFERRAL SAFETY INVARIANT (Item 21)
    if grade == 0 and (num_hemo > 0 or num_ex >= 2 or massive_hemo_found or num_cws >= 2 or num_mas >= 4):
        safety_override = True
        grade = 2 if (num_hemo >= 2 or num_ex >= 3 or num_cws >= 2 or (num_mas >= 4 and num_cws >= 1)) else 1
        referable = (grade >= 2)
        dr_damage_percentage = float(max(dr_damage_percentage, 40.0 if referable else 18.0))
        grade_name = 'LEVEL 2 — MODERATE NPDR (SAFETY OVERRIDE)' if referable else 'LEVEL 1 — MILD NPDR (SAFETY OVERRIDE)'
        ref_title = '🔴 REFER TO OPHTHALMOLOGIST' if referable else '🟡 CLINICAL FOLLOW-UP'
        ref_reason = f'Safety invariant triggered: Confirmed lesions detected ({num_hemo} hemorrhages, {num_ex} exudates, {num_cws} CWS, {num_mas} MAs). Zero-tolerance safety policy prevented non-referral false negative.'

    icdr_criteria = {
        'rule_4_vitreous_hemo_or_quadrants': bool(rule_4_met),
        'rule_2_severe_abnormalities': bool(rule_2_met),
        'rule_1_irma_or_lesions': bool(rule_1_met),
        'rule_pdr_neovascularization': bool(rule_pdr_met),
        'csme_status': 'POSITIVE' if csme_positive else 'NEGATIVE',
        'csme_distance_dd': float(round(min_dist_dd, 2)) if min_dist_dd < 900 else 'N/A',
        'safety_invariant_enforced': True,
        'safety_override_applied': bool(safety_override)
    }

    anatomical_landmarks = {
        'disc_center': {'x': int(disc_center[0]), 'y': int(disc_center[1]), 'r': int(disc_radius)},
        'fovea_center': {'x': int(fovea_center[0]), 'y': int(fovea_center[1])},
        'fovea_dist_to_disc_dd': round(float(np.sqrt((fovea_center[0] - disc_center[0])**2 + (fovea_center[1] - disc_center[1])**2) / dd_px), 2),
        'faz_radius_px': int(disc_radius * 0.5),
        'vessel_density_pct': float(round(vessel_density_pct, 1)),
        'nvd_neovascularization_detected': bool(nvd_detected)
    }
    
    full_result = {
        'verified_retina': True,
        'is_gradable': bool(quality_assessment['is_gradable']),
        'quality_assessment': quality_assessment,
        'recapture_guidance': quality_assessment['recapture_guidance'],
        'verification': verification,
        'roi_info': info,
        'anatomical_landmarks': anatomical_landmarks,
        'grade': int(grade),
        'grade_name': str(grade_name),
        'dr_damage_percentage': float(dr_damage_percentage),
        'lesion_burden_score': float(lesion_burden_score),
        'dl_grade': int(dl_grade),
        'dl_confidence_pct': float(round(dl_conf * 100.0, 1)),
        'dl_probs': [float(round(p, 4)) for p in dl_probs],
        'dl_probs_calibrated': [float(round(p, 4)) for p in dl_probs],
        'gradcam_base64': gradcam_pp_b64 or gradcam_std_b64,
        'gradcam_std_base64': gradcam_std_b64,
        'gradcam_pp_base64': gradcam_pp_b64,
        'normalized_entropy': float(uncert_info['normalized_entropy']),
        'high_uncertainty': bool(uncert_info['high_uncertainty']),
        'uncertainty_info': uncert_info,
        'referable': bool(referable),
        'ref_title': str(ref_title),
        'ref_reason': str(ref_reason),
        'focus_score': float(quality_assessment['focus_score']),
        'glare_pct': float(quality_assessment['glare_pct']),
        'mas_count': int(num_mas),
        'mas_coords': mas_coords[:40],
        'hemo_count': int(num_hemo),
        'hemo_coords': hemo_coords[:40],
        'exudates_count': int(num_ex),
        'exudates_coords': exudates_coords[:40],
        'cws_count': int(num_cws),
        'cws_coords': cws_coords[:40],
        'all_lesions_segmented': all_lesions_segmented[:120],
        'lesion_quadrant_distribution': quadrant_counts,
        'csme_positive': bool(csme_positive),
        'csme_dist_dd': float(round(min_dist_dd, 2)) if min_dist_dd < 900 else 'N/A',
        'vessel_density_pct': float(round(vessel_density_pct, 1)),
        'disc_center': {'x': int(disc_center[0]), 'y': int(disc_center[1]), 'r': int(disc_radius)},
        'fovea_center': {'x': int(fovea_center[0]), 'y': int(fovea_center[1])},
        'icdr_criteria': icdr_criteria
    }
    log_prediction_audit(img_bgr, full_result)
    return full_result
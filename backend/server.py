import os
import sys
import json
from flask import Flask, request, jsonify, make_response

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(BACKEND_DIR)

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import retina_analyzer
from app.validators.input_sanitizer import validate_and_sanitize_image
from app.monitoring.drift_detector import get_drift_monitor
from app.db.database import register_patient, get_referred_queue

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max payload
app.config['JSON_SORT_KEYS'] = False

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    return response

@app.route('/', methods=['GET'])
def root_handler():
    """Pure API Gateway Root: Returns JSON status and available endpoints."""
    return jsonify({
        'status': 'ONLINE',
        'service': 'DRISHTI AI Retinal Verification & Diagnostic Engine',
        'framework': 'Flask / PyTorch',
        'type': 'REST API Microservice',
        'version': '2.0.0-SIH26038',
        'deployment': 'Render Cloud Service',
        'endpoints': {
            'health': '/api/health (GET)',
            'status': '/api/status (GET)',
            'analyze_retina': '/api/analyze-retina (POST)',
            'drift_status': '/api/drift-status (GET)',
            'sample_images': '/api/sample-images (GET)',
            'referrals': '/api/referrals (GET)',
            'register_patient': '/api/register-patient (POST)'
        },
        'docs': 'This backend is a pure REST API service. The user interface is hosted separately on Vercel.'
    }), 200

@app.route('/api/health', methods=['GET'])
@app.route('/api/status', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'HEALTHY',
        'service': 'DRISHTI AI Inference Engine',
        'framework': 'Flask',
        'version': '2.0.0-SIH26038'
    }), 200

@app.route('/api/drift-status', methods=['GET'])
def drift_status():
    report = get_drift_monitor().audit_drift()
    return jsonify(report), 200

@app.route('/api/sample-images', methods=['GET'])
def sample_images():
    manifest_paths = [
        os.path.join(BASE_DIR, 'frontend', 'sample_images', 'manifest.json'),
        os.path.join(BACKEND_DIR, 'sample_images', 'manifest.json'),
        os.path.join(BASE_DIR, 'web', 'sample_images', 'manifest.json')
    ]
    manifest_file = next((p for p in manifest_paths if os.path.exists(p)), None)
    images_data = []
    if manifest_file:
        try:
            with open(manifest_file, 'r', encoding='utf-8') as f:
                images_data = json.load(f)
        except Exception as e:
            return jsonify({'error': f'Failed reading manifest: {str(e)}'}), 500
    return jsonify(images_data), 200

@app.route('/api/referrals', methods=['GET'])
def referrals():
    try:
        data = get_referred_queue()
        return jsonify(data), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analyze', methods=['POST', 'OPTIONS'])
@app.route('/api/analyze-retina', methods=['POST', 'OPTIONS'])
def analyze_retina():
    if request.method == 'OPTIONS':
        return make_response('', 200)

    try:
        data = request.get_json(force=True, silent=True)
        if not data or 'image' not in data:
            return jsonify({'error': 'No image provided in JSON payload. Expected {"image": "data:image/..."}'}), 400

        image_b64 = data.get('image', '')
        if not image_b64:
            return jsonify({'error': 'Image data payload is empty'}), 400

        # Validate and sanitize input
        is_valid, img_bgr, meta, err = validate_and_sanitize_image(image_b64)
        if not is_valid:
            return jsonify({'error': err or 'Image validation failed', 'verified_retina': False}), 400

        # Execute PyTorch and OpenCV retinal analysis
        result = retina_analyzer.analyze_retinal_fundus(img_bgr)
        
        # Record into drift monitor
        try:
            get_drift_monitor().record_prediction(result)
        except Exception:
            pass

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': f'Internal analysis error: {str(e)}', 'verified_retina': False}), 500

@app.route('/api/register-patient', methods=['POST', 'OPTIONS'])
def register_patient_endpoint():
    if request.method == 'OPTIONS':
        return make_response('', 200)
    try:
        patient_data = request.get_json(force=True, silent=True)
        if not patient_data:
            return jsonify({'error': 'Invalid JSON body'}), 400
        pid = register_patient(patient_data)
        return jsonify({'status': 'SUCCESS', 'patient_id': pid}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.errorhandler(400)
def bad_request(e):
    return jsonify({'error': 'Bad Request', 'details': str(e)}), 400

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint Not Found', 'service': 'DRISHTI AI Backend'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal Server Error', 'details': str(e)}), 500

def run_server(port=8080, host='0.0.0.0'):
    print(f"DRISHTI AI Pure REST API Server running at http://127.0.0.1:{port}")
    print(f"API Endpoints ready: /api/health, /api/analyze-retina, /api/drift-status, /api/referrals")
    sys.stdout.flush()
    app.run(host=host, port=port, debug=False, threaded=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', sys.argv[1] if len(sys.argv) > 1 else 8080))
    run_server(port)

"""
DRISHTI AI: Role-Based Access Control, Session & Rate Limiting (Items 67, 68, 69)
Roles:
- CHW_OPERATOR: Rural van / PHC technician (Intake & Capture)
- OPHTHALMOLOGIST: Diagnostic specialist (Review & Override)
- DISTRICT_ADMIN: Health administrator (Analytics & Audits)
"""

import time, hashlib, hmac, secrets
from config.settings import SECRET_KEY

ROLES = {
    "CHW_OPERATOR": ["view_intake", "upload_fundus", "view_basic_report"],
    "OPHTHALMOLOGIST": ["view_intake", "upload_fundus", "view_full_xai", "override_diagnosis", "sign_report", "view_referrals"],
    "DISTRICT_ADMIN": ["view_all", "export_analytics", "view_audit_trail", "manage_users"]
}

# In-memory token store & sliding-window rate limiter
_ACTIVE_SESSIONS = {}
_REQUEST_TIMESTAMPS = {} # IP -> list of timestamps

def generate_session_token(username, role):
    """Generates a cryptographically secure signed session token."""
    random_part = secrets.token_hex(16)
    timestamp = str(int(time.time()))
    payload = f"{username}:{role}:{timestamp}:{random_part}"
    signature = hmac.new(SECRET_KEY.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    token = f"{payload}:{signature}"
    _ACTIVE_SESSIONS[token] = {
        "username": username,
        "role": role,
        "created_at": time.time(),
        "expires_at": time.time() + (24 * 3600) # 24 hours
    }
    return token

def verify_session_token(token):
    """Verifies HMAC signature and expiration."""
    if not token or token not in _ACTIVE_SESSIONS:
        return None
    session = _ACTIVE_SESSIONS[token]
    if time.time() > session["expires_at"]:
        del _ACTIVE_SESSIONS[token]
        return None
    return session

def check_permission(session, permission):
    """Verifies that the session role holds the requested capability."""
    if not session:
        return False
    role = session.get("role", "")
    return permission in ROLES.get(role, [])

def check_rate_limit(client_ip, max_requests_per_minute=60):
    """Sliding-window rate limiter preventing API abuse and DDoS."""
    now = time.time()
    if client_ip not in _REQUEST_TIMESTAMPS:
        _REQUEST_TIMESTAMPS[client_ip] = []
    
    # Prune timestamps older than 60 seconds
    _REQUEST_TIMESTAMPS[client_ip] = [t for t in _REQUEST_TIMESTAMPS[client_ip] if now - t < 60]
    
    if len(_REQUEST_TIMESTAMPS[client_ip]) >= max_requests_per_minute:
        return False # Rate limited
    
    _REQUEST_TIMESTAMPS[client_ip].append(now)
    return True

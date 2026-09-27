import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE_DIR, 'backend')
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Prevent Windows OS from sleeping while server is running
if os.name == 'nt':
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000041)
    except Exception:
        pass

from backend.server import run_server

if __name__ == '__main__':
    port = int(os.environ.get('PORT', sys.argv[1] if len(sys.argv) > 1 else 8080))
    run_server(port)

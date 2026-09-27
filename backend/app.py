from server import app, run_server

if __name__ == '__main__':
    import os, sys
    port = int(os.environ.get('PORT', sys.argv[1] if len(sys.argv) > 1 else 8080))
    run_server(port)

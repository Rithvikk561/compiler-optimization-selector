"""
run_web.py — Launcher for TOACD Web Application.

Usage:
    python run_web.py [--host 127.0.0.1] [--port 8080]
"""

import os
import sys
import argparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from web.server import start_server

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TOACD Compiler Optimization Platform — Web Interface")
    parser.add_argument("--host", default="127.0.0.1", help="Binding host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    args = parser.parse_args()
    start_server(host=args.host, port=args.port)

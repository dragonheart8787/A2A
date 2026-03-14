#!/usr/bin/env python3
"""從專案根目錄執行：python validate_schemas.py"""
import subprocess
import sys
from pathlib import Path

script = Path(__file__).resolve().parent / "ai-governance" / "scripts" / "validate_schemas.py"
if not script.exists():
    print(f"找不到 {script}", file=sys.stderr)
    sys.exit(2)
sys.exit(subprocess.run([sys.executable, str(script)], cwd=Path(__file__).resolve().parent).returncode)

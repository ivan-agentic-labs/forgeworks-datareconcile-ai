from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT / "apps/api/src", ROOT / "apps/worker/src"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

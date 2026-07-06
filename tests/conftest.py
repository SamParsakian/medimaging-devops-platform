"""
Makes each service's own directory importable by test files, the same
way each service already runs standalone (one flat script per folder,
no shared package). Only services with something worth unit testing
are added here.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

for service_dir in ("anonymizer", "preview-generator", "metadata-extractor", "ai-inference"):
    sys.path.insert(0, str(ROOT_DIR / "services" / service_dir))

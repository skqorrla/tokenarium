"""pytest 설정. aqua/ 패키지를 sys.path 에 추가해 `from store import DataStore` 가 동작하게 함."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "aqua"))

import sys
from pathlib import Path

# 패키지 디렉토리를 sys.path에 등록해 내부 모듈을 flat import로 사용 가능하게 함
_pkg_dir = str(Path(__file__).resolve().parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

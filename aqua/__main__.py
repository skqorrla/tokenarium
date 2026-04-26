"""
__main__.py - CLI 진입점

python -m aqua              기본 실행
python -m aqua --help       옵션 확인
"""

import argparse
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="aqua",
        description="Tokenarium — AI 토큰 사용량을 터미널 어항으로 시각화",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=None,
        help="DB 파일 경로 (기본: aqua.db)",
    )
    parser.add_argument(
        "--dirs",
        nargs="*",
        metavar="PATH",
        default=None,
        help="추가로 감시할 git 프로젝트 경로 (기본: 현재 디렉토리)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        metavar="N",
        default=None,
        help="파일 폴링 간격 초 (기본: 5)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    # CLI 인자로 config 값 오버라이드
    if args.interval is not None:
        import config
        config.POLL_INTERVAL = args.interval

    git_dirs = [Path(d) for d in args.dirs] if args.dirs else None

    import main
    main.run(db_path=args.db, git_dirs=git_dirs)

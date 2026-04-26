"""
__main__.py - CLI 진입점

python -m aqua              기본 실행 (어항 시작)
python -m aqua init         DB 스키마 생성 (idempotent)
python -m aqua --help       옵션 확인
"""

import argparse
import sys
from pathlib import Path

# `python -m aqua` 실행 시 aqua/ 내부 모듈(`config`, `store`, `main`, ...)을
# top-level import로 쓸 수 있도록 패키지 디렉토리를 sys.path에 등록.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _build_parser() -> argparse.ArgumentParser:
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
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.add_parser(
        "init",
        help="DB 스키마 생성 (idempotent). 이미 있으면 건드리지 않음",
    )
    seed_p = sub.add_parser(
        "seed",
        help="docs/*.xlsx 의 시드 데이터 적재 (INSERT OR IGNORE — 첫 적재만 반영)",
    )
    seed_p.add_argument(
        "--docs",
        metavar="DIR",
        default=None,
        help="시드 xlsx 디렉토리 (기본: config.DOCS_DIR)",
    )
    return parser


def _run_init(db_path: str | None) -> None:
    import config
    from store import DataStore

    resolved = db_path or config.DB_PATH
    DataStore(resolved).init_db()
    print(f"[aqua] DB schema initialized at {resolved}")


def _run_seed(db_path: str | None, docs: str | None) -> None:
    import config
    from seed import seed_from_xlsx

    resolved_db = db_path or config.DB_PATH
    resolved_docs = Path(docs) if docs else config.DOCS_DIR
    counts = seed_from_xlsx(resolved_db, resolved_docs)
    summary = ", ".join(f"{t}={n}" for t, n in counts.items()) or "(없음)"
    print(f"[aqua] seeded from {resolved_docs}: {summary}")


if __name__ == "__main__":
    args = _build_parser().parse_args()

    if args.command == "init":
        _run_init(args.db)
        sys.exit(0)

    if args.command == "seed":
        _run_seed(args.db, args.docs)
        sys.exit(0)

    # 기본 실행 경로 (기존 동작 유지)
    if args.interval is not None:
        import config
        config.POLL_INTERVAL = args.interval

    git_dirs = [Path(d) for d in args.dirs] if args.dirs else None

    import main
    main.run(db_path=args.db, git_dirs=git_dirs)

from pathlib import Path

# ── DataStore ──────────────────────────────────────────────────────── #
DB_PATH: str = str(Path(__file__).resolve().parent.parent / "aqua.db")

# ── Seed (시드 xlsx 디렉토리) ──────────────────────────────────────── #
DOCS_DIR: Path = Path(__file__).resolve().parent.parent / "docs"

# ── 파일 감시 ──────────────────────────────────────────────────────── #
POLL_INTERVAL: int = 5          # polling fallback 간격 (초)

# ── 물고기 성장 임계값 (total_food 기준) ───────────────────────────── #
GROWTH_THRESHOLDS: list[float] = [10.0, 50.0, 200.0]  # 소 / 중 / 대

# ── Renderer ───────────────────────────────────────────────────────── #
RENDER_INTERVAL: int = 1        # 어항 화면 갱신 주기 (초)

# ── 게임 상수 ──────────────────────────────────────────────────────── #
FOOD_COST_PER_FEED: int     = 5_000   # 급여 1회 차감 토큰
FULLNESS_PER_FEED: int      = 5       # 급여 1회 포만감 증가 (%)
FULLNESS_DECAY_RATE: int    = 1       # 포만감 감소 (%/30분)
FULLNESS_MIN: int           = 0       # 포만감 최솟값 (0에서 멈춤)
LINES_PER_XP: int           = 5       # line_diff 5당 XP 1
LEVELUP_FULLNESS_BONUS: int = 30      # 레벨업 시 포만감 보너스 (%)
UI_REFRESH_INTERVAL: float  = 0.5     # UI 갱신 주기 (초)

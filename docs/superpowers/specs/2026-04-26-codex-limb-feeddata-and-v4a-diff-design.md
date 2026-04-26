# Codex Limb — FeedData 매핑 및 V4A diff 파싱 설계

- 일자: 2026-04-26
- 대상 파일: `aqua/limbs/codex_limb.py`
- 브랜치: `feature/codex-limb`

## 목적

`~/.codex/sessions/**/*.jsonl` 에서 두 종류의 이벤트를 추출하여 `FeedData`(aqua/interface.py)로 발행한다.

1. `event_msg` / `payload.type=="token_count"` → 토큰 사용량 FeedData
2. `response_item` / `payload.type=="custom_tool_call"` / `payload.name=="apply_patch"` → V4A diff churn FeedData

## 데이터 소스 구조

### 메타데이터 (파일 앞부분 1회만 등장)

| 출처 | 필드 |
|---|---|
| `session_meta.payload.cwd` | 작업 폴더 절대경로 (예: `/home/skqorrla/2026-1-DSCD-ADE-01`) |
| `session_meta.payload.id` | 세션 UUID |
| `turn_context.payload.model` | 모델명 (예: `gpt-5.5`). `session_meta.payload.model`은 보통 `None` |

### token_count 이벤트

```json
{
  "timestamp": "2026-04-22T07:46:40.419Z",
  "type": "event_msg",
  "payload": {
    "type": "token_count",
    "info": {
      "last_token_usage": {
        "input_tokens": 56130,
        "output_tokens": 2550,
        "reasoning_output_tokens": 1552,
        "total_tokens": 58680
      }
    }
  }
}
```

`payload.info` 가 `null` 인 경우가 존재 → 스킵.

### apply_patch 이벤트

```json
{
  "timestamp": "...",
  "type": "response_item",
  "payload": {
    "type": "custom_tool_call",
    "name": "apply_patch",
    "input": "*** Begin Patch\n*** Update File: foo.py\n@@ class Foo\n- old\n+ new\n*** End Patch"
  }
}
```

## FeedData 매핑

### token_count → FeedData

| 필드 | 값 |
|---|---|
| `dir` | `Path(meta.cwd).name` |
| `agent_name` | `"codex"` |
| `total_token` | `last_token_usage.total_tokens` |
| `normalized` | `output_tokens * 1.0 + reasoning_output_tokens * 0.5` (raw 가중) |
| `created_at` | 이벤트 `timestamp` (ISO8601 → `datetime`). 실패 시 `datetime.now()` |
| `model_name` | `meta.model` (없으면 `""`) |
| `session` | `meta.id` |
| `line_diff` | `0` |

스킵 조건: `info is None` 또는 `output + reasoning <= 0`.

### apply_patch → FeedData

| 필드 | 값 |
|---|---|
| `dir`, `session`, `model_name` | 메타 캐시 |
| `agent_name` | `"codex"` |
| `total_token` | `0` |
| `normalized` | `0.0` |
| `created_at` | 이벤트 `timestamp` |
| `line_diff` | V4A churn = added + removed |

스킵 조건: `payload.name != "apply_patch"` 또는 churn == 0.

## V4A diff 파싱 규칙

`payload.input` 텍스트를 줄 단위로 순회:

| 줄 시작 | 처리 |
|---|---|
| `*** ` | 헤더 (Begin/End/Add File/Update File/Delete File) → 스킵 |
| `@@` | 컨텍스트 마커 → 스킵 |
| `+` (헤더 아닌) | added += 1 |
| `-` (헤더 아닌) | removed += 1 |
| 그 외 | 컨텍스트 → 스킵 |

`churn = added + removed` 반환.

## 발행 단위

**이벤트별 분리 발행**. 한 사이클에 N개의 이벤트가 들어오면 N개의 FeedData가 큐잉된다. 합산 책임은 DataStore.

## 파일 구조 변경

```python
CODEX_DIR = Path.home() / ".codex"

def _normalize(output_tokens: int, reasoning_tokens: int) -> float: ...
def _parse_v4a_diff(diff_text: str) -> int: ...
def _read_meta(path: str) -> dict:
    """파일 앞부분에서 dir/session/model_name 추출. {dir, session, model_name} 반환."""
def _parse_offset(path: str, offset: int, meta_cache: dict) -> tuple[list[FeedData], int]:
    """offset부터 읽어 token_count + apply_patch 이벤트별 FeedData 리스트 반환."""

def _make_watchdog_handler(feed_queue) -> Handler:
    # 핸들러 인스턴스에 self._offsets, self._meta_cache 보유.
    # 새 파일 경로를 만나면 _read_meta(path)로 lazy 캐시.
    ...

class CodexLimb(BaseLimb, PollingMixin):
    def __init__(self):
        self._meta_cache: dict[str, dict] = {}  # PollingMixin 경로 전용
    def watch(...): ...  # 변경 없음
    def _watchdog_watch(...): ...  # 변경 없음
    def _iter_target_files(self):  # 변경 없음
        sessions = CODEX_DIR / "sessions"
        target = sessions if sessions.exists() else CODEX_DIR
        return target.rglob("*.jsonl")
    def _parse_from_offset(self, path, offset):
        # 새 path면 _read_meta로 self._meta_cache 채움 → _parse_offset에 전달
        ...
```

메타 캐시는 watchdog 핸들러와 PollingMixin 측이 각각 보유한다 (실행 중에는 둘 중 하나만 작동하므로 분리되어도 문제없음). `_make_feed` 헬퍼는 인라인으로 통합 (메타 + 사용량을 합치는 위치가 한 곳뿐).

## 비결정 (현 스펙 범위 외)

- 모델별 가중치 차등화: 현재 단일 가중치(`output*1.0 + thoughts*0.5`).
- `_MAX_TOKENS` 정규화 클램프: 사용자 결정 A에 따라 미적용. `normalized`는 raw 가중 값.
- DataStore 측 합산/저장 로직: 본 스펙 범위 외.

## 테스트 방향 (별도 작업)

본 스펙에서는 코드 변경만 다루며, 단위/통합 테스트는 후속 작업으로 분리한다. 그러나 다음 케이스가 주요 검증 대상이다:

- `info=None` token_count 스킵
- `total_tokens=0` 케이스 스킵
- V4A 헤더(`*** Begin Patch`, `*** Update File:`)와 `@@` 줄이 churn에 포함되지 않음
- 메타 캐시가 파일별로 분리되어 다른 세션의 dir/model이 섞이지 않음
- offset 기반 증분 파싱이 같은 이벤트를 두 번 발행하지 않음

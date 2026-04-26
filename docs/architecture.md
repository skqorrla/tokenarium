# Tokenarium 아키텍처

> AI 토큰 사용량 · Git 커밋 수를 실시간 수집해 터미널 어항에 물고기로 시각화하는 CLI 툴.
> **프로젝트 1개 = 물고기 1마리.** 토큰/커밋이 쌓일수록 물고기가 성장한다.

---

## 목차

1. [한 줄 개념도](#1-한-줄-개념도)
2. [핵심 전제: 파일만 읽는다](#2-핵심-전제-파일만-읽는다)
3. [컴포넌트 구조](#3-컴포넌트-구조)
4. [데이터 모델 — FeedData](#4-데이터-모델--feeddata)
5. [전체 데이터 흐름](#5-전체-데이터-흐름)
6. [Orchestrator 상세](#6-orchestrator-상세)
7. [Limb 계층 구조](#7-limb-계층-구조)
8. [파일 감시 전략](#8-파일-감시-전략)
9. [물고기 성장 로직](#9-물고기-성장-로직)
10. [진입점 설계](#10-진입점-설계)
11. [테스트 구조](#11-테스트-구조)
12. [파일 구조 및 현황](#12-파일-구조-및-현황)

---

## 1. 한 줄 개념도

```
사용자가 AI를 쓴다
      │
      ▼
AI CLI가 로컬 파일에 로그를 기록한다   ← ~/.claude, ~/.codex, ~/.gemini, .git/
      │
      ▼
Limb(팔다리)가 파일 변화를 감지한다     ← 외부 API 호출 없음, 파일 읽기만
      │
      ▼
FeedData(물고기 밥)를 Orchestrator에 전달한다
      │
      ▼
DataStore에 저장하고 물고기를 키운다
      │
      ▼
터미널 어항에 물고기가 헤엄친다  ><)))>
```

---

## 2. 핵심 전제: 파일만 읽는다

tokenarium은 **외부 API를 호출하지 않는다.**

각 AI CLI(Claude Code, Codex, Gemini)는 자체적으로 AI 서버에 요청을 보내고,
그 응답(토큰 수 포함)을 로컬 파일에 기록한다.
tokenarium은 그 결과 파일을 감시·파싱해서 토큰 수를 추출할 뿐이다.

```
[Claude Code 실행]
      │
      ▼  (Claude Code가 Anthropic API 호출)
      ▼  (응답 수신 후 로컬 파일에 기록)
~/.claude/projects/-home-user-myapp/session.jsonl
      │
      ▼  (tokenarium이 파일 변화 감지)
ClaudeLimb → FeedData → 어항 갱신
```

---

## 3. 컴포넌트 구조

```
┌─────────────────────────────────────────────────────────┐
│                      python -m aqua                     │
├─────────────────────────────────────────────────────────┤
│                     MainComponent                       │
│                                                         │
│  ┌──────────────────────┐   ┌────────────────────────┐  │
│  │     Orchestrator     │──►│   AquariumRenderer     │  │
│  │   (팔다리 관제탑)     │   │    (터미널 어항)        │  │
│  └──────────┬───────────┘   └────────────────────────┘  │
│             │ save / update            ▲                 │
│             ▼                on_feed 콜백                │
│  ┌──────────────────────┐             │                 │
│  │      DataStore       │─────────────┘                 │
│  │  (SQLite, 구현 예정)  │                               │
│  └──────────────────────┘                               │
└─────────────────────────────────────────────────────────┘
             │
     ┌───────┴────────────────────────────┐
     │  Daemon 스레드 (각 Limb 독립 실행) │
     ├──────────┬──────────┬──────────────┤
     ▼          ▼          ▼              ▼
 ClaudeLimb CodexLimb GeminiLimb      GitLimb
```

> **몸통** = Orchestrator + DataStore + Renderer
> **팔다리** = 각 AI/Git Limb (독립 스레드, 교체·추가 가능)

---

## 4. 데이터 모델 — FeedData

모든 팔다리가 생산하고, 몸통이 소비하는 **공통 화폐**다.

```
┌──────────────────────────────────────────┐
│               FeedData                   │
├──────────────┬───────────────────────────┤
│ project_id   │ sha256(폴더명)[:8]        │  ← 물고기 식별자
│ project_name │ 프로젝트 폴더명           │  ← 어항에 표시
│ raw_value    │ 실제 토큰 수 / 커밋 수    │  ← 원시값
│ normalized   │ 0.0 ~ 1.0                 │  ← 물고기 밥 양
│ source       │ "claude"│"codex"│"gemini"│"git"
│ timestamp    │ 수집 시각 (자동 생성)     │
└──────────────┴───────────────────────────┘
```

**normalized 계산 방식**

| 소스 | 기준값 | 계산식 |
|---|---|---|
| claude | 100,000 토큰 | `tokens / 100_000` (상한 1.0) |
| codex | 100,000 토큰 | `tokens / 100_000` (상한 1.0) |
| gemini | 100,000 토큰 | `tokens / 100_000` (상한 1.0) |
| git | 50 커밋 | `commits / 50` (상한 1.0) |

raw_value를 그대로 쓰면 Claude 50,000 토큰 vs Git 3 커밋을 비교할 수 없다.
normalized로 0.0~1.0 스케일을 맞춰 물고기 밥으로 공정하게 환산한다.

---

## 5. 전체 데이터 흐름

```
[사용자 터미널]          [로컬 파일 시스템]                    [어항 터미널]
──────────────          ──────────────────────────────────    ──────────────
                        ~/.claude/projects/**/*.jsonl
                        → {type:"assistant",
claude 사용 ──append──►    message:{usage:{              ──► ClaudeLimb
                              input_tokens: N,                    │
                              output_tokens: M}}}                 │

                        ~/.codex/sessions/**/*.jsonl
                        → {type:"event_msg",
codex  사용 ──append──►    payload:{type:"token_count",  ──► CodexLimb
                              info:{last_token_usage:{             │
                                input_tokens: N,                   │  FeedData 생성
                                output_tokens: M}}}}               │  {normalized: 0.0~1.0}

                        ~/.gemini/**/*.json(l)
                        → {attributes:{
gemini 사용 ──append──►    "event.name":"gemini_cli.api_response", ──► GeminiLimb
                              total_token_count: N}}              │

git commit  ──write───► .git/COMMIT_EDITMSG (mtime 변화) ──► GitLimb
                                                                  │
                                                   ┌─────────────┘
                                                   │  thread-safe Queue
                                                   ▼
                                         Orchestrator.run_dispatch_loop()
                                                   │
                                     ┌─────────────┴──────────────────┐
                                     ▼                                 ▼
                                DataStore                      AquariumRenderer
                             fish_state 갱신                    어항 재렌더링
                           total_food += normalized
                                     │
                               임계값 초과?
                                     │
                                   Yes → fish.size 증가
```

---

## 6. Orchestrator 상세

### 6-1. 생명주기

```
Orchestrator.start()
      │
      ├─ ClaudeLimb.is_available()?  ── Yes ──► daemon Thread 생성 ──► _watch_loop()
      ├─ CodexLimb.is_available()?   ── Yes ──► daemon Thread 생성 ──► _watch_loop()
      ├─ GeminiLimb.is_available()?  ── No  ──► skip (경고 출력)
      └─ GitLimb.is_available()?     ── Yes ──► daemon Thread 생성 ──► _watch_loop()
```

### 6-2. 스레드별 에러 처리

```
_watch_loop(limb)
      │
  limb.watch() 호출
      │
  예외 발생?
  ┌── Yes ──────────────────────────────────────────────┐
  │   limb.on_error(exc) 호출                           │
  │   retry_count++                                     │
  │                                                     │
  │   retry_count > MAX_RETRIES(3)?                     │
  │   ┌── Yes ──────────────────┐                       │
  │   │   해당 Limb 영구 비활성화│                       │
  │   └─────────────────────────┘                       │
  │         No → RETRY_DELAY(5초) 후 limb.watch() 재시작│
  └─────────────────────────────────────────────────────┘
        │
    No  │
        ▼
    정상 동작 유지
```

### 6-3. 메인 디스패치 루프 (메인 스레드)

```
run_dispatch_loop()  ← 메인 스레드에서 실행

  ┌─────────────────────────────────────┐
  │  feed_queue.get(timeout=1.0)        │
  │          │                          │
  │    FeedData 수신                    │
  │          │                          │
  │  DataStore.save_feed(feed)          │
  │  DataStore.update_fish_state(       │
  │      feed.project_id,               │
  │      feed.normalized                │
  │  )                                  │
  │          │                          │
  │  on_feed(feed) ──► Renderer 갱신   │
  └─────────────────────────────────────┘
           (반복, stop_event까지)
```

---

## 7. Limb 계층 구조

### 7-1. 클래스 관계

```
            BaseLimb  (interface.py)
           ┌──────────────────────────┐
           │  + name: str  [abstract] │
           │  + is_available() → bool │
           │  + watch(q, evt) → None  │  ← Orchestrator가 호출하는 유일한 진입점
           │  + on_error(exc)         │
           └──────────┬───────────────┘
                      │ 구현
        ┌─────────────┼──────────────────────────┐
        │             │                          │
   ┌────▼────┐   ┌────▼────┐              ┌──────▼──────┐
   │Polling  │   │Polling  │              │  GitLimb    │
   │Mixin    │   │Mixin    │              │             │
   ├─────────┤   ├─────────┤              │ 단독 폴링   │
   │Claude   │   │Codex /  │              │ 구현        │
   │Limb     │   │Gemini   │              └─────────────┘
   └─────────┘   │Limb     │
                 └─────────┘

PollingMixin  (limbs/polling_mixin.py)
  + _poll_watch(q, evt)          ← 공통 폴링 루프
  + _iter_target_files()  [hook] ← 각 Limb가 구현
  + _parse_from_offset()  [hook] ← 각 Limb가 구현
```

### 7-2. AI Limb 내부 구조 (Claude / Codex / Gemini 공통)

```
XxxLimb.watch(feed_queue, stop_event)
           │
    pick_strategy()
           │
    ┌──────┴──────┐
    │             │
"watchdog"    "polling"
    │             │
    ▼             ▼
_watchdog_    _poll_watch()   ← PollingMixin 제공
watch()           │
    │        _iter_target_files()  ← Limb가 구현 (감시 파일 목록)
    │        _parse_from_offset()  ← Limb가 구현 (증분 파싱)
    │             │
    └──────┬──────┘
           │
    FeedData 생성 → feed_queue.put()
```

### 7-3. AI별 감시 경로 및 토큰 필드

공식 CLI 소스코드 기준으로 검증된 실제 JSON 경로다.

| Limb | 감시 경로 | 파일 | 토큰 JSON 경로 | 필터 조건 |
|---|---|---|---|---|
| ClaudeLimb | `~/.claude/projects/` | `*.jsonl` | `message.usage.input_tokens` + `message.usage.output_tokens` | 없음 (usage 있는 줄만) |
| CodexLimb | `~/.codex/sessions/` | `*.jsonl` | `payload.info.last_token_usage.input_tokens` + `.output_tokens` | `type=="event_msg"` AND `payload.type=="token_count"` |
| GeminiLimb | `~/.gemini/` | `*.json`, `*.jsonl` | `attributes.total_token_count` | `attributes["event.name"]=="gemini_cli.api_response"` |
| GitLimb | `<project>/.git/` | `COMMIT_EDITMSG` | mtime 변화 횟수 | — |

**Claude 프로젝트 이름 추출 방식**
```
~/.claude/projects/ -home-user-Project-myapp /abc123.jsonl
                    └──────────────────────┘
                    rsplit("-", 1)[-1]  →  "myapp"
```

---

## 8. 파일 감시 전략

### 8-1. 전략 선택 (`pick_strategy()`)

```
pick_strategy() 호출
      │
watchdog 패키지 import 성공?
      │
   Yes │              No
      ▼               ▼
 "watchdog"        "polling"
 이벤트 기반       mtime 기반
 (< 1초 반응)      (5초 간격)
```

### 8-2. watchdog 전략

```
파일 변경 이벤트 발생 (on_modified)
      │
  대상 확장자 파일인가?
      │
    Yes
      │
  _offsets[path] 에서 이전 byte offset 조회
      │
  offset부터 파일 읽기  → 신규 줄만 파싱
      │
  새 offset 저장
      │
  토큰 합산 > 0 ?  →  FeedData 생성 → queue.put()
```

### 8-3. polling 전략 (PollingMixin)

```
POLL_INTERVAL(5초)마다 반복:

  for path in _iter_target_files():
        │
    os.stat(path).st_mtime 조회
        │
    이전 mtime과 다름?
        │
      Yes
        │
    _parse_from_offset(path, 이전 offset)
        │
    FeedData 리스트, 새 offset 반환
        │
    queue.put(feed) for feed in feeds
```

### 8-4. byte offset 기반 증분 읽기 (중복 방지)

```
파일 내용:   [줄1][줄2][줄3][줄4][줄5]
                          ↑
                    이전 offset (줄3까지 읽음)

다음 이벤트: [줄1][줄2][줄3][줄4][줄5][줄6][줄7]
                          ↑──────────────────┘
                          여기서부터만 읽음 → 중복 없음
```

### 8-5. watchdog import 지연 처리

```python
# 모듈 로드 시점에 import하지 않음
# → watchdog 미설치 환경에서도 모듈 로드 가능

def _make_watchdog_handler(feed_queue):
    from watchdog.events import FileSystemEventHandler  # 지연 import
    ...
```

---

## 9. 물고기 성장 로직

### 9-1. 상태 머신

```
FeedData 수신
      │
total_food += normalized (0.0 ~ 1.0)
      │
      ▼
 total_food:  0 ──── 10 ──────── 50 ──────────────── 200 ────►
              │       │           │                    │
  fish.size:  1       2           3                    4
              │       │           │                    │
  ASCII:     ><>   ><))>       ><)))>              ><((((>
             치어    소           중                   대
```

### 9-2. normalized 값이 필요한 이유

```
raw_value 직접 사용 시 문제:

  Claude:  50,000 토큰  →  단위가 달라 Git 커밋과 직접 비교 불가

normalized 사용 시:

  Claude:  50,000 / 100,000 = 0.5
  Git:     3      / 50      = 0.06

  같은 스케일(0.0~1.0)로 물고기 밥을 환산해 공정하게 합산 가능
```

---

## 10. 진입점 설계

### 10-1. 파일 역할 분담

```
__main__.py   CLI 인자 파싱 → main.run() 호출  (얇은 껍데기)
main.py       컴포넌트 초기화 + 배선           (로직 없음, 조립만)
config.py     전역 상수 정의                   (팀원 공유 기준점)
```

### 10-2. 실행 흐름

```
python -m aqua [--db PATH] [--dirs PATH...] [--interval N]
      │
      ▼
__main__.py  ── 인자 파싱 → config 오버라이드
      │
      ▼
main.run(db_path, git_dirs)
      │
      ├─ 1. DataStore 초기화       _resolve_store()
      │        │
      │    구현됐나?
      │    No → _StubStore (no-op)  ← 경고 출력 후 계속 실행
      │
      ├─ 2. AquariumRenderer 초기화  _resolve_renderer()
      │        │
      │    구현됐나?
      │    No → print 콜백으로 대체  ← 경고 출력 후 계속 실행
      │
      ├─ 3. Orchestrator(store, on_feed) 생성
      │
      ├─ 4. Limb 등록
      │      orchestrator.register(ClaudeLimb())
      │      orchestrator.register(CodexLimb())
      │      orchestrator.register(GeminiLimb())
      │      orchestrator.register(GitLimb(git_dirs))
      │
      ├─ 5. renderer.start()  (있을 때만)
      │
      ├─ 6. orchestrator.start()  ← Limb daemon 스레드 시작
      │
      ├─ 7. signal 등록 (SIGINT / SIGTERM → _shutdown)
      │
      └─ 8. orchestrator.run_dispatch_loop()  ← 블로킹, 무한 실행
```

### 10-3. 스텁 컴포넌트 처리 전략

팀원의 store / renderer 구현이 완료되기 전에도 프로세스가 정상 실행된다.

```
_resolve_store(db_path)
      │
  DataStore(db_path) 생성 시도
      │
  NotImplementedError?
  ┌── Yes → 경고 출력 후 _StubStore() 반환 (no-op)
  └── No  → 실제 DataStore 반환

_resolve_renderer(store)
      │
  from renderer import AquariumRenderer 시도
      │
  ImportError / NotImplementedError?
  ┌── Yes → 경고 출력 후 None 반환 (print 콜백 사용)
  └── No  → AquariumRenderer(store) 반환
```

### 10-4. 종료 흐름

```
Ctrl+C (SIGINT)  or  SIGTERM
      │
  _shutdown(sig, frame)
      │
  orchestrator.stop()   → stop_event.set()
  renderer.stop()       → 렌더 스레드 종료
      │
  sys.exit(0)
      │
  daemon 스레드 (Limb들) OS가 자동 회수
```

### 10-5. config.py 항목

| 상수 | 기본값 | 설명 |
|---|---|---|
| `DB_PATH` | `"aqua.db"` | SQLite 파일 경로 |
| `POLL_INTERVAL` | `5` | polling fallback 간격 (초) |
| `GIT_WATCH_DIRS` | `[]` | 감시할 git 프로젝트 경로 목록 |
| `GROWTH_THRESHOLDS` | `[10.0, 50.0, 200.0]` | 물고기 성장 임계값 |
| `RENDER_INTERVAL` | `1` | 어항 화면 갱신 주기 (초) |

### 10-6. 팀원 인터페이스 계약

store / renderer 구현 시 반드시 지켜야 할 메서드 시그니처.

| 파일 | 메서드 | 호출 시점 |
|---|---|---|
| `store.py` | `DataStore(db_path)` | main.py 초기화 |
| `store.py` | `save_feed(feed: FeedData)` | FeedData 수신 시 |
| `store.py` | `update_fish_state(project_id: str, food_delta: float)` | FeedData 수신 시 |
| `store.py` | `get_fish_states() → list` | Renderer가 어항 그릴 때 |
| `renderer.py` | `AquariumRenderer(store)` | main.py 초기화 |
| `renderer.py` | `start()` | Orchestrator 시작 직전 |
| `renderer.py` | `stop()` | 프로세스 종료 시 |
| `renderer.py` | `on_feed(feed: FeedData)` | FeedData 수신 시 콜백 |

---

## 11. 테스트 구조

### 11-1. 테스트 파일 구성

```
tests/
├── conftest.py              공용 픽스처 + JSONL mock 헬퍼
├── base_limb_test.py        LimbContractMixin (모든 Limb 공통 계약)
├── test_claude_limb.py      ClaudeLimb 단위/통합 테스트
├── test_polling_mixin.py    PollingMixin 단위/통합 테스트
└── test_real_claude_scan.py 실제 ~/.claude/ 데이터 스캔 확인
```

### 11-2. 계층별 테스트 전략

| 계층 | 대상 | 방식 |
|---|---|---|
| 순수 함수 | `_project_name`, `_normalize`, `_project_id` | mock 없이 직접 호출 |
| 파일 파싱 | `_parse_offset` | `tmp_path` 가짜 JSONL |
| FeedData 생성 | `_parse_from_offset` | `tmp_path` 가짜 파일 |
| Limb 통합 | `watch()` 폴링 루프 | `threading` + `queue` |
| 실제 데이터 | 실제 `~/.claude/` 스캔 | skipif (디렉토리 없으면 건너뜀) |

### 11-3. mock JSONL 형식

테스트에서 사용하는 mock 데이터는 실제 Claude JSONL 형식과 동일하다.

```python
# conftest.py
def make_usage_line(input_tokens, output_tokens):
    return (
        '{"type": "assistant", "message": '
        '{"usage": {"input_tokens": N, "output_tokens": M}}}\n'
    )
```

### 11-4. 실행

```bash
# 가상환경 설정 (최초 1회)
cd tokenarium
python3 -m venv .venv
source .venv/bin/activate
pip install pytest

# 전체 테스트 (39개)
pytest tests/ -v

# 실제 Claude 데이터 확인 (stdout 출력 포함)
pytest tests/test_real_claude_scan.py -s -v
```

---

## 12. 파일 구조 및 현황

```
tokenarium/
├── CLAUDE.md                   ← AI 세션용 요약 (다음 세션 시작점)
├── docs/
│   └── architecture.md         ← 이 파일
├── tests/
│   ├── conftest.py             ✅ 공용 픽스처 + mock 헬퍼
│   ├── base_limb_test.py       ✅ LimbContractMixin
│   ├── test_claude_limb.py     ✅ 31개 테스트
│   ├── test_polling_mixin.py   ✅ 7개 테스트
│   └── test_real_claude_scan.py ✅ 실데이터 스캔 1개
└── aqua/
    ├── __main__.py             ✅ CLI 진입점
    ├── main.py                 ✅ 컴포넌트 배선 + 스텁 자동 감지
    ├── config.py               ✅ 전역 상수
    ├── interface.py            ✅ FeedData + BaseLimb 계약
    ├── orchestrator.py         ✅ Limb 생명주기 + 라우팅
    ├── store.py                🔲 DataStore 스텁 (구현 필요)
    ├── fish.py                 🔲 ASCII 아트 + 성장 단계 (구현 필요)
    ├── renderer.py             🔲 터미널 어항 렌더링 (구현 필요)
    └── limbs/
        ├── __init__.py         ✅
        ├── polling_mixin.py    ✅ pick_strategy() + PollingMixin
        ├── claude_limb.py      ✅ ~/.claude/**/*.jsonl 감시
        ├── codex_limb.py       ✅ ~/.codex/sessions/**/*.jsonl 감시
        ├── gemini_limb.py      ✅ ~/.gemini/**/*.json(l) 감시
        └── git_limb.py         ✅ COMMIT_EDITMSG 감시
```

### 구현 현황

| 파일 | 상태 | 비고 |
|---|---|---|
| `interface.py` | ✅ 완료 | FeedData + BaseLimb |
| `orchestrator.py` | ✅ 완료 | 스레드 관리 + 라우팅 |
| `config.py` | ✅ 완료 | 전역 상수 |
| `main.py` | ✅ 완료 | 배선 + 스텁 자동 감지 |
| `__main__.py` | ✅ 완료 | argparse CLI |
| `limbs/*.py` | ✅ 완료 | 실제 포맷 검증 완료 |
| `tests/` | ✅ 완료 | 39개 전부 통과 |
| `store.py` | 🔲 스텁 | ERD 확정 후 구현 |
| `fish.py` | 🔲 빈 파일 | ASCII 아트 + 성장 로직 구현 |
| `renderer.py` | 🔲 빈 파일 | blessed 기반 어항 렌더링 구현 |

### 의존성

| 패키지 | 버전 | 용도 |
|---|---|---|
| Python | 3.13.5 | 런타임 |
| pytest | 9.0.3 | 테스트 |
| watchdog | optional | 이벤트 기반 파일 감시 (없으면 polling 자동 전환) |
| blessed | optional | 터미널 UI (renderer.py 구현 시 필요) |

```bash
pip install watchdog   # 선택 (설치 시 파일 변화 반응 < 1초)
pip install blessed    # 선택 (renderer.py 구현 시 설치)
```

실행 방법
```bash
cd tokenarium
python -m aqua                         # 기본 실행
python -m aqua --dirs ~/Project/myapp  # git 프로젝트 지정
python -m aqua --interval 10           # 폴링 간격 변경
python -m aqua --db custom.db          # DB 경로 지정
```

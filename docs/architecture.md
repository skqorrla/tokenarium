# Tokenarium 아키텍처

> AI 토큰 사용량 · Git 커밋 수를 실시간 수집해 터미널 어항에 물고기로 시각화하는 CLI 툴.
> **프로젝트 1개 = 물고기 1마리.** 토큰/커밋이 쌓일수록 물고기가 성장한다.

---

## 목차

1. [한 줄 개념도](#1-한-줄-개념도)
2. [컴포넌트 구조](#2-컴포넌트-구조)
3. [데이터 모델 — FeedData](#3-데이터-모델--feeddata)
4. [전체 데이터 흐름](#4-전체-데이터-흐름)
5. [Orchestrator 상세](#5-orchestrator-상세)
6. [Limb 계층 구조](#6-limb-계층-구조)
7. [파일 감시 전략](#7-파일-감시-전략)
8. [물고기 성장 로직](#8-물고기-성장-로직)
9. [진입점 설계](#9-진입점-설계)
10. [파일 구조](#10-파일-구조)

---

## 1. 한 줄 개념도

```
사용자가 AI를 쓴다
      │
      ▼
AI 도구가 로그 파일에 기록한다   ← ~/.claude, ~/.codex, ~/.gemini, .git/
      │
      ▼
Limb(팔다리)가 파일 변화를 감지한다
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

## 2. 컴포넌트 구조

```
┌─────────────────────────────────────────────────────────┐
│                      python -m aqua                     │
├─────────────────────────────────────────────────────────┤
│                     MainComponent                       │
│                                                         │
│  ┌──────────────────────┐   ┌────────────────────────┐  │
│  │     Orchestrator     │◄──│   AquariumRenderer     │  │
│  │   (팔다리 관제탑)     │   │    (터미널 어항)        │  │
│  └──────────┬───────────┘   └────────────────────────┘  │
│             │ save / update            ▲                 │
│             ▼                on_feed 콜백                │
│  ┌──────────────────────┐             │                 │
│  │      DataStore       │─────────────┘                 │
│  │    (SQLite, 미구현)   │                               │
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

## 3. 데이터 모델 — FeedData

모든 팔다리가 생산하고, 몸통이 소비하는 **공통 화폐**다.

```
┌──────────────────────────────────────────┐
│               FeedData                   │
├──────────────┬───────────────────────────┤
│ project_id   │ sha256(cwd폴더명)[:8]     │  ← 물고기 식별자
│ project_name │ 프로젝트 폴더명           │  ← 어항에 표시
│ raw_value    │ 실제 토큰 수 / 커밋 수    │  ← 원시값
│ normalized   │ 0.0 ~ 1.0                 │  ← 물고기 밥 양
│ source       │ "claude"│"codex"│"gemini"│"git" │
│ timestamp    │ 수집 시각                 │
└──────────────┴───────────────────────────┘
```

**normalized 계산 방식**

| 소스 | 기준값 | 계산식 |
|---|---|---|
| claude | 100,000 토큰 | `tokens / 100_000` |
| codex | 100,000 토큰 | `tokens / 100_000` |
| gemini | 100,000 토큰 | `tokens / 100_000` |
| git | 50 커밋 | `commits / 50` |

---

## 4. 전체 데이터 흐름

```
[사용자 터미널]          [파일 시스템]              [어항 터미널]
──────────────          ──────────────────────      ────────────────────────────
                        ~/.claude/**/*.jsonl
claude 사용 ──append──► usage.input_tokens    ──►  ClaudeLimb
                        usage.output_tokens          │
                                                     │
codex  사용 ──append──► ~/.codex/**/*.json    ──►  CodexLimb
                        prompt_tokens                │
                        completion_tokens            │  FeedData 생성
                                                     │  {normalized: 0.0~1.0}
gemini 사용 ──append──► ~/.gemini/**/*.json   ──►  GeminiLimb
                        usageMetadata                │
                        .totalTokenCount             │
                                                     │
git commit  ──write───► .git/COMMIT_EDITMSG   ──►  GitLimb
                                                     │
                                              ┌──────┘
                                              │  thread-safe Queue
                                              ▼
                                    Orchestrator.run_dispatch_loop()
                                              │
                              ┌───────────────┴──────────────────┐
                              ▼                                   ▼
                         DataStore                        AquariumRenderer
                      fish_state 갱신                     어항 재렌더링
                    total_food += normalized
                              │
                        임계값 초과?
                              │
                            Yes → fish.size 증가
```

---

## 5. Orchestrator 상세

### 5-1. 생명주기

```
Orchestrator.start()
      │
      ├─ ClaudeLimb.is_available()?  ── Yes ──► daemon Thread 생성 ──► _watch_loop()
      ├─ CodexLimb.is_available()?   ── Yes ──► daemon Thread 생성 ──► _watch_loop()
      ├─ GeminiLimb.is_available()?  ── No  ──► skip (경고 출력)
      └─ GitLimb.is_available()?     ── Yes ──► daemon Thread 생성 ──► _watch_loop()
```

### 5-2. 스레드별 에러 처리

```
_watch_loop(limb)
      │
      ▼
  limb.watch() 호출
      │
  예외 발생?
      │
   Yes │                            No
      ▼                              ▼
limb.on_error(exc)            정상 동작 유지
retry_count++
      │
retry_count > 3?
      │
   Yes │                   No
      ▼                     ▼
  해당 Limb          RETRY_DELAY(5초) 후
  영구 비활성화       limb.watch() 재시작
```

### 5-3. 메인 디스패치 루프 (메인 스레드)

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

## 6. Limb 계층 구조

### 6-1. 클래스 관계

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

### 6-2. AI Limb 내부 구조 (Claude / Codex / Gemini 공통)

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

### 6-3. AI별 감시 경로 및 토큰 필드

| Limb | 감시 경로 | 파일 | 토큰 필드 |
|---|---|---|---|
| ClaudeLimb | `~/.claude/projects/` | `*.jsonl` | `usage.input_tokens` + `usage.output_tokens` |
| CodexLimb | `~/.codex/` | `*.json`, `*.jsonl` | `usage.prompt_tokens` + `usage.completion_tokens` |
| GeminiLimb | `~/.gemini/` or `~/.config/gemini/` | `*.json` | `usageMetadata.totalTokenCount` |
| GitLimb | `<project>/.git/` | `COMMIT_EDITMSG` | mtime 변화 횟수 |

**Claude 프로젝트 이름 추출 방식**
```
~/.claude/projects/ -home-user-Project-myapp /abc123.jsonl
                    └──────────────────────┘
                    rsplit("-", 1)[-1]  →  "myapp"
```

---

## 7. 파일 감시 전략

### 7-1. 전략 선택 (`pick_strategy()`)

```
pick_strategy() 호출
      │
watchdog 패키지
import 성공?
      │
   Yes │              No
      ▼               ▼
 "watchdog"        "polling"
 이벤트 기반       mtime 기반
 (< 1초 반응)      (5초 간격)
```

### 7-2. watchdog 전략

```
파일 변경 이벤트 발생 (on_modified)
      │
  .jsonl 파일인가?
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

### 7-3. polling 전략 (PollingMixin)

```
5초마다 반복:

  for path in _iter_target_files():
        │
    os.stat(path).st_mtime
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

### 7-4. byte offset 기반 증분 읽기 (중복 방지)

```
파일 내용:   [줄1][줄2][줄3][줄4][줄5]
                          ↑
                    이전 offset (줄3까지 읽음)

다음 이벤트: [줄1][줄2][줄3][줄4][줄5][줄6][줄7]
                          ↑──────────────────┘
                          여기서부터만 읽음 → 중복 없음
```

### 7-5. watchdog import 지연 처리

```python
# 모듈 로드 시점에 import하지 않음
# → watchdog 미설치 환경에서도 모듈 로드 가능

def _make_watchdog_handler(feed_queue):
    from watchdog.events import FileSystemEventHandler  # 지연 import
    ...
```

---

## 8. 물고기 성장 로직

### 8-1. 상태 머신

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

### 8-2. normalized 값이 필요한 이유

```
raw_value 직접 사용 시 문제:

  Claude:  50,000 토큰  →  물고기 밥 50,000개??
  Git:     3 커밋       →  물고기 밥 3개??

  단위가 달라 직접 비교 불가.

normalized 사용 시:

  Claude:  50,000 / 100,000 = 0.5
  Git:     3      / 50      = 0.06

  같은 스케일(0.0~1.0)로 물고기 밥 환산 가능.
  여러 소스의 기여도를 공정하게 합산.
```

---

## 9. 진입점 설계

### 9-1. 파일 역할 분담

```
__main__.py   CLI 인자 파싱 → main.run() 호출  (얇은 껍데기)
main.py       컴포넌트 초기화 + 배선           (로직 없음, 조립만)
config.py     전역 상수 정의                   (팀원 공유 기준점)
```

### 9-2. 실행 흐름

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

### 9-3. 스텁 컴포넌트 처리 전략

팀원의 store / renderer 구현이 완료되기 전에도 프로세스가 정상 실행된다.

```
_resolve_store(db_path)
      │
  DataStore(db_path) 생성
      │
  get_fish_states() 호출 (탐침)
      │
  NotImplementedError?
  ┌── Yes ──────────────────────────────────┐
  │   경고 출력                              │
  │   return _StubStore()  ← no-op 대체     │
  └─────────────────────────────────────────┘
      │
  No  │
      ▼
  return 실제 DataStore


_resolve_renderer(store)
      │
  from renderer import AquariumRenderer  (import 시도)
      │
  ImportError / NotImplementedError?
  ┌── Yes ──────────────────────────────────┐
  │   경고 출력                              │
  │   return None  ← print 콜백 사용        │
  └─────────────────────────────────────────┘
      │
  No  │
      ▼
  return AquariumRenderer(store)
```

### 9-4. 종료 흐름

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

### 9-5. config.py 항목

| 상수 | 기본값 | 설명 |
|---|---|---|
| `DB_PATH` | `"aqua.db"` | SQLite 파일 경로 |
| `POLL_INTERVAL` | `5` | polling fallback 간격 (초) |
| `GIT_WATCH_DIRS` | `[]` | 감시할 git 프로젝트 경로 목록 |
| `GROWTH_THRESHOLDS` | `[10.0, 50.0, 200.0]` | 물고기 성장 임계값 (소/중/대) |
| `RENDER_INTERVAL` | `1` | 어항 화면 갱신 주기 (초) |

> `--interval N` CLI 인자가 들어오면 `__main__.py`에서 `config.POLL_INTERVAL`을 오버라이드한다.

### 9-6. 팀원 인터페이스 계약

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

## 10. 파일 구조

```
tokenarium/
├── CLAUDE.md                   ← AI 세션용 요약 (다음 세션 시작점)
├── docs/
│   └── architecture.md         ← 이 파일
└── aqua/
    ├── __main__.py             ✅ CLI 진입점 (python -m aqua)
    ├── main.py                 ✅ 컴포넌트 배선 + 실행 루프
    ├── config.py               ✅ 전역 설정 상수
    │
    ├── interface.py            ✅ FeedData + BaseLimb 계약
    ├── orchestrator.py         ✅ Limb 생명주기 + 라우팅
    │
    ├── store.py                🔲 DataStore 스텁 (ERD 설계 전, 로직 없음)
    ├── fish.py                 🔲 빈 파일 (물고기 ASCII + 성장 단계)
    ├── renderer.py             🔲 빈 파일 (터미널 어항 렌더링)
    │
    └── limbs/
        ├── __init__.py         ✅
        ├── polling_mixin.py    ✅ pick_strategy() + PollingMixin
        ├── claude_limb.py      ✅ JSONL 감시
        ├── codex_limb.py       ✅ JSON 감시
        ├── gemini_limb.py      ✅ JSON 감시
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
| `limbs/*.py` | ✅ 완료 | Claude / Codex / Gemini / Git |
| `store.py` | 🔲 스텁 | ERD 확정 후 구현 필요 |
| `fish.py` | 🔲 빈 파일 | ASCII 아트 + 성장 로직 구현 필요 |
| `renderer.py` | 🔲 빈 파일 | blessed 기반 어항 렌더링 구현 필요 |

### 팀원 구현 시 참고

`main.py`가 스텁 자동 감지 로직을 갖고 있으므로, 구현 완료 후 별도 연결 작업 불필요.

```
store.py    → save_feed(), update_fish_state(), get_fish_states() 구현
fish.py     → ASCII 아트 상수, 성장 임계값 로직 구현
renderer.py → AquariumRenderer(store), start(), stop(), on_feed(feed) 구현
```

---

## 의존성

```
pip install watchdog   # 파일 감시 (없으면 polling으로 자동 전환)
pip install blessed    # 터미널 UI (renderer.py 구현 시 필요)
```

실행 방법
```bash
cd tokenarium
python -m aqua                        # 기본 실행
python -m aqua --dirs ~/Project/myapp # git 프로젝트 지정
python -m aqua --interval 10          # 폴링 간격 변경
python -m aqua --db custom.db         # DB 경로 지정
```

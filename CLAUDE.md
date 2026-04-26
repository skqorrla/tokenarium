# Tokenarium - CLAUDE.md

AI 토큰 사용량과 git 커밋 수를 실시간으로 수집해 터미널 어항에 물고기로 시각화하는 CLI 툴.
프로젝트 1개 = 물고기 1마리. 토큰/커밋이 쌓일수록 물고기가 성장한다.
AI 해커톤 입상 목적 프로젝트.

---

## 프로젝트 구조

```
tokenarium/
├── CLAUDE.md
├── docs/
│   └── architecture.md
└── aqua/
    ├── __main__.py          ✅ CLI 진입점 (python -m aqua)
    ├── main.py              ✅ 컴포넌트 배선 + 실행 루프
    ├── config.py            ✅ 전역 설정 상수
    ├── interface.py         ✅ BaseLimb 추상 클래스 + FeedData 데이터클래스
    ├── orchestrator.py      ✅ Limb 생명주기 관리 + FeedData 라우팅
    ├── store.py             🔲 DataStore 스텁 (ERD 설계 전, 로직 없음)
    ├── fish.py              🔲 물고기 ASCII + 성장 단계 (빈 파일)
    ├── renderer.py          🔲 터미널 어항 렌더링 (빈 파일)
    └── limbs/
        ├── __init__.py      ✅
        ├── polling_mixin.py ✅ watchdog fallback 폴링 로직
        ├── claude_limb.py   ✅ Claude JSONL 감시
        ├── codex_limb.py    ✅ Codex JSON 감시
        ├── gemini_limb.py   ✅ Gemini JSON 감시
        └── git_limb.py      ✅ .git/COMMIT_EDITMSG 감시
```

---

## 핵심 아키텍처

### 컴포넌트 관계

```
MainComponent (main.py)
├── Orchestrator          ← Limb 스레드 관리, FeedData 라우팅
│   ├── ClaudeLimb  ┐
│   ├── CodexLimb   ├── 각각 daemon 스레드, feed_queue로 데이터 전송
│   ├── GeminiLimb  │
│   └── GitLimb     ┘
├── DataStore             ← SQLite 영속화 (ERD 미확정)
└── AquariumRenderer      ← 터미널 어항 출력
```

### 데이터 흐름

```
AI 사용 → 파일 기록 → Limb 감지 → FeedData → feed_queue
                                                    ↓
                                          Orchestrator.run_dispatch_loop()
                                                    ↓
                                    DataStore.update_fish_state()
                                                    ↓
                                          AquariumRenderer 갱신
```

---

## 인터페이스 계약 (interface.py)

```python
@dataclass
class FeedData:
    project_id: str      # sha256(cwd)[:8]
    project_name: str    # 폴더명
    raw_value: float     # 원시값 (토큰 수, 커밋 수)
    normalized: float    # 0.0 ~ 1.0  ← 물고기 밥 양
    source: str          # "claude" | "codex" | "gemini" | "git"
    timestamp: datetime

class BaseLimb(ABC):
    name: str            # 팔다리 식별자
    is_available() → bool
    watch(feed_queue, stop_event) → None  # Orchestrator가 daemon 스레드에서 호출
    on_error(exc)        # 에러 시 Orchestrator가 호출 (기본: 로그 출력)
```

---

## Orchestrator 동작 방식

1. `register(limb)` → `is_available()` 통과한 Limb만 등록
2. `start()` → 각 Limb를 독립 daemon 스레드로 실행
3. 예외 발생 시 `MAX_RETRIES(3)` 내 자동 재시작, 초과 시 해당 Limb 비활성화
4. `run_dispatch_loop()` [메인 스레드] → Queue 소비 → DataStore 저장 → Renderer 콜백

---

## 파일 감시 전략 (polling_mixin.py)

`pick_strategy()` 가 환경을 자동 감지해 Limb에게 전략을 지정한다.

| 전략 | 조건 | 지연 |
|---|---|---|
| `"watchdog"` | watchdog 패키지 설치됨 | < 1초 |
| `"polling"` | watchdog 미설치 fallback | 5초 간격 |

- 공통 파싱: **byte offset 기반 증분 읽기** (중복 방지)
- watchdog import는 각 Limb의 `_watchdog_watch()` 내부에서 **지연 import** → watchdog 미설치 시에도 모듈 로드 가능
- TODO: Linux/WSL inotify 직접 호출 전략 추가 가능 (ctypes IN_MODIFY)

### AI Limb 공통 구조 (claude / codex / gemini)

```python
class XxxLimb(BaseLimb, PollingMixin):
    def watch(self, feed_queue, stop_event):
        if pick_strategy() == "watchdog":
            self._watchdog_watch(...)   # watchdog Observer 사용
        else:
            self._poll_watch(...)       # PollingMixin 루프 사용

    def _iter_target_files(self): ...   # 폴링 대상 파일 목록
    def _parse_from_offset(self, path, offset): ...  # 증분 파싱 → FeedData
```

### Git Limb

PollingMixin 미사용. `COMMIT_EDITMSG` mtime 비교로 단독 구현.
커밋 1회 = mtime 변화 1회 = FeedData 1개 발행.

---

## 각 AI의 감시 경로 및 토큰 필드

| AI | 감시 경로 | 토큰 필드 |
|---|---|---|
| Claude | `~/.claude/projects/**/*.jsonl` | `usage.input_tokens` + `usage.output_tokens` |
| Codex | `~/.codex/**/*.json(l)` | `usage.prompt_tokens` + `usage.completion_tokens` |
| Gemini | `~/.gemini/**/*.json` or `~/.config/gemini/` | `usageMetadata.totalTokenCount` |
| Git | `<project>/.git/COMMIT_EDITMSG` | mtime 변화 횟수 (커밋 카운트) |

Claude 프로젝트 식별: `-home-user-Project-myapp` 폴더명 → `rsplit("-",1)[-1]` → `"myapp"`

---

## 물고기 성장 단계 (fish.py 구현 예정)

| 누적 food | 크기 | ASCII |
|---|---|---|
| 0 ~ 10 | 치어(1) | `><>` |
| 10 ~ 50 | 소(2) | `><))>` |
| 50 ~ 200 | 중(3) | `><)))>` |
| 200+ | 대(4) | `><((((>` |

---

## 구현 현황

| 파일 | 상태 | 담당 |
|---|---|---|
| `interface.py` | ✅ 완료 | |
| `orchestrator.py` | ✅ 완료 | |
| `config.py` | ✅ 완료 | |
| `main.py` | ✅ 완료 | |
| `__main__.py` | ✅ 완료 | |
| `limbs/*.py` | ✅ 완료 | |
| `store.py` | 🔲 스텁 | 팀원 A |
| `fish.py` | 🔲 빈 파일 | 팀원 B |
| `renderer.py` | 🔲 빈 파일 | 팀원 C |

---

## 팀원 구현 계약 (store / fish / renderer)

`main.py`가 스텁 자동 감지를 하므로, 구현 완료 시 별도 연결 작업 불필요.

```
store.py    save_feed(feed), update_fish_state(id, delta), get_fish_states()
renderer.py AquariumRenderer(store), start(), stop(), on_feed(feed)
fish.py     renderer.py가 import해서 사용 (ASCII 아트, 성장 임계값)
```

---

## 의존성

```
watchdog   # 파일 시스템 이벤트 감시 (optional, 없으면 polling 자동 전환)
blessed    # 터미널 UI 렌더링 (renderer.py 구현 시 필요)
```

실행: `python -m aqua` (aqua/ 상위 디렉토리에서)

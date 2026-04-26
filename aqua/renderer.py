"""renderer.py - 터미널 어항 TUI (textual 기반)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import fish as fish_module
from fish import WAVE_FRAMES, SEAWEED_FRAMES, STAGE_DECO, get_species_for_xp, get_next_xp_milestone

from textual.app import App, ComposeResult
from textual.widgets import Static
from textual.containers import Horizontal, ScrollableContainer
from textual.binding import Binding
from textual.widget import Widget
from rich.markup import escape


# ── 어항 렌더 헬퍼 ────────────────────────────────────────────────── #

def _build_aquarium(
    fish_data: dict, tick: int, fish_x: int, fish_dir: int, border_flash: bool
) -> str:
    species  = fish_data.get("species", "🐟")
    stage    = fish_data.get("aquarium_stage", 1)
    fullness = fish_data.get("fullness", 50)

    wave = WAVE_FRAMES[tick % 3]
    deco = STAGE_DECO.get(stage, STAGE_DECO[1])
    sw   = SEAWEED_FRAMES[(tick // 3) % 2] if deco["seaweed"] else " "

    x         = max(0, min(fish_x, 44))
    seaweed_l = f"  {sw}  "
    seaweed_r = f"  {sw}"
    row_fish  = seaweed_l + " " * x + species + " " * max(0, 44 - x) + seaweed_r
    row_empty = seaweed_l + " " * 44 + seaweed_r

    if fullness < 30:
        body = [wave, "       °            °     °", row_empty, row_fish]
    else:
        body = [wave, "       °            °     °", row_fish, "                °          °"]

    if deco["rock"] and deco["coral"]:
        bottom = "  🌿 🪨 " + "░" * 36 + " 🐚 🌿"
    elif deco["seaweed"]:
        bottom = "  🌿 " + "░" * 44 + " 🌿"
    else:
        bottom = "  " + "░" * 48
    body.append(bottom)

    if border_flash:
        return "\n".join(f"[bold green]{r}[/bold green]" for r in body)
    return "\n".join(body)


def _fullness_bar(fullness: int, width: int = 10) -> str:
    filled = round(fullness * width / 100)
    bar = "█" * filled + "░" * (width - filled)
    if fullness >= 70:
        return f"[green]{bar}[/green]"
    if fullness >= 30:
        return f"[yellow]{bar}[/yellow]"
    return f"[red]{bar}[/red]"


def _xp_bar(xp: int, width: int = 10) -> str:
    nxt = get_next_xp_milestone(xp)
    if nxt is None:
        return f"[cyan]{'█' * width}[/cyan]  {xp} XP (MAX)"
    cur_req = get_species_for_xp(xp)["xp_required"]
    span    = nxt - cur_req
    filled  = min(width, int((xp - cur_req) * width / span)) if span > 0 else width
    bar     = "█" * filled + "░" * (width - filled)
    return f"[cyan]{bar}[/cyan]  {xp} / {nxt} XP"


# ── 카드 위젯 (Screen 2용) ────────────────────────────────────────── #

class FishCard(Static):
    DEFAULT_CSS = """
    FishCard {
        border: solid #30363d;
        height: 6;
        padding: 0 1;
        margin-right: 2;
        margin-bottom: 1;
    }
    FishCard.danger { border: solid #f85149; }
    """

    def __init__(self, fish_data: dict, **kwargs):
        super().__init__(FishCard._build(fish_data), **kwargs)
        self._fish = fish_data

    @staticmethod
    def _build(f: dict) -> str:
        dir_str = str(f.get("dir", ""))
        if len(dir_str) > 22:
            dir_str = "..." + dir_str[-19:]
        name     = escape(f.get("name", "?"))
        level    = f.get("level", 1)
        species  = f.get("species", "🐟")
        name_kr  = escape(f.get("name_kr", "") or "")
        fullness = f.get("fullness", 0)
        filled   = round(fullness * 7 / 100)
        bar      = "█" * filled + "░" * (7 - filled)
        if fullness >= 70:
            bar_c = f"[green]{bar}[/green]"
        elif fullness >= 30:
            bar_c = f"[yellow]{bar}[/yellow]"
        else:
            bar_c = f"[red]{bar}[/red]"
        warn = " ⚠" if fullness < 30 else ""
        return (
            f"[dim]{escape(dir_str)}[/dim]\n"
            f"[cyan]{name}[/cyan]  Lv.{level}  {species} {name_kr}\n"
            f"{bar_c}  {fullness}%{warn}"
        )

    def update_data(self, fish: dict) -> None:
        self._fish = fish
        self.update(FishCard._build(fish))
        if fish.get("fullness", 100) < 30:
            self.add_class("danger")
        else:
            self.remove_class("danger")



class FishGrid(Widget):
    DEFAULT_CSS = """
    FishGrid {
        layout: grid;
        grid-size: 2;
        grid-gutter: 0;
        padding: 1 2;
        height: auto;
    }
    """


# ── Screen 1: tokenarium watch ────────────────────────────────────── #

class WatchApp(App):
    CSS = """
    Screen {
        background: #0d1117;
        color: #e6edf3;
    }
    #title-bar {
        height: 1;
        background: #161b22;
        padding: 0 1;
    }
    .sep {
        height: 1;
        color: #30363d;
        background: #0d1117;
    }
    #aquarium {
        height: 8;
        padding: 0 1;
        width: 100%;
        background: #0d1117;
    }
    #aquarium.flash { background: #0d2a1a; }
    #stats-row { height: 7; }
    #fish-panel {
        width: 1fr;
        padding: 0 2;
        border-right: solid #30363d;
    }
    #food-panel {
        width: 1fr;
        padding: 0 2;
    }
    #activity {
        padding: 0 2;
        height: auto;
        min-height: 3;
    }
    #feedback { height: 1; padding: 0 2; }
    """

    BINDINGS = [
        Binding("f", "feed", "먹이주기"),
        Binding("q", "quit", "종료"),
    ]

    def __init__(self, store, dir_path: str):
        super().__init__()
        self._store          = store
        self._dir            = dir_path
        self._tick           = 0
        self._fish_x         = 12
        self._fish_dir       = 1
        self._fish_data: dict = {}
        self._feedback        = ""
        self._feedback_ticks  = 0
        self._border_flash    = 0

    def compose(self) -> ComposeResult:
        yield Static(
            "tokenarium  [bold][[f]][/bold] 먹이주기  [bold][[q]][/bold] 종료",
            id="title-bar",
        )
        yield Static("─" * 200, classes="sep")
        yield Static("", id="aquarium")
        yield Static("─" * 200, classes="sep")
        yield Horizontal(
            Static("", id="fish-panel"),
            Static("", id="food-panel"),
            id="stats-row",
        )
        yield Static("─" * 200, classes="sep")
        yield Static("", id="activity")
        yield Static("", id="feedback")

    def on_mount(self) -> None:
        self._fish_data = self._store.get_fish_by_dir(self._dir) or {}
        self._refresh_all()
        self.set_interval(config.UI_REFRESH_INTERVAL, self._on_tick)

    def _on_tick(self) -> None:
        self._tick += 1
        self._fish_data = self._store.get_fish_by_dir(self._dir) or {}

        fullness = self._fish_data.get("fullness", 50)
        if fullness > 70:
            move = True
        elif fullness >= 30:
            move = (self._tick % 2 == 0)
        else:
            move = (self._tick % 4 == 0)

        if move:
            self._fish_x += self._fish_dir
            if self._fish_x >= 42:
                self._fish_dir = -1
            elif self._fish_x <= 2:
                self._fish_dir = 1

        if self._feedback_ticks > 0:
            self._feedback_ticks -= 1
        if self._border_flash > 0:
            self._border_flash -= 1

        self._refresh_all()

    def _refresh_all(self) -> None:
        self._update_aquarium()
        self._update_stats()
        self._update_activity()
        self._update_feedback()

    def _update_aquarium(self) -> None:
        content = _build_aquarium(
            self._fish_data, self._tick, self._fish_x, self._fish_dir,
            self._border_flash > 0,
        )
        aq = self.query_one("#aquarium", Static)
        aq.update(content)
        if self._border_flash > 0:
            aq.add_class("flash")
        else:
            aq.remove_class("flash")

    def _update_stats(self) -> None:
        f        = self._fish_data
        name     = escape(f.get("name", "???"))
        level    = f.get("level", 1)
        species  = f.get("species", "🐟")
        name_kr  = escape(f.get("name_kr") or "새끼 물고기")
        fullness = f.get("fullness", 0)
        xp       = f.get("xp", 0)
        stock    = f.get("food_stock", 0)

        self.query_one("#fish-panel", Static).update(
            f"[bold]물고기[/bold]\n"
            f"[cyan]{name}[/cyan]  Lv.{level}  {species} {name_kr}\n\n"
            f"[bold]포만감[/bold]\n"
            f"{_fullness_bar(fullness)}  {fullness}%"
        )
        self.query_one("#food-panel", Static).update(
            f"[bold]먹이 재고[/bold]\n"
            f"🍖 {stock:,} 토큰\n"
            f"급여 1회 = {config.FOOD_COST_PER_FEED:,} 차감 / +{config.FULLNESS_PER_FEED}%\n\n"
            f"[bold]경험치[/bold]\n"
            f"{_xp_bar(xp)}"
        )

    def _update_activity(self) -> None:
        project_id = self._fish_data.get("project_id")
        stub = "[bold]오늘 활동[/bold]\n(활동 없음)"
        if not project_id:
            self.query_one("#activity", Static).update(stub)
            return
        acts = self._store.get_today_activity(project_id)
        if not acts:
            self.query_one("#activity", Static).update(stub)
            return

        lines = ["[bold]오늘 활동[/bold]"]
        total_tok = total_diff = total_xp = 0
        for a in acts:
            label = a["agent_name"]
            if a.get("model_name"):
                short = (
                    a["model_name"]
                    .replace("claude-", "")
                    .replace("gemini-", "")
                    .replace("gpt-", "")
                )
                label += f"-{short}"
            tok  = a.get("tokens", 0) or 0
            diff = a.get("diff",   0) or 0
            xp_v = a.get("xp",    0) or 0
            lines.append(
                f"[cyan]{label:<20}[/cyan] {tok:>8,} tok   ±{diff:>5}줄   → +{xp_v} XP"
            )
            total_tok += tok
            total_diff += diff
            total_xp   += xp_v

        lines.append("─" * 56)
        lines.append(
            f"[bold]{'합계':<20}[/bold] {total_tok:>8,} tok"
            f"   ±{total_diff:>5}줄   → +{total_xp} XP 오늘"
        )
        self.query_one("#activity", Static).update("\n".join(lines))

    def _update_feedback(self) -> None:
        self.query_one("#feedback", Static).update(
            self._feedback if self._feedback_ticks > 0 else ""
        )

    def action_feed(self) -> None:
        f = self._fish_data
        if not f:
            return
        result = self._store.feed_fish(f["id"], f["project_id"])
        if result["success"]:
            self._feedback = (
                f"[green]{result['stock_before']:,} → {result['stock_after']:,} 토큰 "
                f"(-{config.FOOD_COST_PER_FEED:,}) / "
                f"포만감 {result['fullness_before']}% → {result['fullness_after']}% "
                f"(+{config.FULLNESS_PER_FEED}%)[/green]"
            )
            self._border_flash = 1
        else:
            self._feedback = f"[red]{result['message']}[/red]"
        self._feedback_ticks = 4
        self.query_one("#feedback", Static).update(self._feedback)


# ── Screen 2: tokenarium (전체 어항) ──────────────────────────────── #

class AquariumApp(App):
    CSS = """
    Screen {
        background: #0d1117;
        color: #e6edf3;
    }
    #header {
        height: 1;
        background: #161b22;
        padding: 0 1;
    }
    .sep {
        height: 1;
        color: #30363d;
        background: #0d1117;
    }
    FishCard {
        border: solid #30363d;
        height: 6;
        padding: 0 1;
        margin-right: 2;
        margin-bottom: 1;
    }
    FishCard.danger { border: solid #f85149; }
    FishGrid {
        layout: grid;
        grid-size: 2;
        grid-gutter: 0;
        padding: 1 2;
        height: auto;
    }
    """

    BINDINGS = [Binding("q", "quit", "종료")]

    def __init__(self, store):
        super().__init__()
        self._store      = store
        self._fish_count = -1

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        yield Static("─" * 200, classes="sep")
        yield ScrollableContainer(FishGrid(id="fish-grid"))

    def on_mount(self) -> None:
        self._rebuild()
        self.set_interval(config.UI_REFRESH_INTERVAL, self._refresh)

    def _rebuild(self) -> None:
        fish_list = self._store.get_all_fish_with_state()
        grid = self.query_one("#fish-grid", FishGrid)
        grid.remove_children()
        for fish in fish_list:
            card = FishCard(fish)
            if fish.get("fullness", 100) < 30:
                card.add_class("danger")
            grid.mount(card)
        self._fish_count = len(fish_list)
        self._update_header(fish_list)

    def _update_header(self, fish_list: list) -> None:
        total = sum(f.get("food_stock", 0) for f in fish_list)
        self.query_one("#header", Static).update(
            f"내 어항   🍖 {total:,} 토큰 보유   [bold][[q]][/bold] 종료"
        )

    def _refresh(self) -> None:
        fish_list = self._store.get_all_fish_with_state()
        self._update_header(fish_list)
        if len(fish_list) != self._fish_count:
            self._rebuild()
            return
        for card, fish in zip(self.query(FishCard), fish_list):
            card.update_data(fish)


# ── main.py AquariumRenderer 호환 래퍼 ────────────────────────────── #

class AquariumRenderer:
    def __init__(self, store):
        self._store = store

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def on_feed(self, feed) -> None:
        pass


def run_watch_app(store, dir_path: str) -> None:
    WatchApp(store, dir_path).run()


def run_aquarium_app(store) -> None:
    AquariumApp(store).run()

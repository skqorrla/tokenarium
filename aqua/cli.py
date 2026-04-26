"""cli.py - tokenarium CLI 진입점 (click 기반).

tokenarium        현재 프로젝트 물고기 뷰 (기본)
tokenarium all    어항 전체 뷰 (모든 물고기)
tokenarium init   현재 디렉토리 프로젝트 등록
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import click
import config
from store import DataStore


def _get_store() -> DataStore:
    store = DataStore(config.DB_PATH)
    store.init_db()
    store.seed_data()
    return store


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """Tokenarium — AI 토큰 사용량을 터미널 어항으로 시각화"""
    if ctx.invoked_subcommand is not None:
        return

    store    = _get_store()
    dir_path = str(Path.cwd())

    if not store.project_has_fish(dir_path):
        click.echo(
            "이 프로젝트는 등록되지 않았어요. tokenarium init 을 실행하세요."
        )
        raise SystemExit(0)

    from renderer import run_watch_app
    run_watch_app(store, dir_path)


@main.command()
@click.option("-y", "--yes", is_flag=True, help="확인 프롬프트 없이 바로 삭제")
def delete(yes: bool) -> None:
    """현재 프로젝트 물고기 삭제."""
    store    = _get_store()
    dir_path = str(Path.cwd())

    fish = store.get_fish_by_dir(dir_path)
    if fish is None:
        click.echo("이 프로젝트에 등록된 물고기가 없습니다.")
        return

    click.echo(f"  {fish['species']} {fish['name']}  Lv.{fish['level']}  xp={fish['xp']}")
    if not yes:
        click.confirm("정말 삭제할까요? 관련 토큰 기록도 모두 사라집니다", abort=True)

    store.delete_fish(dir_path)
    click.echo(f"'{fish['name']}' 을(를) 삭제했습니다.")


@main.command()
def all() -> None:
    """전체 어항 뷰 — 모든 물고기 현황."""
    store = _get_store()
    from renderer import run_aquarium_app
    run_aquarium_app(store)


@main.command()
def init() -> None:
    """현재 디렉토리 프로젝트 등록, 물고기 이름 입력."""
    store    = _get_store()
    dir_path = str(Path.cwd())

    if store.project_has_fish(dir_path):
        fish = store.get_fish_by_dir(dir_path)
        assert fish
        click.echo(
            f"이미 {fish['name']} ({fish['species']} Lv.{fish['level']}) 이 있어요!"
        )
        return

    click.echo("새로운 물고기를 만들어봐요! 🐟\n")
    click.echo(f"프로젝트 경로: {dir_path}\n")
    name = click.prompt("물고기 이름을 지어주세요")
    if not name.strip():
        click.echo("이름을 입력해주세요.", err=True)
        raise SystemExit(1)

    project_id = store.register_project(dir_path)
    fish_info  = store.create_fish(project_id, name.strip())

    click.echo(f"\n{fish_info['name']} (Lv.1 🐟 새끼 물고기) 를 만들었어요!")

    from renderer import run_watch_app
    run_watch_app(store, dir_path)

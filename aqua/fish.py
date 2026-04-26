"""fish.py - 물고기 종 데이터, 어항 단계, 애니메이션 상수 및 유틸리티."""

from __future__ import annotations

FISH_SPECIES: list[dict] = [
    {"level_min": 1,  "emoji": "🐟", "name_kr": "새끼 물고기", "xp_required": 0,     "is_legendary": False},
    {"level_min": 3,  "emoji": "🐠", "name_kr": "열대어",      "xp_required": 100,   "is_legendary": False},
    {"level_min": 5,  "emoji": "🐡", "name_kr": "복어",        "xp_required": 300,   "is_legendary": False},
    {"level_min": 8,  "emoji": "🦀", "name_kr": "게",          "xp_required": 700,   "is_legendary": False},
    {"level_min": 10, "emoji": "🦞", "name_kr": "바닷가재",    "xp_required": 1200,  "is_legendary": False},
    {"level_min": 13, "emoji": "🦑", "name_kr": "오징어",      "xp_required": 2000,  "is_legendary": False},
    {"level_min": 15, "emoji": "🐙", "name_kr": "문어",        "xp_required": 2800,  "is_legendary": False},
    {"level_min": 18, "emoji": "🐢", "name_kr": "거북이",      "xp_required": 4000,  "is_legendary": False},
    {"level_min": 20, "emoji": "🐬", "name_kr": "돌고래",      "xp_required": 5500,  "is_legendary": False},
    {"level_min": 25, "emoji": "🦈", "name_kr": "상어",        "xp_required": 8000,  "is_legendary": False},
    {"level_min": 30, "emoji": "🐳", "name_kr": "고래",        "xp_required": 12000, "is_legendary": True},
]

AQUARIUM_STAGES: list[dict] = [
    {"stage": 1, "level_min": 1,  "description": "거품과 물고기만", "decorations": "° °"},
    {"stage": 2, "level_min": 10, "description": "해초 추가",       "decorations": "🌿 ° 🌿"},
    {"stage": 3, "level_min": 20, "description": "바위·조개 추가",  "decorations": "🌿 🪨 🐚"},
    {"stage": 4, "level_min": 25, "description": "풀 생태계",       "decorations": "🌿 🪨 🐚 🌊"},
]

WAVE_FRAMES: list[str] = [
    "  ~    ~         ~              ~    ~  ",
    "   ~    ~         ~              ~    ~ ",
    "  ~ ~    ~         ~             ~    ~ ",
]

SEAWEED_FRAMES: list[str] = ["🌿", "🌾"]

STAGE_DECO: dict[int, dict] = {
    1: {"seaweed": False, "rock": False, "coral": False, "current": False},
    2: {"seaweed": True,  "rock": False, "coral": False, "current": False},
    3: {"seaweed": True,  "rock": True,  "coral": True,  "current": False},
    4: {"seaweed": True,  "rock": True,  "coral": True,  "current": True},
}

# 이모지 미지원 환경 fallback
EMOJI_FALLBACK: dict[str, str] = {
    "🐟": "><>",
    "🐠": "><))>",
    "🐡": "><)))>",
    "🦀": "(°v°)",
    "🦞": ">===>",
    "🦑": ">~~>",
    "🐙": "~O~",
    "🐢": "@~~@",
    "🐬": "<><",
    "🦈": ">^^^>",
    "🐳": "><((((>",
    "🌿": "|",
    "🌾": "/",
}


def get_species_for_xp(xp: int) -> dict:
    """XP 기반 현재 종 반환."""
    result = FISH_SPECIES[0]
    for sp in FISH_SPECIES:
        if xp >= sp["xp_required"]:
            result = sp
    return result


def get_level_for_xp(xp: int) -> int:
    return get_species_for_xp(xp)["level_min"]


def get_next_xp_milestone(xp: int) -> int | None:
    """다음 종 진화에 필요한 XP. 최대 레벨이면 None."""
    for sp in FISH_SPECIES:
        if sp["xp_required"] > xp:
            return sp["xp_required"]
    return None


def get_aquarium_stage_for_level(level: int) -> int:
    stage = 1
    for aq in AQUARIUM_STAGES:
        if level >= aq["level_min"]:
            stage = aq["stage"]
    return stage


def get_name_kr_for_level(level: int) -> str:
    name = "새끼 물고기"
    for sp in FISH_SPECIES:
        if level >= sp["level_min"]:
            name = sp["name_kr"]
    return name

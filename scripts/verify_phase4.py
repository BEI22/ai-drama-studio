"""Phase 4 acceptance checks: Episode Agent, scripts, storyboards, shots.

Exercises the real HTTP surface end to end against a running backend: planning,
script generation, storyboard generation, shot persistence, id binding, the
re-run guards and cross-user isolation.

Why Python rather than curl+bash: on Windows/git-bash, non-ASCII JSON passed
inline via ``curl -d`` gets re-encoded by the shell and the backend rejects the
body with "There was an error parsing the body" (HTTP 400). Encoding the payload
explicitly as UTF-8 removes that whole class of false failure -- see
docs/TDD.md section 16.

Usage::

    python scripts/verify_phase4.py [backend_base_url]
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any

BACKEND = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
API = f"{BACKEND}/api/v1"

PASSWORD = "episodetime2026"
STAMP = uuid.uuid4().hex[:8]
A_EMAIL = f"episode-a+{STAMP}@example.com"
B_EMAIL = f"episode-b+{STAMP}@example.com"

STORY = (
    "林澈在大学宿舍的床上睁开眼，发现自己竟然回到了十年前的开学日。"
    "前世他因为沉迷游戏错过保研，毕业后四处碰壁，最后在出租屋里郁郁而终。"
    "这一次，他决定改变自己的人生。室友赵明达推开宿舍门，喊他一起去食堂。"
    "林澈没有说话，只是握紧了拳头。班主任周老师走进教室，宣布了考研的报名时间。"
    "苏晚坐在他旁边的座位上，笑着说：林澈，你这次一定要加油。"
    "他翻开课本，第一页上写着自己十年前的笔迹。"
)

PASS = 0
FAIL = 0


def check(label: str, expected: Any, actual: Any) -> None:
    global PASS, FAIL
    if expected == actual:
        print(f"  PASS  {label}")
        PASS += 1
    else:
        print(f"  FAIL  {label}\n        expected: {expected!r}\n        actual:   {actual!r}")
        FAIL += 1


def check_true(label: str, condition: bool, detail: Any = None) -> None:
    check(label + ("" if condition else f" [{detail!r}]"), True, bool(condition))


def check_subset(label: str, actual: set, allowed: set) -> None:
    """Assert ``actual`` is contained in ``allowed``, naming the offenders.

    Used for the id-binding checks (PRD section 10), where the useful failure
    output is *which* id did not resolve rather than a bare False.
    """
    extra = actual - allowed
    check(label + ("" if not extra else f" [unresolved: {sorted(extra)}]"), set(), extra)


def script_states(episodes: list[dict]) -> list[str]:
    return [e["script_status"] for e in episodes]


def board_states(episodes: list[dict]) -> list[str]:
    return [e["storyboard_status"] for e in episodes]


def field_values(items: list[dict], field: str) -> set:
    return {item[field] for item in items}


def check_status(label: str, expected: int, status: int, payload: Any) -> None:
    """Like check(), but a status mismatch also reports the API error code.

    A bare "expected 200, actual 422" cannot be diagnosed from the log alone --
    the error code (and message) is what tells you whether it was input
    validation, a provider failure, or a conflict.
    """
    if status == expected:
        check(label, expected, status)
        return

    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    global FAIL
    print(f"  FAIL  {label}\n        expected: {expected}\n        actual:   {status}")
    if code or message:
        print(f"        error:    code={code} message={message}")
    FAIL += 1


def call(
    method: str,
    path: str,
    *,
    body: dict | None = None,
    token: str | None = None,
) -> tuple[int, Any]:
    """Return (status_code, parsed_json_or_raw_text)."""
    url = f"{API}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None

    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json; charset=utf-8")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        status = error.code
    except urllib.error.URLError as error:
        print(f"  !! cannot reach {url}: {error}")
        sys.exit(2)

    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def data_of(payload: Any) -> Any:
    return payload.get("data") if isinstance(payload, dict) else None


def error_code(payload: Any) -> Any:
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        return payload["error"].get("code")
    return None


# --------------------------------------------------------------------- setup
print("== setup ==")

status, payload = call("POST", "/auth/register", body={"email": A_EMAIL, "password": PASSWORD})
check("register A -> 201", 201, status)
a_token = data_of(payload)["access_token"]

_, payload = call("POST", "/auth/register", body={"email": B_EMAIL, "password": PASSWORD})
b_token = data_of(payload)["access_token"]

status, payload = call(
    "POST",
    "/projects",
    body={
        "name": "重生：分集测试",
        "genre": "都市",
        "style": "国漫",
        "story_source": "SYNOPSIS",
        "story_text": STORY,
    },
    token=a_token,
)
check_status("create project -> 201", 201, status, payload)
project_id = data_of(payload)["id"]

# -------------------------------------------------- guard: no plan before analysis
print("== plan requires an analyzed story ==")

status, payload = call("POST", f"/projects/{project_id}/episodes/plan", token=a_token)
check("plan before analyze -> 409", 409, status)
check("error code is CONFLICT", "CONFLICT", error_code(payload))

status, payload = call("GET", f"/projects/{project_id}/episodes", token=a_token)
check("episode list -> 200", 200, status)
check("no episodes yet", [], data_of(payload)["items"])

# ------------------------------------------------------------------- analysis
print("== analyze (Story Agent) ==")

status, payload = call("POST", f"/projects/{project_id}/analyze", token=a_token)
check_status("analyze -> 200", 200, status, payload)

bible = data_of(payload)
characters = {item["name"]: item["id"] for item in bible["characters"]}
locations = {item["name"]: item["id"] for item in bible["locations"]}
check_true("analysis produced characters", len(characters) >= 1, characters)
check_true("analysis produced locations", len(locations) >= 1, locations)

# -------------------------------------------------------------------- planning
print("== episode planning ==")

status, payload = call(
    "POST", f"/projects/{project_id}/episodes/plan?episode_count=3", token=a_token
)
check_status("plan -> 200", 200, status, payload)

planned = data_of(payload)["items"]
check_true("planner produced episodes", len(planned) >= 1, len(planned))
check(
    "episode numbers are 1..N",
    list(range(1, len(planned) + 1)),
    [e["episode_number"] for e in planned],
)
check_true("every episode has a title", all(e["title"] for e in planned), planned)
check_true("every episode has a summary", all(e["summary"] for e in planned))
check_true("every episode has a duration", all(e["duration"] > 0 for e in planned))
check("no script yet", ["NOT_GENERATED"] * len(planned), script_states(planned))
check("no storyboard yet", ["NOT_GENERATED"] * len(planned), board_states(planned))
check("plan_meta records the model", True, bool(data_of(payload)["plan_meta"].get("model")))

status, payload = call("POST", f"/projects/{project_id}/episodes/plan", token=a_token)
check("re-plan without replace -> 409", 409, status)
check("error code is CONFLICT", "CONFLICT", error_code(payload))

first = planned[0]
episode_id = first["id"]

# ---------------------------------------------------------------------- script
print("== script generation ==")

status, payload = call("POST", f"/episodes/{episode_id}/storyboard/generate", token=a_token)
check("storyboard before script -> 409", 409, status)
check("error code is CONFLICT", "CONFLICT", error_code(payload))

status, payload = call("POST", f"/episodes/{episode_id}/script/generate", token=a_token)
check_status("generate script -> 200", 200, status, payload)

script = data_of(payload)["script"]
scenes = script["scenes"]
check_true("script has scenes", len(scenes) >= 1, len(scenes))
check(
    "scene ids are S1..Sn",
    [f"S{i}" for i in range(1, len(scenes) + 1)],
    [s["scene_id"] for s in scenes],
)

# PRD section 10: ids must resolve to real rows.
known_character_ids = set(characters.values())
known_location_ids = set(locations.values())
scene_location_ids = {s["location_id"] for s in scenes}
dialogue_character_ids = {d["character_id"] for s in scenes for d in s.get("dialogues") or []}
scene_character_ids = {cid for s in scenes for cid in s.get("characters") or []}

check_subset("all location_id resolve to Scene Bible rows", scene_location_ids, known_location_ids)
check_subset(
    "dialogue character_id resolve to Character Bible rows",
    dialogue_character_ids,
    known_character_ids,
)
check_subset(
    "scene character_id resolve to Character Bible rows",
    scene_character_ids,
    known_character_ids,
)
check_true("script has at least one line of dialogue", bool(dialogue_character_ids))
check_true("script meta records a provider", bool(data_of(payload)["meta"].get("provider")))
check("script_status is SUCCEEDED", "SUCCEEDED", data_of(payload)["script_status"])

characters_lookup = data_of(payload)["characters"]
check_subset("response carries id->name lookup", dialogue_character_ids, set(characters_lookup))

status, payload = call("GET", f"/episodes/{episode_id}/script", token=a_token)
check_status("GET script -> 200", 200, status, payload)
check("GET returns the same scene count", len(scenes), len(data_of(payload)["script"]["scenes"]))

status, payload = call("GET", f"/episodes/{episode_id}", token=a_token)
check("episode reports has_script", True, data_of(payload)["has_script"])

status, payload = call(
    "PATCH",
    f"/episodes/{episode_id}/script",
    body={"summary": "手工修改的本集梗概"},
    token=a_token,
)
check_status("PATCH script -> 200", 200, status, payload)
check("summary was updated", "手工修改的本集梗概", data_of(payload)["script"]["summary"])

# ------------------------------------------------------------------ storyboard
print("== storyboard generation ==")

status, payload = call("POST", f"/episodes/{episode_id}/storyboard/generate", token=a_token)
check_status("generate storyboard -> 200", 200, status, payload)

storyboard = data_of(payload)["storyboard"]
shots = data_of(payload)["shots"]
boards = storyboard["scenes"]

check_true("storyboard has scenes", len(boards) >= 1, len(boards))
check(
    "storyboard covers exactly the script's scenes",
    [s["scene_id"] for s in scenes],
    [b["scene_id"] for b in boards],
)
check_true("shots were persisted", len(shots) >= 1, len(shots))
check(
    "every scene has at least one shot",
    [True] * len(boards),
    [len(b["shots"]) >= 1 for b in boards],
)
check_true(
    "sequence is 1..N in absolute order",
    [s["sequence"] for s in shots] == list(range(1, len(shots) + 1)),
    [s["sequence"] for s in shots],
)

for board in boards:
    ids = [shot["shot_number"] for shot in board["shots"]]
    if ids != list(range(1, len(ids) + 1)):
        check_true(f"{board['scene_id']} shot_number restarts at 1", False, ids)
        break
else:
    check_true("shot_number restarts at 1 within every scene", True)

valid_sizes = {
    "extreme_wide",
    "wide",
    "medium",
    "medium_close_up",
    "close_up",
    "extreme_close_up",
}
valid_moves = {
    "static",
    "slow_push",
    "push_in",
    "pull_out",
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
    "tracking",
    "crane",
    "handheld",
}
check_subset(
    "all shot_size values are in the closed vocabulary",
    field_values(shots, "shot_size"),
    valid_sizes,
)
check_subset(
    "all camera_movement values are in the closed vocabulary",
    field_values(shots, "camera_movement"),
    valid_moves,
)
check_true("all shot durations are positive", all(s["duration"] > 0 for s in shots))
check_true("every shot has a visual_description", all(s["visual_description"] for s in shots))

# PRD section 11: shots name characters, and those names must be on the roster.
shot_character_names = {name for s in shots for name in s["characters"]}
check_subset(
    "shot characters all exist in the Character Bible",
    shot_character_names,
    set(characters),
)

# PRD section 19: the global style must reach every image prompt.
style = "国漫"
missing_style = [s["shot_number"] for s in shots if style not in (s["image_prompt"] or "")]
check("image_prompt mentions the project style", [], missing_style)

check("storyboard_status is SUCCEEDED", "SUCCEEDED", data_of(payload)["storyboard_status"])
check_true("storyboard meta records a provider", bool(data_of(payload)["meta"].get("provider")))

status, payload = call("GET", f"/episodes/{episode_id}/shots", token=a_token)
check_status("GET shots -> 200", 200, status, payload)
check("shot list length matches", len(shots), len(data_of(payload)))

status, payload = call(
    "PATCH",
    f"/shots/{shots[0]['id']}",
    body={"duration": 7, "camera_movement": "crane"},
    token=a_token,
)
check_status("PATCH shot -> 200", 200, status, payload)
check("shot duration updated", 7, data_of(payload)["duration"])
check("shot camera_movement updated", "crane", data_of(payload)["camera_movement"])

# --------------------------------------------------------------- consistency
print("== consistency check ==")

status, payload = call("GET", f"/episodes/{episode_id}/consistency", token=a_token)
check_status("consistency -> 200", 200, status, payload)
report = data_of(payload)
check_true("checked at least one shot", report["checked_shots"] >= 1, report["checked_shots"])
check("no ERROR-severity issues on a generated storyboard", 0, report["errors"])
check_true("report carries a boolean verdict", isinstance(report["ok"], bool))
issue_codes = {issue["code"] for issue in report["issues"]}
check_true("no UNKNOWN_CHARACTER issues", "UNKNOWN_CHARACTER" not in issue_codes, issue_codes)
check_true("no SCENE_NOT_IN_SCRIPT issues", "SCENE_NOT_IN_SCRIPT" not in issue_codes, issue_codes)

# ------------------------------------------------------------ regeneration
print("== regeneration invalidates the storyboard ==")

status, payload = call("POST", f"/episodes/{episode_id}/script/generate", token=a_token)
check_status("re-generate script -> 200", 200, status, payload)
check("script re-generated", "SUCCEEDED", data_of(payload)["script_status"])

status, payload = call("GET", f"/episodes/{episode_id}/storyboard", token=a_token)
check("storyboard reset to NOT_GENERATED", "NOT_GENERATED", data_of(payload)["storyboard_status"])
check("stale shots were removed", 0, len(data_of(payload)["shots"]))

status, payload = call("GET", f"/episodes/{episode_id}", token=a_token)
check("episode reports has_storyboard=False", False, data_of(payload)["has_storyboard"])

# -------------------------------------------------------- episode CRUD + ordering
print("== episode CRUD ==")

status, payload = call(
    "POST",
    f"/projects/{project_id}/episodes",
    body={"title": "手工新增的一集", "summary": "手工填写", "duration": 120},
    token=a_token,
)
# 200, not 201: this repo reserves 201 for top-level aggregates (register,
# create project) and returns 200 for POSTs into a nested collection --
# characters/locations behave the same way.
check_status("manual episode create -> 200", 200, status, payload)
manual = data_of(payload)
check("manual episode gets the next number", len(planned) + 1, manual["episode_number"])
check("manual episode starts NOT_GENERATED", "NOT_GENERATED", manual["script_status"])

status, payload = call(
    "POST",
    f"/projects/{project_id}/episodes",
    body={"title": "重复编号", "episode_number": manual["episode_number"]},
    token=a_token,
)
check("duplicate episode_number -> 409", 409, status)
check("error code is CONFLICT", "CONFLICT", error_code(payload))

status, payload = call(
    "PATCH", f"/episodes/{manual['id']}", body={"title": "改过标题的一集"}, token=a_token
)
check_status("PATCH episode -> 200", 200, status, payload)
check("title updated", "改过标题的一集", data_of(payload)["title"])

status, payload = call("GET", f"/projects/{project_id}/episodes", token=a_token)
check_status("list episodes -> 200", 200, status, payload)
listed = data_of(payload)["items"]
numbers = [e["episode_number"] for e in listed]
check("episodes are ordered by number", sorted(numbers), numbers)
check("list reports shot_count", True, all("shot_count" in e for e in listed))

status, payload = call("DELETE", f"/episodes/{manual['id']}", token=a_token)
check_status("DELETE episode -> 200", 200, status, payload)

status, payload = call("GET", f"/episodes/{manual['id']}", token=a_token)
check("deleted episode -> 404", 404, status)

# ------------------------------------------------------------- unknown ids
print("== unknown ids are rejected ==")

status, payload = call("GET", f"/episodes/{uuid.uuid4()}", token=a_token)
check("unknown episode -> 404", 404, status)

status, payload = call("PATCH", f"/shots/{uuid.uuid4()}", body={"duration": 5}, token=a_token)
check("unknown shot -> 404", 404, status)

# --------------------------------------------------------------- isolation
print("== cross-user isolation ==")

status, payload = call("GET", f"/episodes/{episode_id}", token=b_token)
check("user B cannot read A's episode", 404, status)

status, payload = call("GET", f"/projects/{project_id}/episodes", token=b_token)
check("user B cannot list A's episodes", 404, status)

status, payload = call("POST", f"/episodes/{episode_id}/script/generate", token=b_token)
check("user B cannot generate A's script", 404, status)

status, payload = call("PATCH", f"/shots/{shots[0]['id']}", body={"duration": 5}, token=b_token)
check("user B cannot edit A's shot", 404, status)

status, payload = call("DELETE", f"/episodes/{episode_id}", token=b_token)
check("user B cannot delete A's episode", 404, status)

# ---------------------------------------------------------------------- done
print()
print(f"== phase 4: passed={PASS} failed={FAIL} ==")
sys.exit(1 if FAIL else 0)

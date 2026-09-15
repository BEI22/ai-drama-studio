"""Phase 3 acceptance checks: Story Agent, Bibles, CRUD and isolation.

Exercises the real HTTP surface end to end against a running backend.

Why Python rather than curl+bash: on Windows/git-bash, non-ASCII JSON passed
inline via ``curl -d`` gets re-encoded by the shell and the backend rejects the
body with "There was an error parsing the body" (HTTP 400). Encoding the payload
explicitly as UTF-8 removes that whole class of false failure -- see
docs/TDD.md section 16.

Usage::

    python scripts/verify_phase3.py [backend_base_url]
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

PASSWORD = "storytime2026"
STAMP = uuid.uuid4().hex[:8]
A_EMAIL = f"agent-a+{STAMP}@example.com"
B_EMAIL = f"agent-b+{STAMP}@example.com"

STORY = (
    "林澈在大学宿舍的床上睁开眼，发现自己竟然回到了十年前的开学日。"
    "前世他因为沉迷游戏错过保研，毕业后四处碰壁，最后在出租屋里郁郁而终。"
    "这一次，他决定改变自己的人生。室友赵明达推开宿舍门，喊他一起去食堂。"
    "林澈没有说话，只是握紧了拳头。班主任周老师走进教室，宣布了考研的报名时间。"
    "苏晚坐在他旁边的座位上，笑着说：林澈，你这次一定要加油。"
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
    if isinstance(payload, dict) and payload.get("data") is not None:
        print(f"        data:     {json.dumps(payload['data'], ensure_ascii=False)[:300]}")
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
        with urllib.request.urlopen(request, timeout=180) as response:
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
        "name": "重生：我在大学重新开始",
        "genre": "都市",
        "style": "国漫",
        "story_source": "SYNOPSIS",
        "story_text": STORY,
    },
    token=a_token,
)
check("create project -> 201", 201, status)
project_id = data_of(payload)["id"]
check("new project is NOT_ANALYZED", "NOT_ANALYZED", data_of(payload)["analysis_status"])
check("new project has no characters", 0, data_of(payload)["character_count"])
check("new project has no locations", 0, data_of(payload)["location_count"])

# ------------------------------------------------------------------ bible pre
print("== bible before analysis ==")

status, payload = call("GET", f"/projects/{project_id}/bible", token=a_token)
check("bible -> 200 before analysis", 200, status)
check("story_bible is null, not an error", None, data_of(payload)["story_bible"])
check("status still NOT_ANALYZED", "NOT_ANALYZED", data_of(payload)["analysis_status"])
check("characters empty", [], data_of(payload)["characters"])

status, payload = call("GET", f"/projects/{project_id}/analyze/status", token=a_token)
check("status endpoint -> 200", 200, status)
ACTIVE_PROVIDER = data_of(payload)["provider"]
check("provider is reported", True, bool(ACTIVE_PROVIDER))
check("mock flag is a boolean", True, isinstance(data_of(payload)["mock"], bool))
print(f"        (active provider: {ACTIVE_PROVIDER})")

# -------------------------------------------------------------------- analyze
print("== analyze (Story Agent) ==")

status, payload = call("POST", f"/projects/{project_id}/analyze", token=a_token)
check("analyze -> 200", 200, status)
bible = data_of(payload) or {}
check("analysis SUCCEEDED", "SUCCEEDED", bible.get("analysis_status"))
check("analysis_error is null", None, bible.get("analysis_error"))
check("analyzed_at set", True, bool(bible.get("analyzed_at")))

story_bible = bible.get("story_bible") or {}
check("story bible has a title", True, bool(story_bible.get("title")))
# A genre the user typed in explicitly must win over inference -- overriding a
# deliberate choice would be presumptuous.
check("explicit genre hint is honored", "都市", story_bible.get("genre"))
check("story bible style inferred", True, bool(story_bible.get("style")))
check("world_rules present", True, len(story_bible.get("world_rules") or []) >= 1)
check("timeline present", True, len(story_bible.get("timeline") or []) >= 1)
check("main_conflict present", True, bool(story_bible.get("main_conflict")))

for field in (
    "title",
    "genre",
    "logline",
    "background",
    "world_rules",
    "main_conflict",
    "timeline",
    "important_objects",
    "important_events",
    "style",
):
    check(f"story bible exposes {field} (PRD 6)", True, field in story_bible)

# provenance: real output must be labelled as real, mock as mock -- the point is
# that a caller can always tell which one produced the Bible.
meta = bible.get("meta") or {}
check("provenance records the provider", ACTIVE_PROVIDER, meta.get("provider"))
check("mock flag agrees with the provider", ACTIVE_PROVIDER == "mock", bool(meta.get("mock")))
check("provenance records the model", True, bool(meta.get("model")))
check("provenance records prompt versions", True, bool(meta.get("prompt_versions")))
check("prompt version is versioned", "story_parser_v2", meta["prompt_versions"]["story_parser"])
check("usage recorded for all 3 nodes", 3, len(meta.get("usage") or []))
check(
    "every usage row names its node",
    True,
    all(r.get("node") and r.get("provider") for r in meta.get("usage") or []),
)
check(
    "usage reports token counts",
    True,
    all("input_tokens" in r and "output_tokens" in r for r in (meta.get("usage") or [])),
)

# ----------------------------------------------------------------- characters
print("== characters (Character Bible) ==")

characters = bible.get("characters") or []
names = [c["name"] for c in characters]
check("at least 3 characters", True, len(characters) >= 3)
check("main character extracted", True, "林澈" in names)
check("protagonist ranks first", "林澈", names[0])
check("protagonist role is correct", "PROTAGONIST", characters[0]["role"])
check("no verb fragments leaked", False, any("没有" in n or "笑着" in n for n in names))
check("no placeholder names", False, any(n in {"未知", "无", "角色"} for n in names))

hero = characters[0]
for field in (
    "id",
    "project_id",
    "name",
    "role",
    "age",
    "gender",
    "description",
    "appearance",
    "hair",
    "clothing",
    "personality",
    "voice_id",
    "reference_image_url",
    "sort_order",
):
    check(f"character exposes {field} (PRD 7)", True, field in hero)

check("appearance is image-prompt ready", True, len(hero["appearance"]) > 5)
check("personality is a list", True, isinstance(hero["personality"], list))
check(
    "roles are from the closed vocabulary",
    True,
    all(
        c["role"] in {"PROTAGONIST", "ANTAGONIST", "SUPPORTING", "MENTOR", "LOVE_INTEREST", "OTHER"}
        for c in characters
    ),
)

# ------------------------------------------------------------------ locations
print("== locations (Scene Bible) ==")

locations = bible.get("locations") or []
location_names = [item["name"] for item in locations]
check("at least 3 locations", True, len(locations) >= 3)
check("university dorm found", True, any("宿舍" in n for n in location_names))
check("classroom found", True, any("教室" in n for n in location_names))
check("no single-char fragments", True, all(len(n) >= 2 for n in location_names))

scene = locations[0]
for field in (
    "id",
    "name",
    "description",
    "time",
    "lighting",
    "visual_style",
    "reference_image_url",
):
    check(f"location exposes {field} (PRD 8)", True, field in scene)

# ------------------------------------------------------------ project surface
print("== project surfaces the analysis ==")

status, payload = call("GET", f"/projects/{project_id}", token=a_token)
check("detail -> 200", 200, status)
check("detail analysis_status", "SUCCEEDED", data_of(payload)["analysis_status"])
check("detail character_count", len(characters), data_of(payload)["character_count"])
check("detail location_count", len(locations), data_of(payload)["location_count"])
check("detail analyzed_at set", True, bool(data_of(payload)["analyzed_at"]))

status, payload = call("GET", "/projects", token=a_token)
row = next(i for i in data_of(payload)["items"] if i["id"] == project_id)
check("list card shows analysis_status", "SUCCEEDED", row["analysis_status"])
check("list card shows character_count", len(characters), row["character_count"])

# -------------------------------------------------------------- re-analysis
print("== re-analysis semantics ==")

status, payload = call("POST", f"/projects/{project_id}/analyze", token=a_token)
check("second analyze without replace -> 409", 409, status)
check("conflict error code", "CONFLICT", error_code(payload))

status, payload = call("POST", f"/projects/{project_id}/analyze?replace=true", token=a_token)
check("second analyze with replace -> 200", 200, status)
second = data_of(payload)["characters"]
second_names = [c["name"] for c in second]
check("no duplicated characters", len(second_names), len(set(second_names)))

# A real model is not deterministic, so a re-run may legitimately yield a
# different cast. What must ALWAYS hold is that replace=true did not pile a
# second copy of the same names on top of the first.
check("replace never duplicates a name", len(second_names), len(set(second_names)))

if ACTIVE_PROVIDER == "mock":
    # The mock is deterministic, so the stronger guarantees are testable here.
    check("character count unchanged (deterministic provider)", len(names), len(second_names))
    check(
        "character ids are stable (deterministic provider)",
        [c["id"] for c in characters],
        [c["id"] for c in second],
    )
    check(
        "rows were upserted, not recreated",
        sorted(c["created_at"] for c in characters),
        sorted(c["created_at"] for c in second),
    )
else:
    # Even with a real model, a name that both runs produced must keep its id,
    # because re-analysis upserts by name rather than wiping the table.
    before = {c["name"]: c["id"] for c in characters}
    shared = [n for n in second_names if n in before]
    check(
        "surviving names keep their id (upsert, not recreate)",
        [before[n] for n in shared],
        [c["id"] for c in second if c["name"] in before],
    )
    print(f"        ({len(shared)}/{len(second_names)} names survived re-analysis)")

status, payload = call("GET", f"/projects/{project_id}/characters", token=a_token)
listed_now = data_of(payload)
check(
    "stored cast matches the response", True, {c["name"] for c in listed_now} == set(second_names)
)

# -------------------------------------------------------------------- crud
print("== character / location CRUD ==")

status, payload = call(
    "POST",
    f"/projects/{project_id}/characters",
    body={"name": "手动添加的角色", "role": "MENTOR", "appearance": "银发老者，拄着拐杖"},
    token=a_token,
)
check("create character -> 200", 200, status)
manual_id = data_of(payload)["id"]
check("manual role preserved", "MENTOR", data_of(payload)["role"])

status, _ = call(
    "POST",
    f"/projects/{project_id}/characters",
    body={"name": "手动添加的角色"},
    token=a_token,
)
check("duplicate character -> 409", 409, status)

status, payload = call(
    "PATCH",
    f"/characters/{manual_id}",
    body={"appearance": "用户重写的外貌描述"},
    token=a_token,
)
check("patch character -> 200", 200, status)
check("patch applied", "用户重写的外貌描述", data_of(payload)["appearance"])
check("patch is partial (name kept)", "手动添加的角色", data_of(payload)["name"])

status, _ = call("PATCH", f"/characters/{manual_id}", body={"nmae": "typo"}, token=a_token)
check("unknown field -> 422", 422, status)

status, _ = call("PATCH", f"/characters/{manual_id}", body={}, token=a_token)
check("empty patch -> 422", 422, status)

status, payload = call("GET", f"/projects/{project_id}/characters", token=a_token)
check(
    "character list includes the manual one", True, manual_id in [c["id"] for c in data_of(payload)]
)

status, payload = call("DELETE", f"/characters/{manual_id}", token=a_token)
check("delete character -> 200", 200, status)
check("delete reports success", True, data_of(payload)["deleted"])
status, _ = call("DELETE", f"/characters/{manual_id}", token=a_token)
check("delete twice -> 404", 404, status)

status, payload = call(
    "POST",
    f"/projects/{project_id}/locations",
    body={"name": "天台", "time": "深夜", "lighting": "城市霓虹"},
    token=a_token,
)
check("create location -> 200", 200, status)
location_id = data_of(payload)["id"]

status, payload = call(
    "PATCH", f"/locations/{location_id}", body={"lighting": "无光的深夜"}, token=a_token
)
check("patch location -> 200", 200, status)
check("patch applied (partial)", "无光的深夜", data_of(payload)["lighting"])
check("patch kept other fields", "深夜", data_of(payload)["time"])

status, payload = call("DELETE", f"/locations/{location_id}", token=a_token)
check("delete location -> 200", 200, status)

# --------------------------------------------------------------- validation
print("== validation ==")

status, payload = call(
    "POST",
    "/projects",
    body={"name": "无故事项目", "story_source": None, "story_text": None},
    token=a_token,
)
short_id = data_of(payload)["id"]
status, payload = call("POST", f"/projects/{short_id}/analyze", token=a_token)
check("analyze without story -> 422", 422, status)
check("validation error code", "VALIDATION_ERROR", error_code(payload))

status, payload = call(
    "POST", f"/projects/{short_id}/analyze", body={"story_text": "太短"}, token=a_token
)
check("analyze a too-short story -> 422", 422, status)

status, payload = call(
    "POST", f"/projects/{short_id}/analyze", body={"story_text": STORY}, token=a_token
)
check("analyze preview text -> 200", 200, status)
check("preview produced characters", True, len(data_of(payload)["characters"]) >= 3)
status, payload = call("GET", f"/projects/{short_id}", token=a_token)
check("preview did NOT save the story", None, data_of(payload)["story_text"])

status, payload = call(
    "POST",
    f"/projects/{project_id}/story",
    body={"story_source": "NOVEL", "story_text": "这是一段全新的故事，主角换了人，场景也全变了。"},
    token=a_token,
)
check(
    "saving a new story invalidates the analysis",
    "NOT_ANALYZED",
    data_of(payload)["analysis_status"],
)

status, payload = call("POST", f"/projects/{project_id}/analyze", token=a_token)
check_status("can re-analyze after a story change (no 409)", 200, status, payload)

# ---------------------------------------------------------------- isolation
print("== isolation (the important part) ==")

status, payload = call("GET", f"/projects/{project_id}/bible", token=b_token)
check("B cannot read A's bible -> 404", 404, status)
check("B's denial leaks no names", False, "林澈" in json.dumps(payload, ensure_ascii=False))

status, _ = call("GET", f"/projects/{project_id}/characters", token=b_token)
check("B cannot list A's characters -> 404", 404, status)

status, _ = call("GET", f"/projects/{project_id}/locations", token=b_token)
check("B cannot list A's locations -> 404", 404, status)

status, _ = call("POST", f"/projects/{project_id}/analyze", token=b_token)
check("B cannot analyze A's project -> 404", 404, status)

status, _ = call("GET", f"/projects/{project_id}/analyze/status", token=b_token)
check("B cannot read A's analyze status -> 404", 404, status)

# B owns nothing, so any real id from A must be invisible through the id route.
status, payload = call(
    "POST", f"/projects/{project_id}/characters", body={"name": "A 的临时角色"}, token=a_token
)
victim_id = data_of(payload)["id"]

status, payload = call(
    "PATCH", f"/characters/{victim_id}", body={"name": "被 B 改坏了"}, token=b_token
)
check("B cannot patch A's character -> 404", 404, status)
check("B's patch leaks nothing", False, "被 B 改坏了" in json.dumps(payload, ensure_ascii=False))

status, _ = call("DELETE", f"/characters/{victim_id}", token=b_token)
check("B cannot delete A's character -> 404", 404, status)

status, payload = call("GET", f"/projects/{project_id}/characters", token=a_token)
check("A's character survived", True, victim_id in [c["id"] for c in data_of(payload)])
check(
    "A's character was not renamed", False, "被 B 改坏了" in [c["name"] for c in data_of(payload)]
)

status, _ = call(
    "POST", f"/projects/{project_id}/characters", body={"name": "B 的越权角色"}, token=b_token
)
check("B cannot add to A's project -> 404", 404, status)

status, _ = call("GET", "/projects", token=b_token)
check("B's own project list is empty", 0, payload.get("meta", {}).get("total", 0))

status, _ = call("GET", f"/projects/{uuid.uuid4()}/bible", token=a_token)
check("unknown project bible -> 404", 404, status)

status, _ = call("GET", f"/projects/{project_id}/bible")
check("bible without a token -> 401", 401, status)

# ------------------------------------------------------------------ cascade
print("== cascade ==")

status, payload = call("DELETE", f"/projects/{project_id}", token=a_token)
check("delete project -> 200", 200, status)

status, _ = call("GET", f"/projects/{project_id}/characters", token=a_token)
check("characters unreachable after project delete -> 404", 404, status)

# A fresh project must not inherit the deleted project's cast.
status, payload = call("POST", "/projects", body={"name": "全新项目"}, token=a_token)
fresh_id = data_of(payload)["id"]
check("fresh project has 0 characters", 0, data_of(payload)["character_count"])
check("fresh project has 0 locations", 0, data_of(payload)["location_count"])
status, _ = call("DELETE", f"/projects/{fresh_id}", token=a_token)

print()
print(f"passed={PASS} failed={FAIL}")
sys.exit(0 if FAIL == 0 else 1)

#!/usr/bin/env python
"""Phase 2 acceptance checks: auth + Project CRUD + Story + tenant isolation.

Exercises the real HTTP surface end to end against a running backend.

Why Python instead of curl+bash: on Windows/git-bash, passing non-ASCII JSON
inline via ``curl -d`` gets re-encoded by the shell and the backend rejects the
body with "There was an error parsing the body" (HTTP 400). Writing the payload
as explicit UTF-8 bytes removes that whole class of false failure.

Usage::

    python scripts/verify_phase2.py [backend_base_url]
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
A_EMAIL = f"alice+{STAMP}@example.com"
B_EMAIL = f"bob+{STAMP}@example.com"

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
        with urllib.request.urlopen(request, timeout=30) as response:
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


# --------------------------------------------------------------------- auth
print("== auth ==")

status, payload = call("POST", "/auth/register", body={"email": A_EMAIL, "password": PASSWORD})
check("register A -> 201", 201, status)
check("register success flag", True, payload.get("success"))
a_token = data_of(payload).get("access_token") if data_of(payload) else None
check("register returns a token", True, bool(a_token))
check("register hides password_hash", False, "password_hash" in json.dumps(payload))
check("register echoes email", A_EMAIL, data_of(payload)["user"]["email"])

status, payload = call("POST", "/auth/register", body={"email": A_EMAIL, "password": PASSWORD})
check("duplicate register -> 409", 409, status)
check("duplicate error code", "CONFLICT", error_code(payload))
check("duplicate data is null", None, data_of(payload))

status, _ = call(
    "POST", "/auth/register", body={"email": f"weak+{STAMP}@example.com", "password": "short1"}
)
check("too-short password -> 422", 422, status)

status, _ = call(
    "POST",
    "/auth/register",
    body={"email": f"letters+{STAMP}@example.com", "password": "onlyletters"},
)
check("letters-only password -> 422", 422, status)

status, _ = call("POST", "/auth/register", body={"email": "not-an-email", "password": PASSWORD})
check("invalid email -> 422", 422, status)

status, payload = call("POST", "/auth/login", body={"email": A_EMAIL, "password": PASSWORD})
check("login -> 200", 200, status)
check("login returns a token", True, bool(data_of(payload).get("access_token")))

status, payload = call("POST", "/auth/login", body={"email": A_EMAIL.upper(), "password": PASSWORD})
check("login email is case-insensitive", 200, status)

status, payload = call("POST", "/auth/login", body={"email": A_EMAIL, "password": "wrongpass123"})
check("wrong password -> 401", 401, status)
wrong_password_error = payload.get("error")

status, payload = call(
    "POST", "/auth/login", body={"email": "nobody@example.com", "password": "whatever123"}
)
check("unknown email -> 401", 401, status)
check(
    "unknown email is indistinguishable from wrong password",
    True,
    payload.get("error") == wrong_password_error,
)

status, payload = call("GET", "/auth/me", token=a_token)
check("me -> 200", 200, status)
check("me returns the right email", A_EMAIL, data_of(payload)["email"])

status, _ = call("GET", "/auth/me")
check("me without token -> 401", 401, status)

status, _ = call("GET", "/auth/me", token="not-a-jwt")
check("me with malformed token -> 401", 401, status)

status, _ = call("GET", "/auth/me", token=str(uuid.uuid4()))
check("me with unknown subject -> 401", 401, status)

_, payload = call("POST", "/auth/register", body={"email": B_EMAIL, "password": PASSWORD})
b_token = data_of(payload)["access_token"]

# ------------------------------------------------------------------- projects
print("== project CRUD ==")

status, _ = call("GET", "/projects")
check("projects require auth -> 401", 401, status)

status, payload = call(
    "POST",
    "/projects",
    body={"name": "重生大学时代", "genre": "都市", "style": "国漫", "description": "测试项目"},
    token=a_token,
)
check("create project -> 201", 201, status)
project = data_of(payload) or {}
project_id = project.get("id")
check("create returns an id", True, bool(project_id))
check("create defaults to DRAFT", "DRAFT", project.get("status"))
check("create has no story yet", False, project.get("has_story"))
check("create episode_count=0", 0, project.get("episode_count"))
check("create story_bible is null", None, project.get("story_bible_json"))
check("create episodes is empty", [], project.get("episodes"))
check("chinese name survives the round trip", "重生大学时代", project.get("name"))

status, _ = call("POST", "/projects", body={"name": "   "}, token=a_token)
check("blank name -> 422", 422, status)

status, _ = call("POST", "/projects", body={"name": "x" * 300}, token=a_token)
check("over-long name -> 422", 422, status)

status, _ = call(
    "POST", "/projects", body={"name": "缺来源", "story_text": "有文本没有来源"}, token=a_token
)
check("story text without source -> 422", 422, status)

status, payload = call(
    "POST",
    "/projects",
    body={"name": "内联故事", "story_source": "SYNOPSIS", "story_text": "内联的故事文本"},
    token=a_token,
)
check("inline story on create -> 201", 201, status)
check("inline story sets has_story", True, data_of(payload).get("has_story"))
inline_id = data_of(payload).get("id")

status, payload = call("GET", f"/projects/{project_id}", token=a_token)
check("get detail -> 200", 200, status)
check("detail echoes id", project_id, data_of(payload).get("id"))
check("detail has empty episodes", [], data_of(payload).get("episodes"))
check("detail does not expose other fields", True, "user_id" not in data_of(payload))

status, payload = call("GET", "/projects", token=a_token)
check("list -> 200", 200, status)
check("list total=2", 2, payload.get("meta", {}).get("total"))
check("list page meta", 1, payload.get("meta", {}).get("page"))
check(
    "list contains our project", True, any(i["id"] == project_id for i in data_of(payload)["items"])
)

status, payload = call("GET", "/projects?search=%E9%87%8D%E7%94%9F", token=a_token)
check("search by chinese substring", 1, payload.get("meta", {}).get("total"))

status, payload = call("GET", "/projects?search=zzznotfound", token=a_token)
check("search miss", 0, payload.get("meta", {}).get("total"))

status, payload = call("GET", "/projects?page_size=1", token=a_token)
check("page_size honoured", 1, len(data_of(payload)["items"]))
check("pages computed", 2, payload.get("meta", {}).get("pages"))

status, _ = call("GET", "/projects?page_size=500", token=a_token)
check("page_size over max -> 422", 422, status)

status, payload = call(
    "PATCH", f"/projects/{project_id}", body={"name": "改名后的项目"}, token=a_token
)
check("patch name -> 200", 200, status)
check("patch applied", "改名后的项目", data_of(payload).get("name"))
check("patch is partial (genre kept)", "都市", data_of(payload).get("genre"))

status, payload = call("PATCH", f"/projects/{project_id}", body={"status": "ACTIVE"}, token=a_token)
check("patch status", "ACTIVE", data_of(payload).get("status"))

status, _ = call("PATCH", f"/projects/{project_id}", body={}, token=a_token)
check("patch empty body -> 422", 422, status)

status, _ = call("PATCH", f"/projects/{project_id}", body={"status": "NOPE"}, token=a_token)
check("patch invalid status -> 422", 422, status)

# ------------------------------------------------------------------ story
print("== story ==")

STORY = "一个年轻人意外重生回大学时代，决定改变自己的人生。"
status, payload = call(
    "POST",
    f"/projects/{project_id}/story",
    body={"story_source": "SYNOPSIS", "story_text": STORY},
    token=a_token,
)
check("save story -> 200", 200, status)
check("story flips has_story", True, data_of(payload).get("has_story"))
check("story source saved", "SYNOPSIS", data_of(payload).get("story_source"))
check("story text saved verbatim", STORY, data_of(payload).get("story_text"))

status, payload = call("GET", f"/projects/{project_id}/story", token=a_token)
check("read story -> 200", 200, status)
check("story text round-trips", STORY, data_of(payload).get("story_text"))

status, payload = call(
    "POST",
    f"/projects/{project_id}/story",
    body={"story_source": "SCRIPT", "story_text": "替换后的剧本"},
    token=a_token,
)
check("story replace works", "替换后的剧本", data_of(payload).get("story_text"))
check("story source replaced", "SCRIPT", data_of(payload).get("story_source"))

status, _ = call(
    "POST",
    f"/projects/{project_id}/story",
    body={"story_source": "SYNOPSIS", "story_text": "   "},
    token=a_token,
)
check("blank story -> 422", 422, status)

# -------------------------------------------------------------- isolation
print("== isolation (the important part) ==")

status, payload = call("GET", f"/projects/{project_id}", token=b_token)
check("B cannot read A's project -> 404", 404, status)
check("B's denial uses NOT_FOUND (not FORBIDDEN)", "NOT_FOUND", error_code(payload))
check("B's denial leaks no project data", False, "改名后的项目" in json.dumps(payload))

status, _ = call("PATCH", f"/projects/{project_id}", body={"name": "hacked"}, token=b_token)
check("B cannot patch A's project -> 404", 404, status)

status, _ = call("DELETE", f"/projects/{project_id}", token=b_token)
check("B cannot delete A's project -> 404", 404, status)

status, _ = call(
    "POST",
    f"/projects/{project_id}/story",
    body={"story_source": "NOVEL", "story_text": "入侵者的故事"},
    token=b_token,
)
check("B cannot write A's story -> 404", 404, status)

status, payload = call("GET", f"/projects/{project_id}/story", token=b_token)
check("B cannot read A's story -> 404", 404, status)
check("B's story denial leaks nothing", False, "替换后的剧本" in json.dumps(payload))

status, payload = call("GET", f"/projects/{project_id}", token=a_token)
check("A's project is untouched", "改名后的项目", data_of(payload).get("name"))
check("A's story is untouched", "替换后的剧本", data_of(payload).get("story_text"))

status, payload = call("GET", "/projects", token=b_token)
check("B sees only their own (empty) list", 0, payload.get("meta", {}).get("total"))

status, _ = call("GET", f"/projects/{uuid.uuid4()}", token=a_token)
check("unknown project -> 404", 404, status)

status, _ = call("GET", "/projects/not-a-uuid", token=a_token)
check("malformed uuid -> 422", 422, status)

# --------------------------------------------------------------- cleanup
print("== cleanup ==")

status, payload = call("DELETE", f"/projects/{project_id}/story", token=a_token)
check("clear story -> 200", 200, status)
check("story cleared", False, data_of(payload).get("has_story"))

status, payload = call("DELETE", f"/projects/{project_id}", token=a_token)
check("delete project -> 200", 200, status)
check("delete reports success", True, data_of(payload).get("deleted"))

status, _ = call("DELETE", f"/projects/{project_id}", token=a_token)
check("delete again -> 404", 404, status)

status, _ = call("GET", f"/projects/{project_id}", token=a_token)
check("deleted project is gone -> 404", 404, status)

status, _ = call("DELETE", f"/projects/{inline_id}", token=a_token)
check("inline-story project also deletable", 200, status)

print()
print(f"passed={PASS} failed={FAIL}")
sys.exit(0 if FAIL == 0 else 1)

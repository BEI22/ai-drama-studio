"""Seed a demo account + a fully analysed project so the UI can be browsed.

Run against the live compose stack (real model).

Idempotent: reuses the demo account and project, and **skips** analysis when the
project has already been analysed (re-analysing is a 409 by design -- the
conflict guard). Pass ``--force`` to re-analyse anyway via ``?replace=true``.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"

EMAIL = "demo@aistudio.dev"
PASSWORD = "aistudio2026"
PROJECT_NAME = "重生之我在大学当学霸"

STORY = (
    "大一新生林澈在开学典礼上打了个盹，醒来时发现自己回到了十年前的那个下午。\n\n"
    "前世他沉迷网游、挂科退学，三十岁一事无成，在出租屋里郁郁而终。"
    "这一世他带着完整的十年记忆重来，知道哪只股票会涨、哪门课的老师会给挂、"
    "也记得那个在图书馆四楼总是坐在窗边的女生最后嫁给了别人。\n\n"
    "室友赵明达推门进来，把刚买的煎饼果子往桌上一拍：「走啊，开黑去！」\n"
    "林澈看着这张十年后因车祸去世的脸，喉咙发紧。\n\n"
    "班主任周建国在班会上宣布了转专业申请的时间，前世林澈就是错过了这次机会。"
    "苏晚坐在他旁边，笑着递过来一块橡皮：「林澈，你这次一定要加油啊。」\n\n"
    "林澈在笔记本第一页写下三个字：改写它。"
)


def call(
    method: str, path: str, token: str | None = None, body: dict | None = None, timeout: int = 300
) -> tuple[int, dict]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace"))


# --- account (register, or log in if it already exists) ---------------------
status, body = call(
    "POST",
    "/auth/register",
    body={"email": EMAIL, "password": PASSWORD, "display_name": "演示账号"},
)
if status == 201:
    print(f"created demo account {EMAIL}")
else:
    status, body = call("POST", "/auth/login", body={"email": EMAIL, "password": PASSWORD})
    print(f"reused demo account {EMAIL} (register said {status})")

token = body["data"]["access_token"]
print("  login ok, token acquired")

# --- project ---------------------------------------------------------------
status, body = call("GET", "/projects", token=token)
projects = (body.get("data") or {}).get("items", []) if status == 200 else []
existing = next((p for p in projects if p["name"] == PROJECT_NAME), None)

if existing:
    project_id = existing["id"]
    already_analysed = existing.get("analysis_status") == "SUCCEEDED"
    print(f"reusing project {project_id}  analysis_status={existing.get('analysis_status')}")
else:
    status, body = call(
        "POST",
        "/projects",
        token=token,
        body={
            "name": PROJECT_NAME,
            "description": "重生流校园题材，用于演示 Story Agent 与人物/场景管理。",
            "genre": "都市",
            "style": "国漫",
            "story_source": "SYNOPSIS",
            "story_text": STORY,
        },
    )
    if status != 201:
        raise SystemExit(f"create project failed: {status} {body}")
    project_id = body["data"]["id"]
    already_analysed = False
    print(f"created project {project_id}")

# --- analyse (real model, ~20-90s) ----------------------------------------
# Re-analysing a project that already succeeded returns 409 by design, so skip it
# rather than provoking a conflict; --force maps to the replace query param.
if already_analysed and "--force" not in sys.argv:
    print("already analysed -> skipping (pass --force to re-analyse with replace=true)")
else:
    query = "?replace=true" if already_analysed else ""
    status, body = call("POST", f"/projects/{project_id}/analyze{query}", token=token)
    print(f"analyse -> {status}")

    if status == 200:
        data = body["data"]
        meta = data.get("meta") or {}
        bible = data.get("story_bible") or {}
        print(f"  provider      : {meta.get('provider')} / {meta.get('model')}")
        print(f"  mock          : {meta.get('mock')}")
        print(f"  pinned        : {meta.get('pinned_from_user')}")
        print(f"  title         : {bible.get('title')}")
        print(f"  genre / style : {bible.get('genre')} / {bible.get('style')}")
        print(f"  characters    : {len(data.get('characters') or [])}")
        for c in (data.get("characters") or [])[:6]:
            print(f"      - {c.get('name')}  ({c.get('role')})")
        print(f"  locations     : {len(data.get('locations') or [])}")
        for loc in (data.get("locations") or [])[:6]:
            print(f"      - {loc.get('name')}")
    else:
        print(json.dumps(body.get("error"), ensure_ascii=False))

print("\n" + "=" * 58)
print("  登录地址 : http://localhost:3000/login")
print(f"  邮箱     : {EMAIL}")
print(f"  密码     : {PASSWORD}")
print("=" * 58)

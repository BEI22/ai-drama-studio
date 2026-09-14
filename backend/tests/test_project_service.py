"""Service-layer unit tests -- no HTTP involved (PRD section 36 item 12).

These exercise the business rules directly against a real database session, so
they stay meaningful even if route signatures change.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session as OrmSession

from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError, ValidationError
from app.core.security import hash_password
from app.models.enums import ProjectStatus
from app.repositories.project import ProjectRepository
from app.repositories.user import UserRepository
from app.schemas.auth import UserRegister
from app.schemas.project import ProjectCreate, ProjectUpdate, StorySource, StoryUpsert
from app.services.auth_service import AuthService
from app.services.project_service import ProjectService


@pytest.fixture
def auth(db: OrmSession) -> AuthService:
    return AuthService(db)


@pytest.fixture
def service(db: OrmSession) -> ProjectService:
    return ProjectService(db)


def make_user(auth: AuthService, email: str = "svc@example.com"):
    return auth.register(UserRegister(email=email, password="storytime2026"))


# ------------------------------------------------------------------ UserRepository
def test_user_repository_email_lookup_is_case_insensitive(db: OrmSession) -> None:
    repo = UserRepository(db)
    repo.create(email="Repo@Example.com", password_hash=hash_password("pw12345678"))
    db.commit()

    assert repo.get_by_email("repo@example.com") is not None
    assert repo.get_by_email("REPO@EXAMPLE.COM") is not None
    assert repo.email_taken("repo@example.com") is True
    assert repo.email_taken("other@example.com") is False


def test_user_repository_stores_lowercase_email(db: OrmSession) -> None:
    repo = UserRepository(db)
    user = repo.create(email="  Spaced@Example.COM  ", password_hash=hash_password("pw12345678"))
    db.commit()
    assert user.email == "spaced@example.com"


# ------------------------------------------------------------------ AuthService
def test_register_rejects_duplicate(auth: AuthService) -> None:
    make_user(auth)
    with pytest.raises(ConflictError):
        make_user(auth)


def test_authenticate_rejects_bad_password(auth: AuthService) -> None:
    make_user(auth)
    with pytest.raises(UnauthorizedError):
        auth.authenticate("svc@example.com", "definitely-wrong1")


def test_authenticate_accepts_good_password(auth: AuthService) -> None:
    created = make_user(auth)
    assert auth.authenticate("svc@example.com", "storytime2026").id == created.id


def test_issue_token_round_trips_through_load_user(auth: AuthService) -> None:
    user = make_user(auth)
    token = auth.issue_token(user)
    restored = auth.load_user(str(user.id))
    assert restored.id == user.id
    assert token


def test_load_user_rejects_unknown_and_malformed_ids(auth: AuthService) -> None:
    with pytest.raises(UnauthorizedError):
        auth.load_user(str(uuid.uuid4()))
    with pytest.raises(UnauthorizedError):
        auth.load_user("not-a-uuid")


def test_expires_in_is_positive(auth: AuthService) -> None:
    assert auth.expires_in_seconds() > 0


# --------------------------------------------------------------- ProjectService
def test_create_project_persists_and_returns_detail(
    auth: AuthService, service: ProjectService
) -> None:
    user = make_user(auth)
    detail = service.create(user, ProjectCreate(name="  我的项目  ", genre="都市"))

    assert detail.name == "我的项目"
    assert detail.status == ProjectStatus.DRAFT.value
    assert detail.episode_count == 0
    assert detail.has_story is False
    assert detail.story_bible_json is None


def test_get_rejects_other_users_project(auth: AuthService, service: ProjectService) -> None:
    alice = make_user(auth, "owner@example.com")
    bob = make_user(auth, "intruder@example.com")
    created = service.create(alice, ProjectCreate(name="Alice 的项目"))

    with pytest.raises(NotFoundError):
        service.get(bob, created.id)


def test_get_rejects_unknown_project(auth: AuthService, service: ProjectService) -> None:
    user = make_user(auth)
    with pytest.raises(NotFoundError):
        service.get(user, uuid.uuid4())


def test_update_without_fields_raises_validation_error(
    auth: AuthService, service: ProjectService
) -> None:
    user = make_user(auth)
    created = service.create(user, ProjectCreate(name="空更新"))
    with pytest.raises(ValidationError):
        service.update(user, created.id, ProjectUpdate())


def test_update_only_touches_supplied_fields(auth: AuthService, service: ProjectService) -> None:
    user = make_user(auth)
    created = service.create(user, ProjectCreate(name="原名", genre="都市", style="国漫"))

    updated = service.update(user, created.id, ProjectUpdate(name="新名"))

    assert updated.name == "新名"
    assert updated.genre == "都市"
    assert updated.style == "国漫"


def test_update_accepts_status_enum(auth: AuthService, service: ProjectService) -> None:
    user = make_user(auth)
    created = service.create(user, ProjectCreate(name="状态流转"))

    updated = service.update(user, created.id, ProjectUpdate(status=ProjectStatus.ACTIVE))
    assert updated.status == ProjectStatus.ACTIVE.value


def test_delete_removes_project(auth: AuthService, service: ProjectService) -> None:
    user = make_user(auth)
    created = service.create(user, ProjectCreate(name="待删除"))

    service.delete(user, created.id)

    with pytest.raises(NotFoundError):
        service.get(user, created.id)


def test_delete_rejects_other_user(auth: AuthService, service: ProjectService) -> None:
    alice = make_user(auth, "del-owner@example.com")
    bob = make_user(auth, "del-intruder@example.com")
    created = service.create(alice, ProjectCreate(name="不能被删"))

    with pytest.raises(NotFoundError):
        service.delete(bob, created.id)

    assert service.get(alice, created.id).name == "不能被删"


def test_upsert_story_sets_flags(auth: AuthService, service: ProjectService) -> None:
    user = make_user(auth)
    created = service.create(user, ProjectCreate(name="故事项目"))

    updated = service.upsert_story(
        user,
        created.id,
        StoryUpsert(story_source=StorySource.NOVEL, story_text="第一章，少年重生。"),
    )

    assert updated.has_story is True
    assert updated.story_source == StorySource.NOVEL
    assert updated.story_text == "第一章，少年重生。"


def test_clear_story_resets_fields(auth: AuthService, service: ProjectService) -> None:
    user = make_user(auth)
    created = service.create(
        user,
        ProjectCreate(name="清空故事", story_source=StorySource.SYNOPSIS, story_text="故事"),
    )

    cleared = service.clear_story(user, created.id)

    assert cleared.has_story is False
    assert cleared.story_text is None
    assert cleared.story_source is None


def test_list_paginates_and_counts(auth: AuthService, service: ProjectService) -> None:
    user = make_user(auth)
    for index in range(7):
        service.create(user, ProjectCreate(name=f"项目 {index}"))

    first = service.list(user, page=1, page_size=3)
    assert first.total == 7
    assert len(first.items) == 3

    last = service.list(user, page=3, page_size=3)
    assert len(last.items) == 1


def test_list_clamps_page_size(auth: AuthService, service: ProjectService) -> None:
    user = make_user(auth)
    service.create(user, ProjectCreate(name="一"))
    assert service.list(user, page_size=10_000).page_size == 100


def test_list_never_leaks_other_users_rows(auth: AuthService, service: ProjectService) -> None:
    alice = make_user(auth, "list-a@example.com")
    bob = make_user(auth, "list-b@example.com")
    service.create(alice, ProjectCreate(name="A 的"))
    service.create(bob, ProjectCreate(name="B 的"))

    assert [item.name for item in service.list(alice).items] == ["A 的"]
    assert [item.name for item in service.list(bob).items] == ["B 的"]


# ---------------------------------------------------------- ProjectRepository
def test_episode_counts_batches_and_handles_empty(db: OrmSession) -> None:
    repo = ProjectRepository(db)
    assert repo.episode_counts([]) == {}


def test_episode_count_is_zero_without_episodes(auth: AuthService, db: OrmSession) -> None:
    user = make_user(auth)
    repo = ProjectRepository(db)
    project = repo.create(user_id=user.id, name="无剧集")
    db.commit()

    assert repo.episode_count(project.id) == 0
    assert repo.episode_counts([project.id]) == {}

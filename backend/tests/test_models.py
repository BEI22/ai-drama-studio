"""Persistence behaviour for the Phase 1 tables (PRD section 17)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Episode, EpisodeStatus, Project, ProjectStatus, User


def _user(email: str = "author@example.com") -> User:
    return User(email=email, password_hash=hash_password("s3cret-passphrase"))


def test_create_user_project_episode(db: Session) -> None:
    user = _user()
    project = Project(user=user, name="重生大学时代", genre="都市", style="国漫")
    episode = Episode(episode_number=1, title="第 1 集")
    project.episodes.append(episode)

    db.add(project)
    db.commit()
    db.refresh(project)
    db.refresh(episode)

    assert isinstance(project.id, uuid.UUID)
    assert project.status == ProjectStatus.DRAFT.value
    assert episode.status == EpisodeStatus.DRAFT.value
    assert episode.duration == 180
    assert episode.created_at is not None
    assert project.created_at is not None

    assert project.user.email == "author@example.com"
    assert episode.project_id == project.id
    assert [item.id for item in project.episodes] == [episode.id]


def test_episode_numbers_are_unique_per_project(db: Session) -> None:
    user = _user("dup@example.com")
    project = Project(user=user, name="重复集号", episodes=[Episode(episode_number=1)])
    db.add(project)
    db.commit()

    db.add(Episode(project_id=project.id, episode_number=1))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_deleting_a_project_cascades_to_episodes(db: Session) -> None:
    user = _user("cascade@example.com")
    project = Project(
        user=user,
        name="级联删除",
        episodes=[Episode(episode_number=1), Episode(episode_number=2)],
    )
    db.add(project)
    db.commit()

    db.delete(project)
    db.commit()

    assert db.query(Project).count() == 0
    assert db.query(Episode).count() == 0
    assert db.query(User).count() == 1  # the author survives


def test_story_bible_json_round_trips(db: Session) -> None:
    bible = {
        "title": "重生",
        "genre": "都市",
        "world_rules": ["时间线不可逆"],
        "characters": [{"name": "林澈", "role": "protagonist"}],
    }
    project = Project(user=_user("bible@example.com"), name="Story Bible", story_bible_json=bible)
    db.add(project)
    db.commit()
    db.expire_all()

    stored = db.get(Project, project.id)
    assert stored is not None
    assert stored.story_bible_json == bible
    assert stored.to_dict()["name"] == "Story Bible"


def test_episode_script_and_storyboard_json_persist(db: Session) -> None:
    project = Project(user=_user("script@example.com"), name="剧本持久化")
    episode = Episode(
        episode_number=1,
        script_json={"scenes": [{"scene_id": "sc_1", "dialogues": []}]},
        storyboard_json={"scene_id": "sc_1", "shots": [{"shot_id": "sh_1", "duration": 5}]},
    )
    project.episodes.append(episode)
    db.add(project)
    db.commit()
    db.expire_all()

    stored = db.get(Episode, episode.id)
    assert stored is not None
    assert stored.script_json["scenes"][0]["scene_id"] == "sc_1"
    assert stored.storyboard_json["shots"][0]["duration"] == 5


def test_email_is_unique(db: Session) -> None:
    db.add(_user("same@example.com"))
    db.commit()

    db.add(_user("same@example.com"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

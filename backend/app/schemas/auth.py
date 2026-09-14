"""Authentication schemas (PRD section 27)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        """Reject the most obviously weak passwords.

        Deliberately light: composition rules push users toward predictable
        patterns, so we only require length + not-all-one-character-class.
        """
        if value.strip() != value:
            raise ValueError("密码首尾不能有空白字符")
        if value.isdigit() or value.isalpha():
            raise ValueError("密码需同时包含字母和数字")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")
    user: UserOut

"""Deployment settings that change how the process behaves."""

import os

import pytest

from app.config import apply_umask, config


@pytest.fixture
def umask():
    """Restore the process umask after the test."""
    previous = os.umask(0o022)
    yield
    os.umask(previous)


def current_umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


def test_umask_from_config(umask, monkeypatch):
    monkeypatch.setattr(config, "UMASK", "002")
    apply_umask()
    assert current_umask() == 0o002


def test_umask_left_alone_when_unset(umask, monkeypatch):
    monkeypatch.setattr(config, "UMASK", None)
    apply_umask()
    assert current_umask() == 0o022

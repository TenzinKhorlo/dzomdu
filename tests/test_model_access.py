"""Hugging Face access problems are explained in plain language, without network access."""

import sys
import types

import pytest

from dzomdu.diarize.pyannote import PyannoteDiarizer, access_problem

MODEL = "pyannote/speaker-diarization-community-1"


class RepositoryNotFoundError(Exception):
    pass


class GatedRepoError(RepositoryNotFoundError):  # same hierarchy as huggingface_hub
    pass


@pytest.fixture
def fake_hub(monkeypatch):
    state = {"token": "hf_saved", "error": None, "calls": 0}

    def auth_check(repo_id, token=None):
        state["calls"] += 1
        if state["error"]:
            raise state["error"]

    hub = types.ModuleType("huggingface_hub")
    hub.auth_check = auth_check
    hub.get_token = lambda: state["token"]
    errors = types.ModuleType("huggingface_hub.errors")
    errors.GatedRepoError = GatedRepoError
    errors.RepositoryNotFoundError = RepositoryNotFoundError
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "huggingface_hub.errors", errors)
    return state


def test_access_ok(fake_hub):
    assert access_problem(MODEL) is None


def test_no_token(fake_hub):
    fake_hub["token"] = None
    assert "hf auth login" in access_problem(MODEL)
    assert fake_hub["calls"] == 0  # nothing to check without a token


def test_terms_not_accepted(fake_hub):
    fake_hub["error"] = GatedRepoError("403")
    msg = access_problem(MODEL)
    assert "accept the conditions" in msg and "fine-grained" in msg


def test_bad_token(fake_hub):
    fake_hub["error"] = RepositoryNotFoundError("401")
    assert "did not accept your login" in access_problem(MODEL)
    unauthenticated = GatedRepoError("401 Client Error ... Please log in.")
    unauthenticated.response = types.SimpleNamespace(status_code=401)
    fake_hub["error"] = unauthenticated
    assert "did not accept your login" in access_problem(MODEL)


def test_offline(fake_hub):
    fake_hub["error"] = ConnectionError("no route")
    assert "Could not reach huggingface.co" in access_problem(MODEL)


def test_failed_load_explains_and_does_not_retry(fake_hub, monkeypatch):
    attempts = []

    class Pipeline:
        @staticmethod
        def from_pretrained(model, token=None):
            attempts.append(model)
            raise RuntimeError("download failed")

    audio = types.ModuleType("pyannote.audio")
    audio.Pipeline = Pipeline
    monkeypatch.setitem(sys.modules, "pyannote", types.ModuleType("pyannote"))
    monkeypatch.setitem(sys.modules, "pyannote.audio", audio)
    fake_hub["error"] = GatedRepoError("403")

    diarizer = PyannoteDiarizer(MODEL)
    for _ in range(3):  # e.g. several live-transcript chunks
        with pytest.raises(RuntimeError, match="accept the conditions"):
            diarizer._load()
    assert attempts == [MODEL]


def test_env_token_override_is_pointed_out(fake_hub, monkeypatch):
    fake_hub["error"] = RepositoryNotFoundError("401")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert "unset HF_TOKEN" not in access_problem(MODEL)
    monkeypatch.setenv("HF_TOKEN", "hf_...")
    assert "unset HF_TOKEN" in access_problem(MODEL)

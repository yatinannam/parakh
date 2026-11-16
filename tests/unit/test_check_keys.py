import httpx
import pytest

from tools.check_keys import check_groq, main

KEY = "gsk_test_SECRET_123"  # gitleaks:allow (fake key for tests)


def client(status=200, body=None, exc=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if exc is not None:
            raise exc
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        assert str(request.url) == "https://api.groq.com/openai/v1/models"
        return httpx.Response(status, json=body or {})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ok_lists_models_sorted():
    r = check_groq(KEY, client(200, {"data": [{"id": "whisper-large-v3-turbo"}, {"id": "a"}]}))
    assert r.ok
    assert r.models == ["a", "whisper-large-v3-turbo"]


@pytest.mark.parametrize(
    "status,exc,detail",
    [(401, None, "401"), (0, httpx.ConnectError("boom"), "ConnectError")],
)
def test_failures(status, exc, detail):
    r = check_groq(KEY, client(status, exc=exc))
    assert not r.ok
    assert detail in r.detail


def test_missing_env_file_exit_2(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert main(["--env", str(tmp_path / "dir with space" / ".env")]) == 2
    assert "GROQ_API_KEY not set" in capsys.readouterr().err


def test_empty_key_exit_2(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=\n", encoding="utf-8")
    assert main(["--env", str(env)]) == 2
    assert "GROQ_API_KEY not set" in capsys.readouterr().err


def test_success_message_and_exit_0(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text(f"GROQ_API_KEY={KEY}\n", encoding="utf-8")
    body = {"data": [{"id": "whisper-large-v3-turbo"}, {"id": "llama"}]}
    assert main(["--env", str(env)], client=client(200, body)) == 0
    assert capsys.readouterr().out.strip() == "groq: ok (2 models; whisper-large-v3-turbo: yes)"


def test_key_never_printed(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text(f"GROQ_API_KEY={KEY}\n", encoding="utf-8")
    clients = (client(200, {"data": []}), client(401), client(exc=httpx.ConnectError("boom")))
    codes = [main(["--env", str(env)], client=c) for c in clients]
    assert codes == [0, 1, 1]
    out = capsys.readouterr()
    assert KEY not in out.out
    assert KEY not in out.err


def raw_client(content: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "content",
    [b"<html>captive portal</html>", b'["not", "an", "object"]', b'{"data": [1, 2]}'],
    ids=["not-json", "list-body", "items-without-id"],
)
def test_unexpected_body_is_a_failure(content):
    r = check_groq(KEY, raw_client(content))
    assert not r.ok
    assert "unexpected response body" in r.detail


def test_non_ascii_key_is_a_clear_failure(tmp_path, capsys, monkeypatch):
    # A zero-width space pasted with the key cannot go into an HTTP header.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    bad_key = KEY + chr(0x200B)
    env = tmp_path / ".env"
    env.write_text(f"GROQ_API_KEY={bad_key}\n", encoding="utf-8")
    assert main(["--env", str(env)], client=client()) == 1
    out = capsys.readouterr()
    assert "non-ASCII" in out.err
    assert KEY not in out.out + out.err


def test_utf16_env_file_exit_2(tmp_path, capsys, monkeypatch):
    # Windows PowerShell 5.1 `>` writes UTF-16.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text(f"GROQ_API_KEY={KEY}\n", encoding="utf-16")
    assert main(["--env", str(env)]) == 2
    out = capsys.readouterr()
    assert "UTF-8" in out.err
    assert KEY not in out.out + out.err

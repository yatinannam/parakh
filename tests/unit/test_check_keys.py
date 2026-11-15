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
    codes = [main(["--env", str(env)], client=c) for c in (client(200, {"data": []}), client(401))]
    assert codes == [0, 1]
    out = capsys.readouterr()
    assert KEY not in out.out
    assert KEY not in out.err

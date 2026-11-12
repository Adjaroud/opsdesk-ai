import httpx
import pytest
from pathlib import Path
from streamlit.testing.v1 import AppTest

from app import db

UI = str(Path(__file__).resolve().parents[1] / "app" / "ui.py")


def bind_backend(client, monkeypatch):
    def local_request(method, url, **kwargs):
        kwargs.pop("timeout", None)
        return client.request(method, url.replace("http://127.0.0.1:18000", ""), **kwargs)
    monkeypatch.setattr(httpx, "request", local_request)


def test_ui_without_key_shows_data_and_disables_chat(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    bind_backend(client, monkeypatch)
    page = AppTest.from_file(UI).run(timeout=15)
    assert not page.exception
    assert len(page.dataframe) == 2
    assert next(b for b in page.button if b.label == "Envoyer").disabled
    next(b for b in page.button if b.label == "Problème VPN").click().run()
    assert "réunion" in page.text_area[0].value
    page.selectbox[0].select_index(1).run()
    assert page.session_state["employee_id"] == "EMP-002"
    assert not page.exception


def test_ui_click_is_required_for_real_creation(client, path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-only-for-ui-test")
    bind_backend(client, monkeypatch)
    page = AppTest.from_file(UI).run(timeout=15)
    page.text_area[0].set_value("Préparer un ticket VPN")
    next(b for b in page.button if b.label == "Envoyer").click().run(timeout=15)
    assert not page.exception
    with db.connect(path) as con:
        assert con.execute("SELECT count(*) FROM tickets").fetchone()[0] == 5
    next(b for b in page.button if b.label == "Approuver et créer le ticket").click().run(timeout=15)
    assert not page.exception
    assert page.success[0].value == "Ticket réellement créé : TKT-006"
    page.run()
    with db.connect(path) as con:
        assert con.execute("SELECT count(*) FROM tickets").fetchone()[0] == 6


def test_ui_backend_unavailable_is_actionable(monkeypatch):
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("internal-network-detail")
    monkeypatch.setattr(httpx, "request", unavailable)
    page = AppTest.from_file(UI).run(timeout=15)
    assert not page.exception
    assert "Backend indisponible" in page.error[0].value
    assert "internal-network-detail" not in page.error[0].value


@pytest.mark.parametrize("provider,selected_present,other_present", [
    ("gemini", False, True), ("gemini", True, False),
    ("openai", False, True), ("openai", True, False),
])
def test_ui_uses_only_selected_provider_key(client, monkeypatch, provider, selected_present, other_present):
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", provider)
    selected = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    other = "OPENAI_API_KEY" if provider == "gemini" else "GEMINI_API_KEY"
    if selected_present:
        monkeypatch.setenv(selected, "fake-selected-key")
    if other_present:
        monkeypatch.setenv(other, "fake-unselected-key")
    bind_backend(client, monkeypatch)
    page = AppTest.from_file(UI).run(timeout=15)
    assert not page.exception
    assert next(b for b in page.button if b.label == "Envoyer").disabled is (not selected_present)
    assert any(provider.capitalize() in t.value or (provider == "openai" and "OpenAI" in t.value) for t in page.text)
    if not selected_present:
        assert any(selected in notice.value for notice in page.info)


def test_ui_shows_safe_diagnostic_before_first_tool(client, monkeypatch):
    import json
    from app.llm import FakeLLM
    from app.llm_errors import LLMFailure
    def failure(*args, **kwargs):
        raise LLMFailure("output_limit")
    monkeypatch.setattr(FakeLLM, "decide", failure)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    bind_backend(client, monkeypatch)
    page = AppTest.from_file(UI).run(timeout=15)
    page.text_area[0].set_value("Problème VPN")
    next(b for b in page.button if b.label == "Envoyer").click().run(timeout=15)
    assert not page.exception
    assert "limite de tokens" in page.warning[0].value
    assert "output_limit" in json.dumps(page.json[0].value)


def test_ticket_example_tracks_selected_employee(client, monkeypatch):
    bind_backend(client, monkeypatch)
    page = AppTest.from_file(UI).run(timeout=15)
    page.selectbox[0].select_index(4).run()
    next(b for b in page.button if b.label == "Suivi ticket").click().run()
    assert page.text_area[0].value == "Quel est le statut de TKT-005 ?"

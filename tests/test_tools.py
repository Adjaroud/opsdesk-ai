import json

import pytest
from pydantic import ValidationError

from app import db
from app.seed import seed
from app.tools import Tools, tool_schemas
from conftest import DRAFT


def test_search_relevant_and_traceable(path):
    results = Tools("EMP-001", path).execute("search_kb", '{"query":"VPN connexion distante"}')
    assert results[0]["id"] == "KB-001"
    assert results[0]["score"] > 0
    assert results[0]["excerpt"]


def test_incidents_assets_and_ticket(path):
    tools = Tools("EMP-001", path)
    assert tools.execute("get_service_incidents", '{"service":"vpn"}')[0]["id"] == "INC-001"
    assert {a["id"] for a in tools.execute("get_employee_assets", '{}')} == {"AST-001", "AST-007"}
    assert tools.execute("get_ticket_status", '{"ticket_id":"TKT-001"}')["status"] == "en cours"
    with pytest.raises(PermissionError):
        tools.execute("get_ticket_status", '{"ticket_id":"TKT-002"}')


@pytest.mark.parametrize("name,args", [
    ("get_employee_assets", '{"employee_id":"EMP-002"}'),
    ("get_ticket_status", '{"ticket_id":"TKT-001 OR 1=1"}'),
    ("get_service_incidents", '{"service":"unknown"}'),
    ("search_kb", '{"query":""}'), ("search_kb", 'broken json'),
    ("draft_ticket", json.dumps({**DRAFT, "priority": "P1"})),
    ("draft_ticket", json.dumps({**DRAFT, "rationale": "urgent"})),
    ("create_ticket", '{}'),
])
def test_strict_arguments(path, name, args):
    with pytest.raises((ValueError, ValidationError)):
        Tools("EMP-001", path).execute(name, args)


def test_priority_and_draft_never_inserts_ticket(path):
    tools = Tools("EMP-001", path)
    result = tools.execute("draft_ticket", json.dumps({**DRAFT, "category": "hardware"}))
    assert result["draft"]["priority"] == "P3"
    assert "aucun incident majeur" in result["draft"]["rationale"]
    assert tools.execute("draft_ticket", json.dumps(DRAFT))["draft"]["priority"] == "P2"
    with db.connect(path) as con:
        assert con.execute("SELECT count(*) FROM tickets").fetchone()[0] == 5


def test_schemas_no_create_or_identity():
    schemas = tool_schemas()
    assert len(schemas) == 5
    for schema in schemas:
        assert schema["parameters"]["additionalProperties"] is False
        assert "employee_id" not in schema["parameters"]["properties"]
        assert set(schema["parameters"].get("required", [])) == set(schema["parameters"]["properties"])


def test_seed_idempotent(path):
    seed(path)
    with db.connect(path) as con:
        assert con.execute("SELECT count(*) FROM assets").fetchone()[0] == 8
        assert con.execute("SELECT count(*) FROM tickets").fetchone()[0] == 5

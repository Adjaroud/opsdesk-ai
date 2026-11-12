import json
import secrets
from contextlib import asynccontextmanager
from dataclasses import asdict
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException

from app import db
from app.agent import run_agent
from app.llm import close_llm, create_llm
from app.llm_config import LLMConfigError, llm_config
from app.models import Approval, ChatInput, Draft, SessionInput
from app.seed import seed
from app.tools import Tools, enforce_priority


def create_app(path=None, llm_factory=None):
    @asynccontextmanager
    async def lifespan(app):
        seed(path)
        yield

    app = FastAPI(title="OpsDesk AI — ITSM fictif", lifespan=lifespan)

    def session(x_session_token: str = Header(default="")):
        with db.connect(path) as con:
            result = db.rows(con, "SELECT * FROM sessions WHERE token=?", (x_session_token,))
        if not result:
            raise HTTPException(401, "Session fictive requise ; sélectionnez un salarié.")
        return result[0]

    @app.get("/health")
    def health():
        with db.connect(path) as con:
            con.execute("SELECT 1 FROM employees LIMIT 1")
        try:
            config = llm_config()
            return {"status": "ok", "demo": True, "llm_configured": config.configured,
                    "llm_provider": config.provider, "llm_model": config.model,
                    "llm_timeout_seconds": config.timeout_seconds, "chat_timeout_seconds": config.chat_timeout_seconds}
        except LLMConfigError as error:
            return {"status": "ok", "demo": True, "llm_configured": False,
                    "llm_provider": "invalid", "llm_model": "", "llm_config_error": str(error)}

    @app.get("/employees")
    def employees():
        with db.connect(path) as con:
            return db.rows(con, "SELECT * FROM employees ORDER BY id")

    @app.post("/sessions", status_code=201)
    def new_session(body: SessionInput):
        token = secrets.token_urlsafe(32)
        with db.connect(path) as con:
            if not con.execute("SELECT 1 FROM employees WHERE id=?", (body.employee_id,)).fetchone():
                raise HTTPException(404, "Salarié fictif inconnu.")
            con.execute("INSERT INTO sessions(token, employee_id) VALUES (?,?)", (token, body.employee_id))
        return {"token": token, "employee_id": body.employee_id}

    @app.get("/me/assets")
    def assets(active=Depends(session)):
        with db.connect(path) as con:
            return db.assets(con, active["employee_id"])

    @app.get("/me/tickets")
    def tickets(active=Depends(session)):
        with db.connect(path) as con:
            return db.rows(con, "SELECT id,category,priority,summary,status FROM tickets WHERE employee_id=? ORDER BY rowid DESC", (active["employee_id"],))

    @app.get("/tickets/{ticket_id}")
    def ticket(ticket_id: str, active=Depends(session)):
        with db.connect(path) as con:
            try:
                return db.ticket(con, active["employee_id"], ticket_id)
            except PermissionError:
                raise HTTPException(404, "Ticket inaccessible ou inexistant.") from None

    @app.get("/incidents/{service}")
    def incidents(service: str, active=Depends(session)):
        with db.connect(path) as con:
            return db.incidents(con, service)

    @app.post("/chat")
    def chat(body: ChatInput, active=Depends(session)):
        try:
            llm = llm_factory() if llm_factory else create_llm()
        except LLMConfigError as error:
            raise HTTPException(503, str(error)) from None
        except Exception:
            raise HTTPException(503, "Chat indisponible. Vérifiez le fournisseur, sa clé et OPSDESK_LLM_MODEL côté backend.") from None
        context = json.loads(active["context"])
        tools = Tools(active["employee_id"], path)
        tools.restore_references(context.get("references", []))
        try:
            result = run_agent(body.message, tools, llm, context.get("history", []))
        finally:
            close_llm(llm)
        # Every new request invalidates the previous unapproved proposal.
        context.pop("pending", None)
        draft_id = None
        if result.draft and not result.error:
            draft_id = uuid4().hex
            context["pending"] = {"id": draft_id, "draft": result.draft}
        if result.answer:
            context["references"] = (context.get("references", []) + [result.verified_refs])[-4:]
            context["history"] = (context.get("history", []) + [
                {"role": "user", "content": body.message},
                {"role": "assistant", "content": json.dumps(result.answer, ensure_ascii=False)}])[-8:]
        with db.connect(path) as con:
            con.execute("UPDATE sessions SET context=? WHERE token=?", (json.dumps(context), active["token"]))
        response = asdict(result)
        response.pop("verified_refs")
        return {**response, "draft_id": draft_id}

    @app.delete("/drafts/{draft_id}", status_code=204)
    def cancel(draft_id: str, active=Depends(session)):
        context = json.loads(active["context"])
        if context.get("pending", {}).get("id") == draft_id:
            context.pop("pending")
        with db.connect(path) as con:
            con.execute("UPDATE sessions SET context=? WHERE token=?", (json.dumps(context), active["token"]))

    @app.post("/tickets", status_code=201)
    def approve(body: Approval, active=Depends(session)):
        with db.connect(path) as con:
            # Serialize the check+insert transaction; unique constraint is a second protection.
            con.execute("BEGIN IMMEDIATE")
            previous = db.rows(con, "SELECT * FROM tickets WHERE session_token=? AND draft_id=?", (active["token"], body.draft_id))
            if previous:
                old = previous[0]
                if any(old[k] != v for k, v in body.draft.model_dump().items()):
                    raise HTTPException(409, "Clé déjà utilisée avec un autre brouillon.")
                return {"id": old["id"], "status": old["status"], "replayed": True}
            # Re-read session inside the write transaction, after any concurrent cancellation.
            current = con.execute("SELECT context FROM sessions WHERE token=?", (active["token"],)).fetchone()
            context = json.loads(current["context"])
            pending = context.get("pending", {})
            if pending.get("id") != body.draft_id or pending.get("draft") != body.draft.model_dump():
                raise HTTPException(409, "Brouillon absent, annulé ou modifié. Relancez la demande.")
            validated = enforce_priority(Draft.model_validate(pending["draft"]), con)
            if validated != body.draft:
                raise HTTPException(409, "Contexte d'incident modifié ; préparez un nouveau brouillon.")
            next_id = con.execute("SELECT COALESCE(MAX(CAST(substr(id,5) AS INTEGER)),0)+1 FROM tickets").fetchone()[0]
            ticket_id = f"TKT-{next_id:03}"
            d = validated.model_dump()
            con.execute("INSERT INTO tickets(id,employee_id,category,priority,summary,rationale,session_token,draft_id) VALUES (?,?,?,?,?,?,?,?)", (
                ticket_id, active["employee_id"], d["category"], d["priority"], d["summary"], d["rationale"], active["token"], body.draft_id))
            context.pop("pending")
            con.execute("UPDATE sessions SET context=? WHERE token=?", (json.dumps(context), active["token"]))
        return {"id": ticket_id, "status": "ouvert", "replayed": False}

    return app


app = create_app()

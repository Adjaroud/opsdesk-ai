"""Explicit opt-in real-provider check, temporary synthetic DB, no fallback."""
import argparse
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.agent import POLICY
from app.db import connect
from app.llm import create_llm, close_llm
from app.llm_errors import safe_failure
from app.llm_config import LLMConfigError, llm_config
from app.seed import seed
from app.tools import tool_schemas


def main(argv=None):
    parser = argparse.ArgumentParser(description="Vrais appels réseau : quota Gemini ou facturation OpenAI. Aucun fallback.")
    parser.add_argument("--confirm-network", action="store_true", help="Autoriser explicitement les appels au fournisseur sélectionné.")
    parser.add_argument("--approve-draft", action="store_true", help="Proposer une approbation interactive sur la base temporaire (saisir APPROUVER).")
    parser.add_argument("--first-decision-only", action="store_true", help="Un seul appel LLM pour le VPN, sans exécuter les outils ni créer de base/ticket.")
    args = parser.parse_args(argv)
    if not args.confirm_network:
        parser.error("Aucun appel effectué. Ajouter --confirm-network pour consommer le quota Gemini ou appeler OpenAI potentiellement payant.")
    if args.first_decision_only and args.approve_draft:
        parser.error("--first-decision-only ne peut pas être combiné à --approve-draft.")
    try:
        config = llm_config()
    except LLMConfigError as error:
        raise SystemExit(str(error)) from None
    if not config.configured:
        raise SystemExit(f"{config.key_name} requise ; aucun appel effectué.")
    print(f"VRAIS APPELS RÉSEAU : {config.provider} / {config.model}. Quota Gemini ou coût OpenAI selon le projet. Aucun fallback.", flush=True)
    if args.first_decision_only:
        llm = create_llm()
        try:
            decision = llm.decide(POLICY, [{"role": "user", "content": "Mon ordinateur ne se connecte plus au VPN depuis ce matin. J'ai une réunion dans une heure. Pouvez-vous m'aider ?"}], tool_schemas())
            allowed = {tool["name"] for tool in tool_schemas()}
            print("Première décision reçue ; outils proposés :", [c.name if c.name in allowed else "outil_non_autorise" for c in decision.calls])
            print("Aucun outil exécuté. Aucun ticket créé. Le parcours complet n'est pas validé par ce test.")
        except Exception as error:
            message, diagnostic = safe_failure(error)
            print(message)
            print("Diagnostic sûr :", diagnostic)
            raise SystemExit(1) from None
        finally:
            close_llm(llm)
        return
    sequences = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "smoke.db"
        seed(path)
        with TestClient(create_app(path)) as client:
            token = client.post("/sessions", json={"employee_id": "EMP-001"}).json()["token"]
            headers = {"X-Session-Token": token}
            result = None
            for prompt, expected in [
                ("Le VPN ne fonctionne plus ce matin. Vérifiez les incidents et la procédure. Que faire ?", {"get_service_incidents", "search_kb"}),
                ("Consultez mes équipements puis conseillez-moi pour mon écran noir.", {"get_employee_assets"}),
                ("Vérifiez maintenant le statut de mon ticket TKT-001.", {"get_ticket_status"}),
                ("Vérifiez maintenant si vous pouvez lire le ticket TKT-002, puis refusez si ce n'est pas autorisé.", {"get_ticket_status"}),
                ("Préparez maintenant un brouillon de ticket pour mon problème VPN, priorité justifiée. Ne créez rien.", {"draft_ticket"}),
            ]:
                response = client.post("/chat", json={"message": prompt}, headers=headers)
                if response.status_code != 200:
                    raise SystemExit("Chat indisponible : vérifier configuration, accès au modèle et clé. Aucun ticket créé.")
                result = response.json()
                sequence = [entry["tool"] for entry in result["trace"]]
                print("Demande :", prompt)
                print("Outils réellement choisis :", sequence)
                print("Réponse :", result["answer"] or result["error"])
                if result["error"] or not expected <= set(sequence):
                    raise SystemExit("Smoke test non concluant : examiner la trace. Aucun ticket créé.")
                if "TKT-002" in prompt and not any(t["status"] == "refusé" for t in result["trace"]):
                    raise SystemExit("Refus d'accès non observé. Aucun ticket créé.")
                sequences.append(tuple(sequence))
            with connect(path) as con:
                if con.execute("SELECT count(*) FROM tickets").fetchone()[0] != 5:
                    raise SystemExit("Échec : écriture avant approbation.")
            if len(set(sequences)) < 2 or not result["draft"]:
                raise SystemExit("Vérification des séquences ou du brouillon non concluante.")
            print("Au moins deux séquences différentes observées. Brouillon sans écriture vérifié.")
            if args.approve_draft:
                print("Brouillon de la base TEMPORAIRE :", result["draft"])
                if input("Pour créer un ticket temporaire, saisir APPROUVER : ").strip() == "APPROUVER":
                    body = {"draft_id": result["draft_id"], "draft": result["draft"], "approved": True}
                    first = client.post("/tickets", json=body, headers=headers)
                    second = client.post("/tickets", json=body, headers=headers)
                    if first.status_code != 201 or second.status_code != 201 or first.json()["id"] != second.json()["id"] or not second.json()["replayed"]:
                        raise SystemExit("Échec de la vérification d'approbation/idempotence.")
                    with connect(path) as con:
                        if con.execute("SELECT count(*) FROM tickets").fetchone()[0] != 6:
                            raise SystemExit("Nombre de tickets inattendu après approbation.")
                    print("Ticket temporaire créé :", first.json()["id"], "; second POST idempotent vérifié.")
                else:
                    print("Approbation annulée. Aucun ticket créé.")
            else:
                print("Aucun ticket créé. Utiliser --approve-draft pour tester l'approbation interactive.")


if __name__ == "__main__":
    main()

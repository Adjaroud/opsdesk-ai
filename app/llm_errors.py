"""Allow-listed diagnostics only. Never expose str(exception), bodies or headers."""
from openai import APIConnectionError, APIStatusError, APITimeoutError
import httpx
from pydantic import ValidationError


MESSAGES = {
    "authentication": "Clé refusée par le fournisseur. Vérifiez la clé locale et ses restrictions.",
    "permission": "Accès refusé par le fournisseur (HTTP 403). Vérifiez les restrictions de clé et l'accès du projet au modèle.",
    "model_not_found": "Modèle ou endpoint inaccessible (HTTP 404). Vérifiez le modèle sélectionné et son accès dans votre projet.",
    "invalid_request": "Requête refusée par le fournisseur (HTTP 400/422). Vérifiez la compatibilité des paramètres et des schémas d'outils.",
    "quota": "Quota du fournisseur atteint. Réessayez plus tard.",
    "provider_unavailable": "Service du fournisseur temporairement indisponible. Réessayez plus tard.",
    "timeout": "Le délai réseau du fournisseur est dépassé. Vérifiez le réseau ou le service ; vous pouvez ajuster OPSDESK_LLM_TIMEOUT_SECONDS.",
    "connection": "Connexion au fournisseur impossible. Vérifiez le réseau, le proxy et les certificats.",
    "output_limit": "Réponse interrompue par la limite de tokens de sortie. Le modèle n'a pas terminé sa décision.",
    "response_rejected": "Réponse du fournisseur bloquée ou incomplète. Aucune décision exploitable reçue.",
    "invalid_answer": "Réponse finale reçue, mais son JSON ne respecte pas le schéma attendu.",
    "unverified_reference": "Réponse finale rejetée : elle cite une référence non vérifiée par les outils de cet échange.",
    "invalid_response": "Réponse du fournisseur inexploitable. Vérifiez la compatibilité de l'adaptateur.",
    "unexpected": "Erreur interne pendant le traitement de la réponse. Aucun détail sensible n'est affiché.",
}


class LLMFailure(RuntimeError):
    def __init__(self, code):
        self.code = code if code in MESSAGES else "unexpected"
        super().__init__(MESSAGES[self.code])


def safe_failure(error):
    status = None
    if isinstance(error, LLMFailure):
        code = error.code
    elif isinstance(error, (APITimeoutError, TimeoutError)):
        code = "timeout"
    elif isinstance(error, APIConnectionError):
        code = "connection"
    elif isinstance(error, APIStatusError):
        status = error.status_code
        code = {400: "invalid_request", 401: "authentication", 402: "permission", 403: "permission",
                404: "model_not_found", 408: "timeout", 422: "invalid_request", 429: "quota"}.get(status, "provider_unavailable" if status >= 500 else "invalid_response")
        # Google can report invalid keys with HTTP 400. Only inspect the
        # structured, known reason; never copy arbitrary messages into the UI.
        body = error.body
        if isinstance(body, dict):
            data = body.get("error", body)
            if isinstance(data, dict):
                details = data.get("details", [])
                if isinstance(details, list) and any(isinstance(d, dict) and d.get("reason") in {"API_KEY_INVALID", "API_KEY_EXPIRED"} for d in details):
                    code = "authentication"
    elif isinstance(error, ValidationError):
        code = "invalid_answer"
    else:
        code = "unexpected"
    diagnostic = {"code": code}
    if code == "timeout":
        cause = error.__cause__
        for kind, phase in ((httpx.ConnectTimeout, "connect"), (httpx.ReadTimeout, "read"),
                            (httpx.WriteTimeout, "write"), (httpx.PoolTimeout, "pool")):
            if isinstance(cause, kind):
                diagnostic["network_phase"] = phase
                break
    if status is not None:
        diagnostic["http_status"] = status
    return MESSAGES[code] + " Aucun ticket créé.", diagnostic

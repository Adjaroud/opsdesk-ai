"""Streamlit presentation only: all decisions and approval checks stay in the API."""
import os

import httpx
import streamlit as st

API = os.environ.get("OPSDESK_API_URL", "http://127.0.0.1:18000").rstrip("/")
VPN_PROMPT = "Bonjour, mon ordinateur n'arrive plus à se connecter au VPN depuis ce matin. J'ai une réunion dans une heure. Pouvez-vous m'aider ?"
DRAFT_PROMPT = "Préparez un brouillon de ticket pour mon problème VPN, avec une priorité justifiée par les informations vérifiées. S'il manque une information, posez-moi une question."
st.set_page_config(page_title="OpsDesk AI · Support IT", page_icon="🛠️", layout="wide")
# Static styles only. No user, model or tool text is ever inserted into HTML.
st.markdown("""<style>
.block-container {max-width: 1120px; padding-top: 2.2rem; padding-bottom: 3rem;}
h1 {letter-spacing: -.035em;}
[data-testid="stSidebar"] {border-right: 1px solid rgba(120,130,150,.16);}
[data-testid="stChatMessage"] {border: 1px solid rgba(120,130,150,.15); border-radius: 12px;}
@media (max-width: 640px) {.block-container {padding-top: 1rem;}}
</style>""", unsafe_allow_html=True)


def request(method, route, **kwargs):
    headers = {"X-Session-Token": st.session_state.get("token", "")}
    try:
        response = httpx.request(method, API + route, headers=headers,
                                timeout=httpx.Timeout(st.session_state.get("chat_timeout_seconds", 355) if route == "/chat" else 7, connect=3), **kwargs)
        if response.is_error:
            messages = {401: "Sélectionnez à nouveau un salarié ou ouvrez une nouvelle conversation.",
                        404: "Ticket inaccessible ou inexistant pour ce salarié. Actualisez la liste.",
                        409: "Brouillon expiré ou modifié. Demandez un nouveau brouillon avant de valider.",
                        422: "Données invalides. Vérifiez votre saisie.",
                        503: "Chat indisponible : vérifiez le fournisseur, sa clé et son modèle côté backend."}
            st.error(messages.get(response.status_code, "Le backend n'a pas pu traiter la demande. Réessayez."))
            return None
        return response.json() if response.status_code != 204 else {}
    except (httpx.HTTPError, ValueError):
        st.error("Backend indisponible ou délai dépassé. Vérifiez son démarrage et OPSDESK_API_URL, puis réessayez.")
        return None


def start_session(employee_id):
    session = request("POST", "/sessions", json={"employee_id": employee_id})
    if not session:
        return False
    st.session_state.update(token=session["token"], employee_id=employee_id, messages=[],
                            pending=None, created=None, prompt="", vpn_attempted=False, draft_requested=False)
    st.session_state.pop("ticket_selection", None)
    st.session_state.ticket_focus = st.session_state.get("recent_tickets", {}).get(employee_id)
    return True


def open_tickets(ticket_id=None):
    # Callback runs before the next widget render: safe to select the radio mode.
    st.session_state.demo_mode = "Mes tickets"
    st.session_state.ticket_focus = ticket_id


def show_tickets(tickets):
    st.subheader("Mes tickets")
    st.caption("Tickets du salarié sélectionné · lecture seule · aucun appel LLM")
    # Clicking the button reruns the page and its single GET /me/tickets above.
    # No cache or session copy of list/detail data is used.
    st.button("Actualiser la liste", help="Relire les tickets depuis SQLite via le backend.")
    if tickets is None:
        st.warning("Liste des tickets indisponible. Vérifiez le backend puis cliquez sur Actualiser la liste.")
        return
    if not tickets:
        st.info("Aucun ticket pour ce salarié. Les tickets créés après approbation apparaîtront ici.")
        return
    st.caption("Les plus récents en premier, selon l'ordre de création dans la base. Les tickets initiaux sont également inclus.")
    st.dataframe(tickets, hide_index=True, column_config={
        "id": "Identifiant", "summary": "Résumé", "category": "Catégorie", "priority": "Priorité", "status": "Statut"})
    by_id = {ticket["id"]: ticket for ticket in tickets}
    recent = st.session_state.get("recent_tickets", {}).get(st.session_state.employee_id)
    if recent in by_id:
        with st.container(border=True):
            st.caption("DERNIER TICKET CRÉÉ DANS CETTE NAVIGATION")
            st.text(recent)
            st.text(by_id[recent]["summary"])
    focus = st.session_state.pop("ticket_focus", None)
    if focus in by_id:
        st.session_state.ticket_selection = focus
    elif st.session_state.get("ticket_selection") not in by_id:
        st.session_state.pop("ticket_selection", None)
    selected = st.selectbox("Ticket à consulter", list(by_id), key="ticket_selection",
                            format_func=lambda ticket_id: f'{ticket_id} — {by_id[ticket_id]["summary"]}')
    detail = request("GET", "/tickets/" + selected)
    if detail is None:
        st.warning("Les détails ne sont pas disponibles. Aucune ancienne réponse n'est affichée ; vous pouvez actualiser la liste.")
        return
    with st.container(border=True):
        st.caption("DÉTAILS RELUS DEPUIS LE BACKEND")
        for label, key in [("Identifiant", "id"), ("Résumé", "summary"), ("Catégorie", "category"), ("Priorité", "priority"), ("Statut", "status")]:
            st.text(f"{label} : {detail[key]}")


def submit_message(text, guided_action=None):
    """Only called on deliberate submit/button clicks. Never on a rerun or step change."""
    if guided_action == "vpn":
        st.session_state.vpn_attempted = True
    if guided_action == "draft":
        st.session_state.draft_requested = True
    with st.spinner("L'agent consulte la demande et choisit ses outils. Le fournisseur peut prendre un moment…"):
        result = request("POST", "/chat", json={"message": text.strip()})
    # A failed HTTP response is ambiguous: don't keep a potentially stale approval.
    st.session_state.pending = None
    if result is None:
        st.warning("Aucune nouvelle réponse disponible. Votre texte reste dans le formulaire ; vous pouvez réessayer. Aucun ticket n'est créé par l'envoi d'un message.")
        return
    st.session_state.messages.extend([{"role": "user", "content": text}, {"role": "assistant", "content": result}])
    if result.get("draft") and not result.get("error"):
        st.session_state.pending = {"draft_id": result["draft_id"], "draft": result["draft"]}
    st.session_state.created = None
    st.rerun()


def show_result(result):
    if result.get("error"):
        st.warning(result["error"])
        st.caption("Vous pouvez réessayer ou préciser la demande. Aucun ticket n'a été créé par cet échange.")
    answer = result.get("answer")
    if answer:
        st.caption("DIAGNOSTIC PRUDENT")
        st.text(answer["diagnosis"])
        if answer["advice"]:
            st.caption("CONSEILS")
            for advice in answer["advice"]:
                st.text("• " + advice)
        if answer["question"]:
            with st.container(border=True):
                st.caption("PRÉCISION NÉCESSAIRE · Répondez dans le formulaire")
                st.text(answer["question"])
        if answer["evidence_ids"]:
            st.text("Références consultées : " + ", ".join(answer["evidence_ids"]))
        if result["sources"]:
            with st.expander(f'Sources documentaires · {len(result["sources"])} procédure(s)'):
                for source in result["sources"]:
                    provenance = "source de session revalidée" if source.get("origin") == "session_revalidated" else f'score lexical {source["score"]}'
                    st.text(f'{source["id"]} — {source["title"]} ({provenance})')
                    st.text(source["excerpt"])
        else:
            st.caption("Aucune procédure citée pour cette réponse. Vous pouvez demander à l'agent de consulter la documentation.")
    with st.expander("Trace d'exécution"):
        st.caption("Appels réellement exécutés par l'agent pour ce message. Les données consultables dans la barre latérale sont indépendantes de cette trace.")
        if result["trace"]:
            st.table(result["trace"])
        else:
            st.caption("Aucun outil appelé.")
        if result.get("diagnostic"):
            st.caption("Diagnostic technique (sans contenu sensible)")
            st.json(result["diagnostic"])


st.caption("PORTFOLIO · IA AGENTIQUE · SUPPORT INFORMATIQUE")
st.title("OpsDesk AI — IT Support Agent Demo")
st.write("Comprendre une demande IT, vérifier les informations et préparer un ticket que vous seul pouvez approuver.")
st.caption("PME fictive · Procédures locales sourcées · Aucun ticket créé automatiquement")
health = request("GET", "/health")
employees = request("GET", "/employees")
if not health or not employees:
    st.info("Pour démarrer le backend : python -m uvicorn app.api:app --port 18000")
    st.stop()
st.session_state.chat_timeout_seconds = health.get("chat_timeout_seconds", 355)
provider = health.get("llm_provider", "openai")
provider_label = {"gemini": "Gemini", "openai": "OpenAI"}.get(provider, "configuration invalide")

with st.sidebar:
    st.header("Votre espace de démo")
    employee = st.selectbox("Salarié fictif", employees, format_func=lambda e: f'{e["name"]} — {e["department"]}', key="employee_picker")
    if st.session_state.get("employee_id") != employee["id"]:
        if not start_session(employee["id"]):
            st.stop()
    if st.button("Nouvelle conversation", use_container_width=True):
        if start_session(employee["id"]):
            st.rerun()
    st.caption("Changer de salarié ouvre une session séparée. Une nouvelle conversation abandonne le brouillon affiché ; elle ne supprime aucun ticket créé.")
    st.divider()
    st.text(f'Fournisseur LLM : {provider_label} ({health.get("llm_model", "")})')
    st.caption("La présence d'une clé ne garantit pas l'accès au modèle ni son quota. Aucun appel LLM au démarrage.")
    if health.get("llm_config_error"):
        st.warning(health["llm_config_error"])

    # Shared read for the dedicated view and the existing ticket example.
    my_tickets = request("GET", "/me/tickets")
    with st.expander("Consulter les données de démonstration", expanded=not health["llm_configured"]):
        st.caption("Lectures directes de l'API · données synthétiques")
        st.caption("La liste complète et les détails de vos tickets sont accessibles dans le parcours Mes tickets.")
        for label, route in [("Mes équipements", "/me/assets"), ("Incidents VPN", "/incidents/vpn")]:
            st.caption(label)
            data = request("GET", route)
            if data is not None:
                st.dataframe(data, hide_index=True)

if not health["llm_configured"]:
    key_name = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    st.info(f"Le chat {provider_label} nécessite {key_name} côté backend et une configuration valide. Aucun faux LLM n'est utilisé. Les exemples et données restent accessibles.")

mode = st.radio("Choisissez votre parcours", ["Démo guidée", "Exploration libre", "Mes tickets"], horizontal=True, key="demo_mode")
if mode == "Mes tickets":
    show_tickets(my_tickets)
    st.stop()
pending = st.session_state.get("pending")
created = st.session_state.get("created")
latest = next((entry["content"] for entry in reversed(st.session_state.messages) if entry["role"] == "assistant"), None)

if mode == "Démo guidée":
    with st.container(border=True):
        st.subheader("Du problème VPN au ticket validé")
        st.caption("1 · Choisir un salarié   →   2 · Examiner la réponse   →   3 · Préparer un brouillon   →   4 · Approuver")
        progress = 1.0 if created else .75 if pending else .5 if latest and latest.get("answer") else .25
        st.progress(progress)
        if created:
            st.write("Parcours terminé : le backend a confirmé la création du ticket. Consultez son identifiant ci-dessous ou ouvrez une nouvelle conversation.")
        elif pending:
            st.write("Le brouillon est prêt. Vérifiez sa priorité et sa justification dans la carte d'approbation ci-dessous. Rien n'a encore été créé.")
        else:
            if not st.session_state.vpn_attempted:
                st.write("Le salarié est sélectionné dans la barre latérale. Envoyez le scénario ci-dessous : l'agent choisira lui-même les outils utiles.")
                st.text(VPN_PROMPT)
            elif latest and latest.get("error"):
                st.write("Le parcours est en attente : le modèle a renvoyé une erreur. Consultez le diagnostic, puis réessayez quand le service est disponible.")
            elif latest and (latest.get("answer") or {}).get("question"):
                st.write("L'agent demande une précision. Répondez dans le formulaire de conversation avant de poursuivre si cette information est nécessaire.")
            elif st.session_state.draft_requested:
                st.write("Aucun brouillon reçu. L'agent peut demander une précision ou ne pas proposer d'action. Consultez sa réponse, précisez votre besoin, puis réessayez si pertinent.")
            else:
                st.write("Examinez la réponse, les références, les sources et la trace. Vous pouvez ensuite demander un brouillon de ticket.")
            vpn_col, draft_col = st.columns(2)
            if vpn_col.button("Envoyer la demande VPN" if not st.session_state.vpn_attempted else "Réessayer la demande VPN", disabled=not health["llm_configured"], use_container_width=True):
                submit_message(VPN_PROMPT, "vpn")
            if draft_col.button("Demander un brouillon", disabled=not health["llm_configured"] or not latest or not latest.get("answer"), use_container_width=True):
                submit_message(DRAFT_PROMPT, "draft")
        if latest and latest.get("answer"):
            evidence = latest["answer"]["evidence_ids"]
            cols = st.columns(3)
            cols[0].metric("Appels d'outils · dernier message", len(latest["trace"]))
            cols[1].metric("Incidents référencés", sum(ref.startswith("INC-") for ref in evidence))
            cols[2].metric("Procédures citées", len(latest["sources"]))
            if not any(ref.startswith("INC-") for ref in evidence):
                st.caption("Aucun incident référencé dans cette réponse. Le guide n'en invente pas et ne force aucun outil.")

st.subheader("Conversation")
if not st.session_state.messages:
    st.caption("Commencez avec le parcours guidé ou un exemple. En exploration libre, saisissez votre propre demande IT.")
for entry in st.session_state.messages:
    with st.chat_message(entry["role"]):
        if entry["role"] == "user":
            st.text(entry["content"])
        else:
            show_result(entry["content"])

st.caption("EXEMPLES À MODIFIER")
examples = [
    ("Problème VPN", VPN_PROMPT),
    ("Mon matériel", "Mon écran reste noir. Pouvez-vous consulter mes équipements et me conseiller ?"),
    ("Suivi ticket", f'Quel est le statut de {my_tickets[0]["id"]} ?' if my_tickets else "Je souhaite suivre un ticket. Quelles informations dois-je fournir ?"),
]
for col, (label, prompt) in zip(st.columns(3), examples):
    if col.button(label, use_container_width=True):
        st.session_state.prompt = prompt

with st.form("request_form"):
    text = st.text_area("Votre demande IT (ou réponse à la question de l'agent)", key="prompt", max_chars=2000,
                        placeholder="Décrivez le problème ou répondez à la question de l'agent…")
    send = st.form_submit_button("Envoyer", disabled=not health["llm_configured"], type="primary")
if send:
    if text.strip():
        submit_message(text)
    else:
        st.info("Saisissez une demande ou choisissez un exemple avant d'envoyer.")

pending = st.session_state.get("pending")
if pending:
    with st.container(border=True):
        st.subheader("Brouillon — aucun ticket créé")
        draft = pending["draft"]
        st.text(draft["summary"])
        category, priority = st.columns(2)
        category.metric("Catégorie", draft["category"].upper())
        priority.metric("Priorité proposée", draft["priority"])
        st.caption("JUSTIFICATION DE LA PRIORITÉ")
        st.text(draft["rationale"])
        st.info("Votre approbation est nécessaire. Le bouton ci-dessous demande au backend de créer ce ticket dans SQLite ; Annuler abandonne le brouillon.")
        approve, cancel = st.columns(2)
        if approve.button("Approuver et créer le ticket", type="primary", use_container_width=True):
            with st.spinner("Validation du brouillon et enregistrement du ticket…"):
                result = request("POST", "/tickets", json={**pending, "approved": True})
            if result:
                st.session_state.created = result["id"]
                recent = dict(st.session_state.get("recent_tickets", {}))
                recent[st.session_state.employee_id] = result["id"]
                st.session_state.recent_tickets = recent
                st.session_state.pending = None
                st.rerun()
        if cancel.button("Annuler", use_container_width=True):
            if request("DELETE", "/drafts/" + pending["draft_id"]) is not None:
                st.session_state.pending = None
                st.rerun()
if st.session_state.get("created"):
    st.success("Ticket réellement créé : " + st.session_state.created)
    st.caption("Identifiant retourné par le backend après écriture SQLite. Un rafraîchissement ne crée pas un nouveau ticket.")
    st.button("Voir ce ticket dans Mes tickets", on_click=open_tickets, args=(st.session_state.created,), type="primary")

with st.expander("Limites et sécurité"):
    st.write("Données entièrement fictives. Sélecteur sans authentification de production. Les outils sont limités à la session serveur ; la création exige une validation distincte. Les conseils LLM peuvent être erronés : vérifiez les procédures. Aucun email envoyé, logiciel installé ou droit modifié.")
    st.caption("Le guide propose des messages, pas une séquence d'outils. Le fournisseur peut demander une précision, ne citer aucune source ou rencontrer une erreur de quota. Les appels LLM consomment le quota du projet et peuvent être facturés selon sa configuration.")

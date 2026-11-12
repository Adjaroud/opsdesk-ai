# Vérifications de la version avec démo guidée et Mes tickets

Date : 12 novembre 2026. Environnement : Windows, Python 3.12.7, dépendances de `requirements.lock.txt`.

## Résultats exécutés

| Contrôle | Résultat |
| --- | --- |
| `python -m pytest -q --tb=short` | **148 réussis, 0 échec, 1 avertissement**, en 32,30 s lors du contrôle avant publication |
| Tests d'interface existants et guidés, avant la suite complète | 19 réussis |
| `python -m compileall -q app scripts` | Réussi |
| `python -m pip check` | Aucune dépendance incompatible |
| `docker compose config --quiet` | Réussi, sans affichage des secrets interpolés |
| `python -m scripts.check_publication` | Aucun fichier privé, clé locale connue ou motif de clé détecté dans les candidats Git examinés |
| API temporaire sur `127.0.0.1:18002/health` (version du 11 novembre) | `status=ok`, `demo=true`, `llm_configured=false` |
| Streamlit temporaire sur `127.0.0.1:8503/_stcore/health` (version du 11 novembre) | `ok` |

Les contrôles de lancement réseau des deux dernières lignes concernent la version précédente ; ils n'ont pas été rejoués pour Mes tickets. La nouvelle vue est vérifiée avec Streamlit AppTest et FastAPI TestClient, sur une base SQLite temporaire. Aucun appel de génération réel n'a été effectué pendant le contrôle avant publication. Le commit initial et le push GitHub sont autorisés par le propriétaire après contrôles ; aucun déploiement n'est prévu.

## Ce que vérifient les nouveaux tests

`test_tickets_ui.py` ajoute neuf cas à la suite précédente de 139 tests :

- liste des tickets initiaux et détails provenant des endpoints existants, sans clé ni appel LLM ;
- ticket créé par le POST d'approbation réel de l'API de test, présélectionné et mis en évidence depuis le lien de confirmation ;
- tickets récents en premier, selon l'ordre SQLite déjà fourni par l'API ;
- persistance après une nouvelle conversation, un rerun et une nouvelle session navigateur de test ;
- nouvelle lecture de la liste et des détails au clic Actualiser (une requête de liste par affichage) ;
- changement de salarié sans réutilisation de la sélection ou des détails du précédent, avec refus API d'un ticket non autorisé ;
- salarié sans ticket ;
- erreurs de liste et de détail (500/404), sans ancien détail affiché, puis récupération après actualisation ;
- persistance en SQLite après redémarrage de l'application FastAPI de test.

Les approbations sont générées par des clics AppTest explicites ou des POST de test. Le seul LLM utilisé pour préparer les données est le faux déterministe déjà présent ; les consultations ne l'utilisent pas. Aucun ajout d'outil ni changement du mécanisme d'idempotence. Deux anciennes assertions de comptage des tableaux ont été adaptées : la table de tickets n'est plus dupliquée dans la barre latérale et apparaît dans la nouvelle vue.

`test_guided_ui.py` utilise Streamlit AppTest, une véritable application FastAPI de test et une base SQLite temporaire. Les décisions LLM sont explicitement prescrites par FakeLLM. Les scénarios vérifient :

- le parcours VPN → outils et sources → brouillon → clic d'approbation → identifiant du ticket écrit ;
- l'absence d'écriture avant approbation et de nouvel appel à chaque rerun ou changement de mode ;
- le salarié propriétaire du ticket créé ;
- les variations : clarification, absence de source, absence de brouillon, quota et backend indisponible ;
- l'annulation, la nouvelle conversation et le changement de salarié, sans réutiliser un ancien brouillon dans la nouvelle session ;
- les boutons désactivés en l'absence de clé ;
- l'affichage du texte du modèle sans interprétation HTML.

Les anciens tests d'idempotence et de concurrence restent conservés. Les tests de publication vérifient aussi les règles d'exclusion, la détection d'un fichier privé déjà suivi par Git (y compris dans des sous-dossiers) et d'une clé locale recopiée dans une source, sans afficher sa valeur. Le contrôle avant publication examine 57 fichiers candidats Git, dont le montage final et une capture réelle ; les prises originales restent exclues. Aucune clé locale connue ou motif de clé détecté.

## Limites de la vérification

- Les tests hors ligne ne valident pas le comportement sémantique du vrai LLM. Le guide ne force aucune séquence d'outils ; un fournisseur réel peut demander une précision, omettre des sources ou ne pas proposer de brouillon.
- Le propriétaire rapporte des parcours manuels réussis avec Gemini (VPN et écran noir, tickets distincts). La vidéo jointe montre un parcours VPN jusqu'au ticket TKT-013 et sa consultation dans Mes tickets ; les tests utilisent leurs propres tickets dans une base temporaire. Ces exemples ne constituent pas une évaluation statistique du LLM.
- Le navigateur de contrôle automatisé n'a pas démarré lors du chantier d'interface. Une capture extraite de l'enregistrement réel fourni par le propriétaire et une vidéo montée sont maintenant incluses. Les composants sont natifs Streamlit ; le rendu sur mobile mérite encore un contrôle manuel.
- Le moteur Docker Desktop est arrêté : construction et exécution des images non vérifiées. Le thème Streamlit est copié dans l'image UI ; seule la configuration Compose a été validée localement.
- Un avertissement Starlette indique que son client de test utilisant `httpx` est déprécié. Il n'empêche pas les tests de passer.
- La branche locale `main` est initialisée pour la première publication autorisée. Le contrôle examine les candidats du dépôt réel, y compris les fichiers déjà suivis même s'ils sont ensuite ignorés. Le code du contrôle ne réalise lui-même aucun commit ou push.
- Les exclusions et motifs de clés ne constituent pas une preuve universelle d'absence de secret. Relire le diff avant publication et ne pas forcer l'ajout d'un fichier privé ignoré.

## Contrôle manuel avant publication

1. Démarrer la démo puis ouvrir **Démo guidée** avec un salarié fictif.
2. Envoyer le VPN, vérifier la trace et les éventuelles sources réellement retournées.
3. Répondre aux précisions éventuelles, demander le brouillon et lire la priorité justifiée.
4. Vérifier qu'aucun ticket n'est apparu avant approbation, puis approuver et relever l'identifiant réel. Cliquer Voir ce ticket dans Mes tickets : vérifier la sélection, la mise en évidence et les cinq champs du détail.
5. Cliquer Actualiser, ouvrir une nouvelle conversation, revenir dans Mes tickets puis rafraîchir la page : le ticket doit toujours être présent pour son salarié. Changer de salarié doit afficher uniquement ses propres tickets. Vérifier aussi le mode libre et une largeur d'écran mobile.
6. Vérifier la capture et la vidéo réelles jointes dans `docs/media/`, sans clé ou donnée privée.
7. Relancer tests et contrôle de publication, puis inspecter le diff Git. La première publication est explicitement autorisée par le propriétaire ; l'application ne réalise aucune publication automatique.

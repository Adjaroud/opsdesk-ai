# Montage final avec sources et traces — OpsDesk AI

Date : 12 novembre 2026. Cette version remplace le montage précédent de 64,60 secondes.

## Export livré

- **Fichier : `opsdesk-ai-demo.mp4`**.
- **Durée : 73,60 secondes (1 min 13,6 s)**.
- **Taille : 9,09 Mo** (9089536 octets), inférieure à 25 Mo.
- H.264 High, yuv420p, **1918 × 866**, 30 images/s ; proportions du programme principal conservées.
- MP4 web : index `moov` avant `mdat` (`faststart`).
- Aucune piste audio : les deux prises ont un niveau maximum mesuré à −91 dBFS. Aucune voix ni musique ajoutée.
- Décodage complet vérifié : **2 208 images**, sans erreur.
- Images clés contrôlées visuellement : sources/outils, trace du brouillon, confirmation et détail du ticket.

Les originaux `demo_f.mp4` (124,33 s, 1918 × 866) et `trace_et_sources.mp4` (23,13 s, 1918 × 860) sont conservés intacts ; leurs empreintes ont été vérifiées avant et après montage. L’ancien export est sauvegardé localement dans le dossier de travail ignoré `review_exports/video_edit/opsdesk-ai-demo-v1.mp4`.

Aucun code d’application modifié, aucun appel LLM et aucune publication effectués.

## Ajout des preuves agentiques

Deux plans de **4,5 secondes** ont été insérés dans le montage existant :

1. **Export 00:21,00–00:25,50** : procédure **KB-001**, incident **INC-001** et trace du diagnostic avec **`get_service_incidents`** et **`search_kb`**, chacun au statut `ok`. Extrait de la prise complémentaire entre 00:02,50 et 00:07,00, à vitesse normale.
2. **Export 00:43,50–00:48,00** : source KB-001 et trace avec **`search_kb`** et **`draft_ticket`**, au statut `ok`. Arrêt sur l’image réelle de la prise complémentaire à 00:15,00, pour permettre de lire les deux lignes.

Les cartouches indiquent **Prise complémentaire** et, pour le second plan, **Arrêt sur image · prise complémentaire**. Ces plans ont été regroupés près des étapes correspondantes ; ils ne prétendent pas faire partie d’une capture continue en temps réel.

La nouvelle prise correspond au même salarié fictif, au même modèle affiché (Gemini 3.1 Flash-Lite), à la même demande VPN et à la précision « erreur 110 ». L’incident INC-001, la procédure KB-001 et le ticket TKT-013 concordent avec le programme principal. Aucun appel ou résultat n’est reconstruit.

Le premier insert est recadré uniquement sur les 810 premières lignes pour retirer le début du message suivant, déjà montré plus tard dans le programme principal, puis complété par une marge blanche jusqu’à 866 lignes. La procédure et les deux lignes de trace restent entièrement visibles. Le second insert reçoit une marge blanche de six lignes en bas pour harmoniser sa hauteur, sans déformation.

## Parcours conservé

Les six étapes restent : demande VPN → diagnostic et sources → précision utilisateur → brouillon P2 et justification → clic humain d’approbation → confirmation **TKT-013**, puis consultation dans **Mes tickets**.

Les attentes LLM du programme principal sont toujours ramenées à deux secondes chacune avec **Temps d’attente raccourci**. La saisie et deux passages de navigation accélérés portent également une mention. Diagnostic, clarification, brouillon, approbation, confirmation et détails restent à vitesse normale. Le cartouche éditorial est placé au-dessus du contenu de la barre latérale, sans masquer ces informations.

## Relevé précis des coupes et vitesses

Format des temps : minutes:secondes.centisecondes. Raccords directs, sans transition animée.

| Prise | Temps source | Temps export | Traitement |
| --- | --- | --- | --- |
| demo_f.mp4 | 00:00.00–00:08.80 | 00:00.00–00:08.80 | Temps réel |
| demo_f.mp4 | 00:08.80–00:44.80 | 00:08.80–00:10.80 | ×18 — Temps d’attente raccourci |
| demo_f.mp4 | 00:44.80–00:55.00 | 00:10.80–00:21.00 | Temps réel |
| trace_et_sources.mp4 | 00:02.50–00:07.00 | 00:21.00–00:25.50 | Temps réel |
| demo_f.mp4 | 00:55.00–01:01.00 | 00:25.50–00:31.50 | Temps réel |
| demo_f.mp4 | 01:01.00–01:13.00 | 00:31.50–00:35.50 | ×3 — Saisie accélérée ×3 |
| demo_f.mp4 | 01:13.00–01:14.00 | 00:35.50–00:36.50 | Temps réel |
| demo_f.mp4 | 01:14.00–01:29.60 | 00:36.50–00:38.50 | ×7.8 — Temps d’attente raccourci |
| demo_f.mp4 | 01:29.60–01:34.60 | 00:38.50–00:43.50 | Temps réel |
| trace_et_sources.mp4 | 00:15.00 (image fixe) | 00:43.50–00:48.00 | Arrêt sur image signalé, 4,5 s |
| demo_f.mp4 | 01:34.60–01:38.80 | 00:48.00–00:50.10 | ×2 — Navigation accélérée ×2 |
| demo_f.mp4 | 01:38.80–01:46.80 | 00:50.10–00:58.10 | Temps réel |
| demo_f.mp4 | 01:46.80–01:48.00 | 00:58.10–00:59.30 | Temps réel |
| demo_f.mp4 | 01:48.00–01:52.00 | 00:59.30–01:03.30 | Temps réel |
| demo_f.mp4 | 01:52.00–01:56.00 | 01:03.30–01:05.30 | ×2 — Navigation accélérée ×2 |
| demo_f.mp4 | 01:56.00–02:04.30 | 01:05.30–01:13.60 | Temps réel |

Les 0,03 dernières secondes environ de `demo_f.mp4` ne sont pas retenues. Seuls les deux extraits décrits de `trace_et_sources.mp4` sont utilisés ; ses autres passages, répétitifs pour ce montage, sont écartés.

## Lisibilité et limites

Les sources et traces sont maintenant lisibles : aucune nouvelle prise n’est nécessaire pour corriger leur absence dans la première version. Une pause permet de lire l’intégralité de la procédure, qui est trop longue pour une lecture exhaustive en 4,5 secondes. La trace montre les **noms et statuts**, pas le détail des arguments ou des résultats internes ; le montage ne prétend pas les exposer.

La source principale montre un brouillon proposé à la suite de la précision utilisateur, sans demande distincte « Préparez un brouillon » enregistrée. Aucun clic ou message supplémentaire n’a été fabriqué. La validation humaine avant création est conservée.

Avant partage, lire la vidéo plein écran sur ordinateur et conserver les deux originaux en archive locale. Ne pas déduire un temps de réponse réel des attentes raccourcies.

## Empreintes SHA-256

- `demo_f.mp4` : `5f649a9b68aa89055208924a8ef31d5156d1e8548e0a29669cae65e0e29b928c`
- `trace_et_sources.mp4` : `1344b3a79d88677fb6af3691687d48c1f288fbac802c83b8b9828612277f13a2`
- Export final : `51878c3ad5facdbcc4ef31958f92e580c55d5a871165bd2682de66b6e06b3ea5`

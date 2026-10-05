# Evidence Desk

Evidence Desk est une petite démo de recherche documentaire locale. Le corpus contient trois procédures fictives : accès, qualité de données et gestion d’incident. Une question ne reçoit une réponse que si un passage actif peut l’étayer.

Il s’agit d’un projet personnel de démonstration. Les documents livrés sont fictifs et servent à rendre les mécanismes testables. Ce n’est ni une base de connaissances client ni un service de conformité en production.

## Scénario et choix

- recherche SQLite FTS5 suivie d’un reranking lexical explicite ;
- catalogue de sources avec identifiant stable, version, propriétaire, niveau déclaré, statut et date de revue ;
- exclusion des sources `draft` ou `superseded` de la recherche ;
- préférence déclarée pour une source `authoritative` ou `controlled` lorsque la pertinence textuelle est équivalente ;
- réponse extractive citée par défaut, sans appel externe ;
- abstention explicite quand aucun passage actif ne soutient la question ;
- reçu local qui conserve les empreintes de la question et des passages, sans écrire la question en clair ;
- quatre cas de référence : trois réponses attendues et une abstention attendue.

Un fournisseur de texte peut être configuré en développement. Son résultat n’est retenu que si chaque phrase contient une référence syntaxiquement valide. Cette vérification ne prouve pas que la phrase est vraie, donc la réponse extractive reste le chemin par défaut.

## Démarrer

```bash
cd evidence-desk
PYTHONPATH=src python3 -m evidence_desk.server
```

Ouvrir ensuite `http://localhost:8080`. Au démarrage, les documents de démonstration et leur catalogue sont indexés.

Questions de démonstration :

```text
Quand faut-il faire valider une demande d’accès ?
Quel contrôle bloque un indicateur critique ?
Quand prévenir le responsable lors d’un incident élevé ?
```

Pour observer le refus, demander par exemple :

```text
Quel est le protocole de rotation des clés cryptographiques ?
```

Le corpus fourni ne contient pas cette règle. Une bonne réponse est donc un refus clair, pas une invention.

Dans l’interface, cette question ne retourne aucun passage : la page de lecture affiche « preuves insuffisantes » et le reçu ne garde que les empreintes de la question et des passages.

La réponse s’affiche comme une page annotée : chaque phrase porte un appel de note qui mène au passage cité, placé en marge sur grand écran et sous le paragraphe sur mobile. Le reçu de recherche ferme la page. À l’ouverture, la page montre une réponse d’exemple calculée sans écrire de reçu.

Pendant la frappe (à partir de 3 caractères, après 250 ms sans saisie), la marge affiche le classement FTS5 des passages candidats et indique lesquels passeraient le seuil de la réponse. Chaque note propose aussi d’écarter sa source : la recherche est relancée sans elle, la réponse change ou devient une abstention, et un bouton rétablit le corpus. L’exclusion vaut pour la requête seulement ; l’index n’est pas modifié.

![Page de lecture d’Evidence Desk : la question sur un indicateur critique en échec, les candidats FTS5 en marge, la réponse avec ses appels [1] et [2] et le premier passage cité](docs/demo.png)

## Ce que l’on peut inspecter

Chaque source retournée contient :

- une citation stable de la forme `SOURCE_ID@VERSION#pPOSITION` ;
- l’extrait exact utilisé ;
- une empreinte courte du contenu ;
- le propriétaire, le niveau déclaré, le statut et le signal de fraîcheur de la source.

Chaque requête crée aussi un reçu tel que `EDR-000042`. Il associe l’empreinte normalisée de la question, la liste des passages récupérés et une empreinte de preuve. La question et la réponse en clair ne sont pas écrites dans le reçu, ce qui réduit l’exposition du texte mais ne constitue pas une garantie de confidentialité à lui seul.

## Ajouter une source en développement local

Déposer un fichier `.md`, `.txt` ou `.html` dans `data/`, puis appeler l’API avec ses métadonnées :

```json
{
  "path": "data/mon-document.md",
  "metadata": {
    "source_id": "POL-EXAMPLE-001",
    "version": "1.0",
    "authority": "controlled",
    "status": "active",
    "owner": "Data Governance",
    "reviewed_at": "2026-10-01",
    "review_due_at": "2027-04-01"
  }
}
```

Les valeurs d’autorité admises sont `authoritative`, `controlled`, `reference` et `unclassified`. Les statuts admis sont `active`, `draft` et `superseded`. Seules les sources actives peuvent appuyer une réponse.

Lorsqu’une nouvelle version active arrive avec le même `source_id`, Evidence Desk passe les versions actives précédentes à `superseded`. Le corpus ne mélange donc pas silencieusement une procédure remplacée avec sa version courante.

Le catalogue de démonstration est dans [`data/demo/catalog.json`](data/demo/catalog.json). Il sépare volontairement les métadonnées de gouvernance du texte des documents.

## API de démonstration

- `GET /api/health`
- `GET /api/documents`
- `GET /api/receipts?limit=20`
- `GET /api/evaluation`
- `POST /api/query` avec `{ "question": "...", "exclude_sources": ["RUN-INC-002"] }` ; `exclude_sources` est facultatif, et `"preview": true` répond sans écrire de reçu
- `POST /api/candidates` avec `{ "question": "..." }` (3 caractères minimum) : classement FTS5 brut, passages retenus ou non, sans reçu
- `POST /api/ingest` avec le chemin d’un fichier déjà présent sous `data/` et des métadonnées optionnelles. Cet endpoint sert au développement local ; il ne reçoit pas de fichier uploadé et ne doit pas être exposé tel quel.

## Vérifier le projet

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Les tests couvrent notamment l’idempotence de l’ingestion, la provenance au niveau du passage, la mise à l’écart d’une source remplacée, l’abstention sûre et la traçabilité des cas de référence.

## Choix et limites

SQLite FTS5 est volontaire : le chemin documents, passages, recherche, réponse et preuve reste facile à inspecter. Ce projet ne prétend pas remplacer un système documentaire d’équipe. Il ne possède pas encore de gestion d’identité, de droits documentaires, d’ingestion asynchrone, de stockage vectoriel, de chiffrement applicatif ni de revue humaine intégrée.

Une version équipe demanderait au minimum une authentification, un contrôle d’accès par document, un pipeline d’ingestion isolé, une stratégie de rétention des reçus, des évaluations annotées par des personnes et une observabilité centralisée. La fiche de travail décrit ces arbitrages et les prochaines expériences dans [`docs/working-paper.md`](docs/working-paper.md).

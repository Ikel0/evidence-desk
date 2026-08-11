# Evidence Desk: fiche de travail

## Pourquoi ce projet

Dans beaucoup d’équipes, les règles de sécurité, les procédures et les décisions passées existent déjà. Le problème est qu’elles sont dispersées dans des documents et qu’il devient difficile de retrouver la bonne version au bon moment. Un assistant qui répond sans montrer ses preuves ajoute un nouveau risque au lieu d’en enlever un.

Evidence Desk est mon terrain d’expérimentation pour une idée simple: une réponse documentaire doit être vérifiable par la personne qui la lit.

## Questions de travail

1. Comment retrouver un passage utile sans dépendre immédiatement d’un modèle externe ?
2. Comment rendre la source, sa version et son extrait visibles dans l’interface ?
3. Que doit faire le système lorsque les preuves disponibles sont trop faibles ?
4. Comment évaluer le produit autrement qu’avec une impression de fluidité ?

## Première architecture

```text
Documents locaux
    -> lecture et normalisation
    -> hash de contenu et version
    -> chunking avec recouvrement
    -> SQLite FTS5
    -> recherche lexicale et reranking
    -> réponse extractive ou LLM optionnel
    -> sources, extraits et niveau de confiance
```

Le choix de SQLite et FTS5 est volontaire. Il rend le chemin d’exécution lisible, permet de travailler sans clé API et évite de masquer les questions de retrieval derrière un modèle. Pour une version équipe, je remplacerais cette base locale par Postgres avec pgvector ou un moteur vectoriel, et j’ajouterais une ingestion asynchrone ainsi qu’une gestion des droits.

## Hypothèses à vérifier

- Pour un corpus documentaire court et structuré, une recherche lexicale bien instrumentée peut déjà donner des résultats utiles.
- La citation du passage source rend une réponse plus contestable, donc plus fiable dans un contexte de travail.
- Un score de confiance ne vaut que s’il est lié à des signaux observables: nombre de sources, recouvrement de la question, fraîcheur et statut documentaire.

## Protocole d’évaluation

Le dossier `eval/` contient des questions de référence. Pour chaque question, je vérifie au minimum:

- que la réponse ne contredit pas la procédure ;
- que le passage attendu est retrouvé ;
- que la citation ouvre une trace exploitable ;
- que le système s’abstient lorsqu’aucune preuve n’est récupérée.

La prochaine itération ajoutera une mesure de recall@k, une annotation humaine des réponses et des scénarios de documents contradictoires.

## Limites actuelles

- Les documents de démonstration sont petits et textuels.
- Le reranking est lexical et non sémantique.
- Le niveau de confiance est heuristique.
- Il n’y a pas encore de gestion des utilisateurs, des permissions ni d’historique de conversation.

Ces limites font partie du projet. Elles donnent un point de départ précis pour discuter de la suite plutôt que de faire croire qu’un prototype résout déjà tous les problèmes d’un RAG d’entreprise.

## Suite envisagée

1. Ajouter un extracteur PDF avec conservation du numéro de page.
2. Comparer retrieval lexical, hybride et vectoriel sur le même jeu de questions.
3. Ajouter une interface d’annotation pour valider ou contester une réponse.
4. Introduire des permissions documentaires et une piste d’audit de consultation.

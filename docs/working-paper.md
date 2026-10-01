# Evidence Desk : fiche de travail

## Problème étudié

Dans une équipe, les règles de sécurité, les standards data et les procédures d'incident existent souvent déjà. Le problème n'est pas seulement de les retrouver. Il faut aussi savoir si le passage consulté est actif, quelle version il représente, qui en est responsable et si sa revue est encore à jour.

Une réponse fluide sans ces éléments peut sembler utile tout en étant dangereuse. Evidence Desk explore donc un RAG où la preuve est un objet de premier plan, et non une annexe ajoutée après la génération.

## Question de travail

Comment proposer une réponse documentaire qui reste utile quand le retrieval est bon, mais qui devient prudente lorsque les preuves sont faibles, remplacées ou difficiles à inspecter ?

## Hypothèses

1. Pour un corpus court et structuré, un retrieval lexical instrumenté peut être une base lisible avant d'introduire un modèle vectoriel.
2. Une citation utile doit désigner un passage, une source stable, une version et une empreinte de contenu.
3. L'abstention est une fonctionnalité du produit, pas un échec de l'interface.
4. Un score global est insuffisant. Il faut distinguer retrieval, ancrage, citations, traçabilité et refus sûr.

## Architecture actuelle

```text
Document local + catalogue de source
    -> lecture et normalisation
    -> hash de contenu + identifiant/version métier
    -> chunking avec recouvrement
    -> SQLite FTS5
    -> filtre des sources actives
    -> reranking lexical
    -> réponse extractive citée ou LLM validé
    -> reçu de récupération sans question en clair
```

Le catalogue est distinct du contenu. Il porte `source_id`, `version`, `authority`, `status`, `owner`, `reviewed_at` et `review_due_at`. Cette séparation évite de confondre le hash technique d'un fichier avec une version validée par un propriétaire de document.

## Contrat de réponse

Une réponse est considérée exploitable seulement si les conditions suivantes sont réunies :

| Signal | Règle actuelle | Effet visible |
| --- | --- | --- |
| Source active | Les sources `draft` et `superseded` sont exclues | Elles ne peuvent pas justifier une réponse |
| Priorité documentaire | À pertinence égale, `authoritative` puis `controlled` passent avant une simple référence | Le système rend visible la hiérarchie déclarée des sources |
| Passage traçable | Chaque source possède une citation `id@version#passage` | La personne qui lit sait quoi vérifier |
| Fraîcheur | La date de revue est comparée à la date courante | Un passage peut être utilisé avec un avertissement de revue |
| Génération | Le LLM optionnel doit citer chaque phrase factuelle | Sinon retour à une synthèse extractive locale |
| Preuves absentes | Aucun passage actif récupéré | Refus explicite, aucune réponse inventée |

Le système ne transforme pas une source dont la revue est échue en vérité inutilisable. Il le signale car l'évaluation métier reste une décision humaine. En revanche, une source remplacée ou en brouillon est retirée du chemin de réponse.

Quand une nouvelle version `active` d'un même `source_id` est ingérée, les versions actives antérieures deviennent `superseded`. Ce mécanisme ne résout pas les contradictions métier, mais empêche le cas plus banal où deux versions d'une même règle sont servies ensemble sans avertissement.

## Reçu de récupération

Chaque interrogation génère un reçu, par exemple `EDR-000042`. Il contient :

- l'empreinte SHA-256 de la question normalisée ;
- la liste des passages récupérés avec leur source, version, position et hash de contenu ;
- l'empreinte de cet ensemble de preuves ;
- l'état rendu, le mode de génération et le motif de repli éventuel ;
- l'horodatage de l'opération.

Le reçu ne stocke pas la question ni la réponse en clair. Le but est de pouvoir comparer une décision de retrieval tout en réduisant le risque de créer un historique non maîtrisé de contenu potentiellement sensible.

## Évaluation `golden.v2`

Le jeu de référence contient trois questions appuyées par le corpus de démonstration et un cas où le système doit s'abstenir. Pour chaque question, le projet mesure séparément :

- rappel du passage attendu ;
- présence de l'élément attendu dans la réponse ;
- présence de citations ;
- correspondance avec la source attendue ;
- traçabilité de la citation, de la version et du hash ;
- succès de l'abstention sûre pour les questions hors corpus.

Ce jeu ne démontre pas une qualité universelle. C'est un seuil de non-régression reproductible. Les résultats ne doivent pas être interprétés comme une mesure de performance sur des documents réels, ni comme une validation de conformité.

## Décisions prises

### Pourquoi une réponse extractive par défaut ?

Elle rend le comportement testable sans clé API, sans dépendance à un fournisseur externe et sans masquer la qualité du retrieval. Un fournisseur compatible peut être configuré, mais son texte est accepté seulement si les citations `[S1]`, `[S2]` correspondent aux passages transmis.

### Pourquoi ne pas enregistrer les requêtes en clair ?

Une question peut contenir un nom, un incident ou une information interne. Pour le prototype, l'audit porte donc sur les empreintes et les preuves. En environnement équipe, la stratégie de journalisation devrait être définie avec les équipes sécurité, légales et métier.

### Pourquoi SQLite FTS5 ?

Parce qu'il garde le système totalement local et observable. Ce n'est pas le choix final pour un corpus large ou multi-utilisateur. Une suite réaliste demanderait Postgres et pgvector ou un moteur vectoriel, un pipeline d'ingestion asynchrone, des sauvegardes, une supervision et des règles d'accès.

## Limites connues

- Le catalogue des documents de démonstration est manuel.
- Le reranking est lexical et ne comprend pas les paraphrases complexes.
- Le signal de fraîcheur dépend d'une date renseignée par le propriétaire.
- Les citations valident la provenance, pas la vérité métier du contenu.
- Il n'y a pas encore d'authentification, de permissions documentaires, de chiffrement applicatif ni d'annotation humaine.
- Le reçu est une piste de démonstration locale, pas une solution de conservation réglementaire.

## Prochaines expériences

1. Ajouter des tests de documents contradictoires et vérifier la présentation du conflit.
2. Comparer FTS5, retrieval hybride et vectoriel sur le même jeu annoté.
3. Ajouter un écran de revue où une personne peut confirmer, corriger ou rejeter une réponse.
4. Associer les sources à des droits d'accès et filtrer le retrieval avant la génération.
5. Définir une politique de rétention et une exportation de reçus vérifiables.

Le projet reste volontairement honnête sur ce qui est implémenté. Sa valeur est de rendre visibles les décisions et les compromis nécessaires avant d'appeler un prototype un système RAG fiable.

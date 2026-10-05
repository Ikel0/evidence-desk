const form = document.getElementById('query-form');
const question = document.getElementById('question');
const reading = document.getElementById('reading');
const status = document.getElementById('status');
const feedback = document.getElementById('form-feedback');
const askButton = document.getElementById('ask');
const askLabel = askButton.querySelector('.button-label');
const liveList = document.getElementById('live-list');
const liveHint = document.getElementById('live-hint');

const LIVE_DELAY_MS = 250;
const LIVE_MIN_CHARS = 3;
const INITIAL_QUESTION = 'Que se passe-t-il lorsqu’un indicateur critique échoue à un contrôle de qualité ?';

// Sources que le lecteur a écartées pour la question affichée.
const excluded = new Set();
let shownQuestion = '';

function asText(value, fallback = '') {
  if (value === undefined || value === null || value === '') return fallback;
  return String(value);
}

function asRecord(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function create(tagName, className, content) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  if (content !== undefined && content !== null) element.textContent = asText(content);
  return element;
}

function plural(count, singular, pluralForm = `${singular}s`) {
  // En français, 0 et 1 prennent le singulier.
  return `${count} ${count <= 1 ? singular : pluralForm}`;
}

function formatDate(value) {
  if (!value) return 'non renseignée';
  const raw = asText(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    return new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium' }).format(new Date(`${raw}T12:00:00`));
  }
  // SQLite écrit CURRENT_TIMESTAMP en UTC, sans fuseau : on le relit comme tel.
  const sqlite = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})$/.exec(raw);
  const date = new Date(sqlite ? `${sqlite[1]}T${sqlite[2]}Z` : raw);
  if (Number.isNaN(date.getTime())) return raw;
  const text = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'long', timeStyle: 'medium', timeZone: 'UTC' }).format(date);
  return `${text} UTC`;
}

function humanize(value) {
  const raw = asText(value, 'non renseigné');
  const labels = {
    active: 'actif',
    authoritative: 'priorité haute',
    controlled: 'priorité standard',
    draft: 'brouillon',
    extractive: 'passages repris sans génération',
    grounded: 'passages actifs retrouvés',
    grounded_with_review_warning: 'passages actifs, revue à vérifier',
    insufficient_evidence: 'preuves insuffisantes',
    llm_cited: 'texte généré avec références présentes',
    none: 'sans génération',
    reference: 'référence',
    superseded: 'remplacée',
    unclassified: 'non classée',
  };
  return labels[raw] ?? raw.replace(/[_-]/g, ' ');
}

// « Source active », « Source remplacée » : le statut s'accorde avec « source ».
const SOURCE_STATUS = {
  active: 'Source active',
  draft: 'Source en brouillon',
  superseded: 'Source remplacée',
};

function setFeedback(message = '', type = '') {
  feedback.textContent = message;
  feedback.className = `form-feedback${type ? ` ${type}` : ''}`;
}

function setBusy(isBusy) {
  askButton.disabled = isBusy;
  askLabel.textContent = isBusy ? 'Recherche…' : 'Chercher';
  askButton.setAttribute('aria-busy', String(isBusy));
  reading.setAttribute('aria-busy', String(isBusy));
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    throw new Error('La réponse du service est illisible.');
  }
  if (!response.ok) {
    throw new Error(asText(payload.error, 'Le service n’a pas pu traiter la demande.'));
  }
  return asRecord(payload);
}

async function refreshStatus() {
  try {
    const data = await fetchJson('/api/health');
    const documents = Number(data.documents ?? data.document_count ?? 0);
    status.textContent = `${plural(documents, 'document')} actif${documents <= 1 ? '' : 's'} dans le corpus`;
  } catch {
    status.textContent = 'Corpus indisponible pour le moment.';
  }
}

/* Cas de référence (suite golden) */

function yesNo(value) {
  return value ? 'oui' : 'non';
}

function percent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 'n/d';
  return `${Math.round(number * 100)} %`;
}

function renderEvaluationRow(item) {
  const record = asRecord(item);
  const row = create('tr');
  const expected = record.expected_abstention ? 'abstention' : 'réponse citée';
  const outcome = create('td', record.passed ? '' : 'is-fail', record.passed ? 'validé' : 'échoué');
  row.append(
    create('td', '', asText(record.question, 'Cas de référence')),
    create('td', '', expected),
    create('td', '', record.expected_abstention ? '—' : yesNo(record.retrieved && record.source_match)),
    create('td', '', record.expected_abstention ? '—' : yesNo(record.cited)),
    outcome,
  );
  return row;
}

async function refreshEvaluation() {
  const summary = document.getElementById('eval-summary');
  const items = document.getElementById('eval-items');
  const rates = document.getElementById('eval-rates');

  try {
    const data = await fetchJson('/api/evaluation');
    const total = Number(data.total ?? 0);
    const passed = Number(data.passed ?? 0);
    const suite = asText(data.suite, 'golden');
    summary.textContent = `Suite ${suite} : ${passed} cas validés sur ${total}. Chaque cas vérifie le passage attendu et sa citation, ou une abstention quand le corpus ne contient pas la règle.`;
    items.replaceChildren(...(Array.isArray(data.items) ? data.items.map(renderEvaluationRow) : []));
    rates.textContent = `Rappel des passages ${percent(data.retrieval_recall)}, réponses étayées ${percent(data.grounded_answer_rate)}, citations ${percent(data.citation_rate)}, traçabilité ${percent(data.traceability_rate)}, abstentions correctes ${percent(data.safe_abstention_rate)}.`;
  } catch {
    summary.textContent = 'Les résultats de la suite d’évaluation ne sont pas disponibles pour le moment.';
    items.replaceChildren();
    rates.textContent = '';
  }
}

/* Page de lecture */

// Découpe la réponse sur les marqueurs [S1], [S2]… et numérote les notes
// dans l'ordre de leur premier appel, comme dans un texte annoté.
function parseAnswer(text, sources) {
  const byId = new Map(sources.map(source => [asText(asRecord(source).id), asRecord(source)]));
  const order = [];
  const parts = [];
  const pattern = /\s*\[(S\d+)\]/g;
  let last = 0;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) parts.push({ text: text.slice(last, match.index) });
    const id = match[1];
    if (byId.has(id)) {
      if (!order.includes(id)) order.push(id);
      parts.push({ call: id });
    }
    last = pattern.lastIndex;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });

  // Passages retournés mais jamais appelés : ils restent visibles en fin de marge.
  const uncited = sources.map(source => asText(asRecord(source).id)).filter(id => id && !order.includes(id));
  const numbers = new Map([...order, ...uncited].map((id, index) => [id, index + 1]));
  return { parts, numbers, byId, cited: new Set(order) };
}

// Le serveur préfixe la réponse extractive ; la page le dit déjà par sa structure.
// Le texte renvoyé par l'API (et évalué par la suite golden) reste inchangé.
const ANSWER_PREFIX = /^D[’']après les passages récupérés\s*:\s*/;

function displayedAnswer(value) {
  const text = asText(value);
  const stripped = text.replace(ANSWER_PREFIX, '');
  return stripped ? stripped.charAt(0).toUpperCase() + stripped.slice(1) : text;
}

function renderAnswer(parts, numbers) {
  const paragraph = create('p', 'answer main-col');
  const seen = new Map();
  parts.forEach(part => {
    if (part.text !== undefined) {
      paragraph.append(document.createTextNode(part.text));
      return;
    }
    const number = numbers.get(part.call);
    const occurrence = (seen.get(number) ?? 0) + 1;
    seen.set(number, occurrence);
    const sup = create('sup', 'reference');
    const link = create('a', 'call', `[${number}]`);
    link.href = `#note-${number}`;
    link.id = `call-${number}-${occurrence}`;
    link.setAttribute('aria-label', `Note ${number}`);
    link.dataset.note = String(number);
    sup.append(link);
    paragraph.append(sup);
  });
  return paragraph;
}

function sourceStatusLine(record) {
  const pieces = [SOURCE_STATUS[record.status] ?? `Statut ${humanize(record.status)}`];
  if (record.reviewed_at) pieces.push(`revue le ${formatDate(record.reviewed_at)}`);
  const freshness = asRecord(record.freshness);
  if (freshness.state === 'review_overdue') pieces.push('revue dépassée');
  else if (record.review_due_at) pieces.push(`prochaine revue le ${formatDate(record.review_due_at)}`);
  if (record.authority) pieces.push(humanize(record.authority));
  if (record.owner) pieces.push(asText(record.owner));
  return `${pieces.join(', ')}.`;
}

function renderNote(id, number, record, isCited) {
  const item = create('li', 'note');
  item.id = `note-${number}`;
  item.dataset.note = String(number);

  // Comme une liste de références : numéro, flèche de retour vers l'appel, titre du document.
  const head = create('p', 'note-head');
  head.append(create('span', 'note-num', `${number}.`));
  if (isCited) {
    const back = create('a', 'note-back', '↑');
    back.href = `#call-${number}-1`;
    back.setAttribute('aria-label', `Revenir à l’appel ${number} dans le texte`);
    head.append(back);
  }
  head.append(create('cite', 'note-doc', asText(record.document ?? record.title, 'Document sans titre')));
  item.append(head);

  const ref = create('p', 'note-ref');
  ref.append(create('code', '', asText(record.citation, `${asText(record.source_id, id)}@${asText(record.version, '?')}#p${asText(record.position, '?')}`)));
  item.append(ref);

  if (!isCited) item.append(create('p', 'note-uncited', 'Passage retrouvé, non repris dans la réponse.'));

  const excerpt = asText(record.excerpt ?? record.text, 'Aucun extrait n’a été transmis pour ce passage.');
  item.append(create('blockquote', 'note-excerpt', excerpt));

  let statusLine = sourceStatusLine(record);
  if (excerpt.endsWith('…')) statusLine += ' Extrait abrégé : le passage complet est dans le document.';
  item.append(create('p', 'note-status', statusLine));

  const sourceId = asText(record.source_id);
  if (sourceId) {
    const setAside = create('button', 'note-action', 'Écarter cette source');
    setAside.type = 'button';
    setAside.setAttribute('aria-label', `Écarter ${sourceId} et relancer la recherche`);
    setAside.addEventListener('click', () => {
      excluded.add(sourceId);
      runQuery(shownQuestion, { keepExclusions: true });
    });
    item.append(setAside);
  }
  return item;
}

function renderColophon(payload, sources) {
  const retrieval = asRecord(payload.retrieval);
  const receipt = asRecord(payload.receipt ?? payload.retrieval_receipt ?? payload.trace);
  const timestamp = receipt.recorded_at ?? receipt.retrieved_at ?? receipt.created_at ?? receipt.timestamp ?? payload.created_at;
  const receiptId = receipt.id ?? receipt.request_id ?? payload.request_id;
  const queryFingerprint = receipt.query_fingerprint ?? receipt.query_hash ?? receipt.query_id;
  const evidenceHash = receipt.evidence_fingerprint ?? receipt.evidence_hash ?? receipt.result_hash ?? payload.evidence_hash;
  const count = Number(receipt.retrieved_passages ?? retrieval.returned ?? sources.length) || 0;
  const isPreview = receipt.preview === true;

  const colophon = create('footer', 'colophon main-col');
  colophon.append(create('h3', '', 'Reçu de recherche'));
  const list = create('dl');
  const rows = [
    ['Méthode', asText(retrieval.strategy ?? receipt.strategy, 'non déclarée')],
    ['Passages', plural(count, 'passage retenu', 'passages retenus')],
    ['Reçu', isPreview ? 'non enregistré : exemple affiché à l’ouverture' : asText(receiptId, 'non émis'), !isPreview],
    ['Empreinte de la question', asText(queryFingerprint, 'non émise'), true],
    ['Empreinte des passages', asText(evidenceHash, 'non émise'), true],
    ['État', humanize(receipt.state ?? payload.state ?? 'non déclaré')],
    ['Horodatage', timestamp ? formatDate(timestamp) : 'non enregistré'],
  ];
  const setAside = Array.isArray(retrieval.excluded_sources) ? retrieval.excluded_sources : [];
  if (setAside.length) rows.splice(2, 0, ['Sources écartées', setAside.join(', ')]);
  rows.forEach(([label, value, isCode]) => {
    const detail = create('dd');
    if (isCode) detail.append(create('code', '', value));
    else detail.textContent = value;
    list.append(create('dt', '', label), detail);
  });
  colophon.append(list);
  colophon.append(create('p', 'colophon-note', 'Le reçu garde les empreintes de la question et des passages, pas leur texte en clair.'));
  return colophon;
}

function renderResult(data, asked, options = {}) {
  const payload = asRecord(data);
  const sources = Array.isArray(payload.sources) ? payload.sources : [];
  const state = asText(payload.state ?? asRecord(payload.receipt).state);
  const abstained = state === 'insufficient_evidence' || sources.length === 0;

  const article = create('article', 'reading-page');
  article.setAttribute('aria-labelledby', 'reading-title');

  const titleRow = create('div', 'page-grid');
  const titleCol = create('div', 'main-col');
  const title = create('h2', 'reading-title', asked);
  title.id = 'reading-title';
  title.tabIndex = -1;
  titleCol.append(title);

  const body = create('div', 'page-grid reading-body');

  if (abstained) {
    titleCol.append(create('p', 'reading-byline', 'Aucun passage cité.'));
    const main = create('div', 'main-col');
    main.append(
      create('p', 'abstention-state', 'Preuves insuffisantes.'),
      create('p', 'answer', asText(payload.answer, 'Le corpus indexé ne contient pas de passage actif qui réponde à cette question.')),
    );
    const margin = create('p', 'margin-col abstention-note', asText(asRecord(payload.retrieval).reason, 'Aucun passage actif ne soutient cette question.'));
    body.append(main, margin);
  } else {
    const { parts, numbers, byId, cited } = parseAnswer(displayedAnswer(payload.answer), sources);
    const byline = [plural(cited.size, 'passage cité', 'passages cités'), humanize(payload.generation ?? asRecord(payload.receipt).generation)];
    if (state === 'grounded_with_review_warning') byline.push('au moins une source a dépassé sa date de revue');
    titleCol.append(create('p', 'reading-byline', `${byline.join(', ')}.`));

    const notes = create('ol', 'notes');
    notes.setAttribute('aria-labelledby', 'notes-title');
    const margin = create('section', 'margin-col references');
    const notesTitle = create('h3', 'references-title', 'Références');
    notesTitle.id = 'notes-title';
    margin.append(notesTitle, notes);
    [...numbers.entries()].forEach(([id, number]) => notes.append(renderNote(id, number, byId.get(id), cited.has(id))));
    body.append(renderAnswer(parts, numbers), margin);
  }

  const colophonRow = create('div', 'page-grid');
  colophonRow.append(renderColophon(payload, sources));

  const setAside = Array.isArray(asRecord(payload.retrieval).excluded_sources) ? payload.retrieval.excluded_sources : [];
  if (setAside.length) {
    const banner = create('div', 'modified');
    banner.append(create('p', '', `Scénario modifié par vous : ${setAside.length > 1 ? `les sources ${setAside.join(', ')} sont écartées` : `la source ${setAside[0]} est écartée`} de la recherche. Les cas de référence ne portent pas sur ce scénario.`));
    const restore = create('button', 'note-action', 'Rétablir le corpus complet');
    restore.type = 'button';
    restore.addEventListener('click', () => {
      excluded.clear();
      runQuery(shownQuestion, { keepExclusions: true });
    });
    banner.append(restore);
    titleCol.append(banner);
  }

  titleRow.append(titleCol);
  article.append(titleRow, body, colophonRow);
  linkCallsAndNotes(article);
  reading.replaceChildren(article);

  if (!options.initial) {
    // Ne déplace la vue que si la page de lecture commence hors de l'écran.
    if (article.getBoundingClientRect().top > window.innerHeight * .6) {
      const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      article.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' });
    }
    title.focus({ preventScroll: true });
  }
}

// Survol ou focus d'un appel : son passage est mis en évidence, et inversement.
// Le lien reste la voie principale (clic, toucher, clavier) ; le surlignage n'ajoute aucune information.
function linkCallsAndNotes(root) {
  const toggle = (number, on) => {
    root.querySelectorAll(`[data-note="${number}"]`).forEach(element => element.classList.toggle('is-linked', on));
  };
  root.querySelectorAll('[data-note]').forEach(element => {
    const number = element.dataset.note;
    ['mouseenter', 'focusin'].forEach(type => element.addEventListener(type, () => toggle(number, true)));
    ['mouseleave', 'focusout'].forEach(type => element.addEventListener(type, () => toggle(number, false)));
  });
}

async function runQuery(value, options = {}) {
  if (!options.keepExclusions) excluded.clear();
  setFeedback('');
  setBusy(true);
  try {
    const data = await fetchJson('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: value, exclude_sources: [...excluded], preview: options.initial === true }),
    });
    shownQuestion = value;
    renderResult(data, value, options);
    refreshCandidates(value);
  } catch (error) {
    const detail = error instanceof Error ? error.message : '';
    setFeedback(`La recherche n’a pas abouti. ${detail}`.trim(), 'is-error');
  } finally {
    setBusy(false);
  }
}

async function submitQuestion(event) {
  event.preventDefault();
  const value = question.value.trim();
  if (!value) {
    setFeedback('Écrivez une question avant de lancer la recherche.', 'is-error');
    question.focus();
    return;
  }
  clearTimeout(liveTimer);
  runQuery(value);
}

/* Candidats pendant la frappe : le vrai classement FTS5, sans reçu. */

let liveTimer;
let liveController;

function candidateState(row) {
  if (row.excluded) return 'source écartée par vous';
  if (row.retained) return 'retenu pour la réponse';
  return 'sous le seuil de recouvrement';
}

function renderCandidates(data) {
  const rows = Array.isArray(data.candidates) ? data.candidates.map(asRecord) : [];
  if (!rows.length) {
    liveHint.textContent = 'Aucun passage ne contient ces termes : la réponse serait une abstention.';
    liveList.replaceChildren();
    return;
  }
  const kept = rows.filter(row => row.retained).length;
  liveHint.textContent = kept
    ? `${plural(Number(data.fts_matches) || rows.length, 'passage trouvé', 'passages trouvés')} par FTS5, ${plural(kept, 'retenu', 'retenus')} pour la réponse.`
    : `${plural(Number(data.fts_matches) || rows.length, 'passage trouvé', 'passages trouvés')}, aucun ne passe le seuil : la réponse serait une abstention.`;
  liveList.replaceChildren(...rows.map(row => {
    const item = create('li', `live-row${row.retained ? ' is-kept' : ''}`);
    const head = create('p', 'live-head');
    head.append(
      create('span', 'live-rank', `${asText(row.rank)}.`),
      create('code', '', asText(row.citation)),
    );
    const score = Number(row.bm25);
    const scoreText = Number.isFinite(score) ? score.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : 'n/d';
    item.append(head, create('p', 'live-meta', `bm25 ${scoreText}, ${plural(Number(row.overlap) || 0, 'terme commun', 'termes communs')}, ${candidateState(row)}`));
    return item;
  }));
}

async function refreshCandidates(value) {
  const text = asText(value).trim();
  liveController?.abort();
  if (text.length < LIVE_MIN_CHARS) {
    liveList.replaceChildren();
    liveHint.textContent = text.length
      ? `Encore ${LIVE_MIN_CHARS - text.length} caractère${LIVE_MIN_CHARS - text.length > 1 ? 's' : ''} avant la recherche.`
      : 'Le classement se met à jour à partir de 3 caractères, sans écrire de reçu.';
    return;
  }
  liveController = new AbortController();
  try {
    const data = await fetchJson('/api/candidates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: text, exclude_sources: text === shownQuestion ? [...excluded] : [] }),
      signal: liveController.signal,
    });
    renderCandidates(data);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return;
    liveHint.textContent = 'Le classement n’est pas disponible pour le moment.';
    liveList.replaceChildren();
  }
}

question.addEventListener('input', () => {
  clearTimeout(liveTimer);
  liveTimer = setTimeout(() => refreshCandidates(question.value), LIVE_DELAY_MS);
});

form.addEventListener('submit', submitQuestion);

const platform = navigator.userAgentData?.platform ?? navigator.platform ?? '';
if (/mac|iphone|ipad/i.test(platform)) {
  document.getElementById('shortcut-modifier').textContent = '⌘';
}

question.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') form.requestSubmit();
});

document.querySelectorAll('[data-question]').forEach(button => {
  button.addEventListener('click', () => {
    question.value = asText(button.dataset.question);
    form.requestSubmit();
  });
});

refreshStatus();
refreshEvaluation();

// État initial complet et statique : une vraie réponse citée, calculée sans écrire de reçu.
question.value = INITIAL_QUESTION;
runQuery(INITIAL_QUESTION, { initial: true });

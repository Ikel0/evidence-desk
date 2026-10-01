const form = document.getElementById('query-form');
const question = document.getElementById('question');
const result = document.getElementById('result');
const status = document.getElementById('status');
const feedback = document.getElementById('form-feedback');
const askButton = document.getElementById('ask');
const askLabel = askButton.querySelector('.button-label');

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

function percentage(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : 'non calculé';
}

function plural(count, singular, pluralForm = `${singular}s`) {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function formatDate(value) {
  if (!value) return 'non renseignée';
  if (/^\d{4}-\d{2}-\d{2}$/.test(asText(value))) {
    return new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium' }).format(new Date(`${value}T12:00:00`));
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return asText(value);
  return new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function humanize(value) {
  const raw = asText(value, 'non renseigné');
  const labels = {
    active: 'actif',
    authoritative: 'faisant autorité',
    controlled: 'contrôlée',
    draft: 'brouillon',
    extractive: 'synthèse extractive locale',
    grounded: 'réponse ancrée',
    grounded_with_review_warning: 'réponse ancrée, revue à surveiller',
    insufficient_evidence: 'preuves insuffisantes',
    llm_cited: 'synthèse LLM citée',
    none: 'sans génération',
    reference: 'référence',
    superseded: 'remplacée',
    unclassified: 'non classée',
  };
  return labels[raw] ?? raw.replace(/[_-]/g, ' ');
}

function setFeedback(message = '', type = '') {
  feedback.textContent = message;
  feedback.className = `form-feedback${type ? ` ${type}` : ''}`;
}

function setBusy(isBusy) {
  askButton.disabled = isBusy;
  askLabel.textContent = isBusy ? 'Recherche des passages' : 'Consulter les preuves';
  askButton.setAttribute('aria-busy', String(isBusy));
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
    const mode = asText(data.mode ?? data.runtime ?? 'local-first');
    status.textContent = `Corpus prêt · ${plural(documents, 'document')} indexé${documents === 1 ? '' : 's'} · ${mode}`;
    status.classList.remove('is-error');
  } catch {
    status.textContent = 'Corpus indisponible pour le moment';
    status.classList.add('is-error');
  }
}

function renderEvaluationItem(item) {
  const record = asRecord(item);
  const element = create('span', `eval-item${record.passed ? ' pass' : ' fail'}`);
  const dot = create('i');
  dot.setAttribute('aria-hidden', 'true');
  element.append(dot, document.createTextNode(asText(record.question, 'Cas de référence')));
  return element;
}

async function refreshEvaluation() {
  const score = document.getElementById('eval-score');
  const label = document.getElementById('eval-label');
  const retrieval = document.getElementById('eval-retrieval');
  const grounding = document.getElementById('eval-grounding');
  const citations = document.getElementById('eval-citations');
  const traceability = document.getElementById('eval-traceability');
  const abstention = document.getElementById('eval-abstention');
  const items = document.getElementById('eval-items');

  try {
    const data = await fetchJson('/api/evaluation');
    const total = Number(data.total ?? 0);
    const passed = Number(data.passed ?? 0);
    score.textContent = `${passed}/${total}`;
    label.textContent = 'cas de référence validés';
    retrieval.textContent = percentage(data.retrieval_recall);
    grounding.textContent = percentage(data.grounded_answer_rate);
    citations.textContent = percentage(data.citation_rate);
    traceability.textContent = percentage(data.traceability_rate);
    abstention.textContent = percentage(data.safe_abstention_rate);
    items.replaceChildren(...(Array.isArray(data.items) ? data.items.map(renderEvaluationItem) : []));
  } catch {
    score.textContent = '...';
    label.textContent = 'Suite indisponible';
    retrieval.textContent = '...';
    grounding.textContent = '...';
    citations.textContent = '...';
    traceability.textContent = '...';
    abstention.textContent = '...';
    items.replaceChildren(create('span', 'eval-item fail', 'Les métriques ne sont pas disponibles.'));
  }
}

function appendDefinitionList(target, rows) {
  target.replaceChildren();
  rows.forEach(([label, value, className]) => {
    const term = create('dt', className || '', label);
    const detail = create('dd', className || '', value);
    target.append(term, detail);
  });
}

function confidenceTone(value, hasSources) {
  const normalized = asText(value).toLocaleLowerCase('fr-FR');
  if (!hasSources || /faible|insuffisant|absten/.test(normalized)) return 'is-low';
  if (/élev|high|fort/.test(normalized)) return 'is-high';
  return 'is-medium';
}

function sourceMetadata(source) {
  const record = asRecord(source);
  const rows = [
    ['Version', asText(record.version, 'non déclarée')],
    ['Passage', record.position ? `n° ${asText(record.position)}` : 'non déclaré'],
  ];

  const authority = record.authority ?? record.source_authority ?? record.owner;
  if (authority) rows.push(['Autorité', humanize(authority)]);

  const freshness = record.freshness ?? record.freshness_label;
  if (freshness && typeof freshness === 'object') {
    const freshnessRecord = asRecord(freshness);
    rows.push(['Fraîcheur', asText(freshnessRecord.label ?? freshnessRecord.state, 'non déclarée')]);
  }
  else if (freshness) rows.push(['Fraîcheur', asText(freshness)]);
  else if (record.updated_at ?? record.updatedAt ?? record.published_at) rows.push(['Mis à jour', formatDate(record.updated_at ?? record.updatedAt ?? record.published_at)]);
  else rows.push(['Fraîcheur', 'non déclarée']);

  if (record.reviewed_at) rows.push(['Dernière revue', formatDate(record.reviewed_at)]);

  const state = record.status ?? record.lifecycle ?? record.state;
  if (state) rows.push(['Statut', humanize(state)]);
  return rows;
}

function renderSource(source, index) {
  const record = asRecord(source);
  const article = create('article', 'source-card');
  const sourceId = create('p', 'source-id', asText(record.id, `S${index + 1}`));
  const content = create('div', 'source-content');
  const heading = create('div', 'source-heading');
  const title = create('h3', '', asText(record.document ?? record.title, 'Document sans titre'));
  const state = create('span', 'source-state', humanize(record.status ?? record.lifecycle ?? 'métadonnées partielles'));
  heading.append(title, state);

  const metadata = create('dl', 'source-metadata');
  appendDefinitionList(metadata, sourceMetadata(record));

  const quote = create('blockquote', '', asText(record.excerpt ?? record.text, 'Aucun extrait n’a été transmis pour cette source.'));
  content.append(heading, metadata, quote);

  const proof = record.citation ?? record.content_fingerprint ?? record.content_hash ?? record.hash ?? record.chunk_id;
  if (proof) {
    const reference = create('p', 'source-reference', `Référence ${asText(proof)}`);
    content.append(reference);
  }

  article.append(sourceId, content);
  return article;
}

function renderSignals(data, sources) {
  const payload = asRecord(data);
  const retrieval = asRecord(payload.retrieval);
  const target = document.getElementById('signals');
  const decision = payload.decision ?? payload.outcome ?? payload.state ?? (sources.length ? 'réponse sourcée' : 'preuves insuffisantes');
  appendDefinitionList(target, [
    ['Passages cités', plural(sources.length, 'passage')],
    ['Décision', humanize(decision)],
    ['Mode', humanize(payload.generation ?? retrieval.generation ?? 'extractif local')],
  ]);
}

function renderReceipt(data, sources) {
  const payload = asRecord(data);
  const retrieval = asRecord(payload.retrieval);
  const receipt = asRecord(payload.receipt ?? payload.retrieval_receipt ?? payload.trace);
  const timestamp = receipt.retrieved_at ?? receipt.created_at ?? receipt.timestamp ?? receipt.recorded_at ?? payload.created_at;
  const receiptId = receipt.id ?? receipt.request_id ?? payload.request_id;
  const queryFingerprint = receipt.query_fingerprint ?? receipt.query_hash ?? receipt.query_id;
  const evidenceHash = receipt.evidence_hash ?? receipt.result_hash ?? receipt.evidence_fingerprint ?? payload.evidence_hash;
  const candidateCount = retrieval.candidates ?? receipt.candidates ?? receipt.returned ?? receipt.retrieved_passages ?? sources.length;

  appendDefinitionList(document.getElementById('receipt-details'), [
    ['Stratégie', asText(retrieval.strategy ?? receipt.strategy, 'non déclarée')],
    ['Passages', plural(Number(candidateCount) || sources.length, 'retourné', 'retournés')],
    ['Reçu', asText(receiptId, 'non émis')],
    ['Question', asText(queryFingerprint, 'empreinte non émise')],
    ['Empreinte', asText(evidenceHash, 'non émise')],
    ['État', humanize(receipt.state ?? payload.state ?? 'non déclaré')],
    ['Horodatage', formatDate(timestamp)],
  ]);
}

function renderResult(data) {
  const payload = asRecord(data);
  const sources = Array.isArray(payload.sources) ? payload.sources : [];
  const answer = asText(payload.answer, sources.length ? 'Le corpus a retourné des passages à consulter.' : 'Le corpus ne contient pas assez de preuves pour répondre à cette question.');
  const confidence = document.getElementById('confidence');
  const confidenceValue = asText(payload.confidence ?? payload.evidence_level, sources.length ? 'à vérifier' : 'insuffisante');

  document.getElementById('answer').textContent = answer;
  confidence.textContent = `Preuve ${confidenceValue}`;
  confidence.className = `confidence ${confidenceTone(confidenceValue, sources.length)}`;
  renderSignals(payload, sources);
  renderReceipt(payload, sources);

  const sourceRoot = document.getElementById('sources');
  const sourceSummary = document.getElementById('sources-summary');
  sourceRoot.replaceChildren(...sources.map(renderSource));
  sourceSummary.textContent = sources.length
    ? `${plural(sources.length, 'passage')} à comparer avec la réponse`
    : 'Aucun passage probant retourné. Réponse à ne pas utiliser comme décision.';
  result.hidden = false;

  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    result.scrollIntoView({ behavior: 'smooth', block: 'start' });
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

  setFeedback('');
  setBusy(true);
  try {
    const data = await fetchJson('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: value }),
    });
    renderResult(data);
    setFeedback('Recherche terminée. Vérifiez les passages avant de réutiliser la réponse.', 'is-success');
  } catch (error) {
    setFeedback(error instanceof Error ? error.message : 'La recherche a échoué.', 'is-error');
  } finally {
    setBusy(false);
  }
}

form.addEventListener('submit', submitQuestion);

question.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') form.requestSubmit();
});

document.querySelectorAll('[data-question]').forEach(button => {
  button.addEventListener('click', () => {
    question.value = asText(button.dataset.question);
    question.focus();
    setFeedback('Question prête. Lancez la recherche lorsque vous le souhaitez.');
  });
});

refreshStatus();
refreshEvaluation();

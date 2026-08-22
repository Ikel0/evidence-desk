const question = document.getElementById('question');
const result = document.getElementById('result');
const status = document.getElementById('status');

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
}

async function refreshStatus() {
  const response = await fetch('/api/health');
  const data = await response.json();
  status.textContent = `${data.documents} documents indexés · local-first`;
}

function percentage(value) {
  return `${Math.round(Number(value) * 100)}%`;
}

async function refreshEvaluation() {
  const response = await fetch('/api/evaluation');
  const data = await response.json();
  if (!response.ok) {
    document.getElementById('eval-label').textContent = 'Suite indisponible';
    return;
  }
  document.getElementById('eval-score').textContent = `${data.passed}/${data.total}`;
  document.getElementById('eval-label').textContent = 'cas de référence validés';
  document.getElementById('eval-retrieval').textContent = percentage(data.retrieval_recall);
  document.getElementById('eval-grounding').textContent = percentage(data.grounded_answer_rate);
  document.getElementById('eval-citations').textContent = percentage(data.citation_rate);
  document.getElementById('eval-items').innerHTML = data.items.map(item => `<span class="eval-item ${item.passed ? 'pass' : 'fail'}"><i></i>${escapeHtml(item.question)}</span>`).join('');
}

document.getElementById('ask').addEventListener('click', async () => {
  const value = question.value.trim();
  if (!value) return;
  const button = document.getElementById('ask');
  button.disabled = true;
  button.textContent = 'Recherche des preuves…';
  try {
    const response = await fetch('/api/query', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({question:value})});
    const data = await response.json();
    document.getElementById('answer').textContent = data.answer;
    document.getElementById('confidence').textContent = `Confiance ${data.confidence}`;
    document.getElementById('sources').innerHTML = data.sources.map(source => `<article class="source"><b>${escapeHtml(source.id)}</b><div><h2>${escapeHtml(source.document)}</h2><p>${escapeHtml(source.excerpt)}</p><small>version ${escapeHtml(source.version)} · passage ${escapeHtml(source.position)}</small></div></article>`).join('');
    result.hidden = false;
  } finally { button.disabled = false; button.innerHTML = 'Analyser la question <b>↗</b>'; }
});
refreshStatus();
refreshEvaluation();

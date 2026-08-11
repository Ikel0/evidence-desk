const question = document.getElementById('question');
const result = document.getElementById('result');
const status = document.getElementById('status');

async function refreshStatus() {
  const response = await fetch('/api/health');
  const data = await response.json();
  status.textContent = `${data.documents} documents indexés · local-first`;
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
    document.getElementById('sources').innerHTML = data.sources.map(source => `<article class="source"><b>${source.id}</b><div><h2>${source.document}</h2><p>${source.excerpt}</p><small>version ${source.version} · passage ${source.position}</small></div></article>`).join('');
    result.hidden = false;
  } finally { button.disabled = false; button.innerHTML = 'Analyser la question <b>↗</b>'; }
});
refreshStatus();

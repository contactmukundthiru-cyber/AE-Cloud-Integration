const apiKeyInput = document.getElementById('apiKey');
const saveKeyButton = document.getElementById('saveKey');
const jobsBody = document.getElementById('jobsBody');
const activeCount = document.getElementById('activeCount');
const completedCount = document.getElementById('completedCount');
const totalSpend = document.getElementById('totalSpend');

function getApiKey() {
  return localStorage.getItem('cloudexport_api_key') || '';
}

function setApiKey(key) {
  localStorage.setItem('cloudexport_api_key', key);
}

async function fetchHistory() {
  const apiKey = getApiKey();
  if (!apiKey) {
    return;
  }
  const response = await fetch('/jobs/history', {
    headers: { 'X-API-Key': apiKey }
  });
  if (!response.ok) {
    return;
  }
  const data = await response.json();
  renderJobs(data.jobs || []);
}

function renderJobs(jobs) {
  jobsBody.innerHTML = '';
  let active = 0;
  let completed = 0;
  let spend = 0;
  jobs.forEach((job) => {
    if (job.status === 'COMPLETED') {
      completed += 1;
    }
    if (job.status === 'QUEUED' || job.status === 'RENDERING' || job.status === 'DOWNLOADING') {
      active += 1;
    }
    spend += job.costUsd || 0;

    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${job.jobId.slice(0, 8)}...</td>
      <td>${job.status}</td>
      <td>${job.preset}</td>
      <td>${new Date(job.createdAt).toLocaleString()}</td>
      <td>$${job.costUsd.toFixed(2)}</td>
      <td>${job.outputName}</td>
      <td>
        ${job.status === 'COMPLETED' ? '<button class="action-btn" data-id="' + job.jobId + '">Download</button>' : ''}
      </td>
    `;
    jobsBody.appendChild(row);
  });

  activeCount.textContent = active;
  completedCount.textContent = completed;
  totalSpend.textContent = `$${spend.toFixed(2)}`;

  document.querySelectorAll('.action-btn').forEach((button) => {
    button.addEventListener('click', async (event) => {
      const jobId = event.target.getAttribute('data-id');
      await downloadResult(jobId);
    });
  });
}

async function downloadResult(jobId) {
  const apiKey = getApiKey();
  const response = await fetch(`/jobs/result/${jobId}`, {
    headers: { 'X-API-Key': apiKey }
  });
  if (!response.ok) {
    return;
  }
  const data = await response.json();
  window.open(data.downloadUrl, '_blank');
}

saveKeyButton.addEventListener('click', () => {
  const key = apiKeyInput.value.trim();
  if (key) {
    setApiKey(key);
    fetchHistory();
  }
});

apiKeyInput.value = getApiKey();
fetchHistory();
setInterval(fetchHistory, 10000);

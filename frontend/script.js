// ── Config ─────────────────────────────────────────────────────────────────
const API_BASE  = 'http://127.0.0.1:8000';
const STATS_URL = `${API_BASE}/api/stats/`;
const UPLOAD_URL= `${API_BASE}/upload/`;
const POLL_MS   = 1000;
const HISTORY_N = 40;

// ── State ──────────────────────────────────────────────────────────────────
const history = new Array(HISTORY_N).fill(0);
let pollTimer  = null;

// ── DOM refs ───────────────────────────────────────────────────────────────
const $badge       = document.getElementById('live-badge');
const $overlay     = document.getElementById('stream-overlay');
const $videoLabel  = document.getElementById('video-label');
const $frameCount  = document.getElementById('frame-counter');
const $laneA       = document.getElementById('lane-a-count');
const $laneB       = document.getElementById('lane-b-count');
const $signalA     = document.getElementById('signal-a');
const $signalB     = document.getElementById('signal-b');
const $uniqueVal   = document.getElementById('total-unique');
const $barU        = document.getElementById('bar-unique');
const $statusBar   = document.getElementById('status-bar');
const $dropZone    = document.getElementById('drop-zone');
const $uploadBox   = document.getElementById('upload-progress');
const $uploadName  = document.getElementById('upload-filename');
const $uploadPct   = document.getElementById('upload-pct');
const $progressBar = document.getElementById('progress-bar');
const $uploadStat  = document.getElementById('upload-status');
const canvas       = document.getElementById('chart');
const ctx          = canvas.getContext('2d');

// ── Stream events ──────────────────────────────────────────────────────────
function onStreamLoad() {
  $overlay.classList.add('hidden');
  $badge.className  = 'badge badge-live';
  $badge.textContent = '● LIVE';
  setStatus('live', 'Stream connected — receiving live data');
  startPolling();
}

function onStreamError() {
  $badge.className  = 'badge badge-error';
  $badge.textContent = '● OFFLINE';
  setStatus('error', '❌ Cannot reach stream — is the Django server running?');
  setTimeout(() => {
    const img = document.getElementById('stream');
    img.src = `${API_BASE}/stream/?t=${Date.now()}`;
  }, 5000);
}

// ── Stats polling ──────────────────────────────────────────────────────────
function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(fetchStats, POLL_MS);
  fetchStats();
}

async function fetchStats() {
  try {
    const res  = await fetch(STATS_URL, { cache: 'no-store' });
    const data = await res.json();
    updateDashboard(data);
  } catch (_) {}
}

function updateDashboard(data) {
  const cA = data.zone_a_count ?? 0;
  const cB = data.zone_b_count ?? 0;
  const sA = data.signal_a     ?? 'Yellow';
  const sB = data.signal_b     ?? 'Yellow';
  const tu = data.total_unique ?? 0;
  const fr = data.frame        ?? 0;
  const vn = data.video_name   ?? '';

  animateValue($laneA, cA);
  animateValue($laneB, cB);
  animateValue($uniqueVal, tu);

  // Update BADGES explicitly
  $signalA.textContent = sA;
  $signalA.style.background = sA.includes("Green") ? "#0cce6b" : "#ff4f4f";
  
  $signalB.textContent = sB;
  $signalB.style.background = sB.includes("Green") ? "#0cce6b" : "#ff4f4f";

  $frameCount.textContent  = `Frame ${fr.toLocaleString()}`;
  if (vn) $videoLabel.textContent = vn;

  $barU.style.width = `${Math.min(tu / 50, 1) * 100}%`;

  // Plot TOTAL vehicles in chart
  const vc = cA + cB;
  history.push(vc);
  if (history.length > HISTORY_N) history.shift();
  drawChart();
}

// ── Animated counter ───────────────────────────────────────────────────────
function animateValue(el, target) {
  const cur = parseInt(el.dataset.val ?? '0');
  if (cur === target) return;
  el.dataset.val = target;
  const diff = target - cur;
  let step = 0;
  const t = setInterval(() => {
    step++;
    el.textContent = Math.round(cur + diff * (step / 8));
    if (step >= 8) clearInterval(t);
  }, 30);
}

// ── Sparkline chart ────────────────────────────────────────────────────────
function drawChart() {
  const W = canvas.clientWidth, H = canvas.clientHeight;
  canvas.width = W; canvas.height = H;
  const max  = Math.max(...history, 1);
  const step = W / (HISTORY_N - 1);

  const grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, 'rgba(79,156,255,0.35)');
  grad.addColorStop(1, 'rgba(79,156,255,0)');
  ctx.clearRect(0, 0, W, H);

  ctx.beginPath();
  history.forEach((v, i) => {
    const x = i * step, y = H - (v / max) * (H - 10) - 5;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.lineTo((HISTORY_N-1)*step, H); ctx.lineTo(0, H); ctx.closePath();
  ctx.fillStyle = grad; ctx.fill();

  ctx.beginPath();
  history.forEach((v, i) => {
    const x = i * step, y = H - (v / max) * (H - 10) - 5;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.strokeStyle = '#4f9cff'; ctx.lineWidth = 2;
  ctx.lineJoin = 'round'; ctx.stroke();

  const lx = (HISTORY_N-1)*step;
  const ly = H - (history[HISTORY_N-1] / max) * (H-10) - 5;
  ctx.beginPath(); ctx.arc(lx, ly, 4, 0, Math.PI*2);
  ctx.fillStyle = '#4f9cff'; ctx.fill();
}

// ── Drag & Drop ────────────────────────────────────────────────────────────
function onDragOver(e) {
  e.preventDefault();
  $dropZone.classList.add('drag-over');
}
function onDragLeave(e) {
  $dropZone.classList.remove('drag-over');
}
function onDrop(e) {
  e.preventDefault();
  $dropZone.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file);
}

// ── Upload logic ───────────────────────────────────────────────────────────
function uploadFile(file) {
  if (!file) return;

  // Validate: must be a video MIME type
  if (!file.type.startsWith('video/')) {
    showUploadResult('err', '❌ Please select a valid video file.');
    return;
  }

  // Show progress UI
  $uploadBox.classList.remove('hidden');
  $uploadName.textContent = file.name;
  $uploadPct.textContent  = '0%';
  $progressBar.style.width = '0%';
  $uploadStat.className   = 'upload-status';
  $uploadStat.textContent = 'Uploading…';

  const formData = new FormData();
  formData.append('video', file);

  const xhr = new XMLHttpRequest();

  // Progress
  xhr.upload.addEventListener('progress', e => {
    if (e.lengthComputable) {
      const pct = Math.round((e.loaded / e.total) * 100);
      $progressBar.style.width = `${pct}%`;
      $uploadPct.textContent   = `${pct}%`;

      if (pct === 100) {
        $uploadStat.textContent = 'Processing video on server…';
      }
    }
  });

  // Done
  xhr.addEventListener('load', () => {
    if (xhr.status === 200) {
      const data = JSON.parse(xhr.responseText);
      const dur  = (data.frames / data.fps).toFixed(1);
      showUploadResult('ok',
        `✅ Loaded: ${data.filename}  |  ${data.frames.toLocaleString()} frames  |  ${dur}s  |  ${data.width}×${data.height}`
      );
      // Refresh stream to pick up new video
      refreshStream();
    } else {
      let msg = 'Upload failed.';
      try { msg = JSON.parse(xhr.responseText).error || msg; } catch(_) {}
      showUploadResult('err', `❌ ${msg}`);
    }
  });

  xhr.addEventListener('error', () => {
    showUploadResult('err', '❌ Network error — is the Django server running?');
  });

  xhr.open('POST', UPLOAD_URL);
  xhr.send(formData);
}

function showUploadResult(type, msg) {
  $progressBar.style.width = type === 'ok' ? '100%' : $progressBar.style.width;
  $uploadPct.textContent   = type === 'ok' ? '100%' : $uploadPct.textContent;
  $uploadStat.className    = `upload-status ${type}`;
  $uploadStat.textContent  = msg;
}

function refreshStream() {
  const img = document.getElementById('stream');
  $overlay.classList.remove('hidden');
  $badge.className   = 'badge badge-idle';
  $badge.textContent = '● LOADING';
  setTimeout(() => {
    img.src = `${API_BASE}/stream/?t=${Date.now()}`;
  }, 800);  // small delay so server restarts its generator with new video
}

// ── Status bar ─────────────────────────────────────────────────────────────
function setStatus(type, msg) {
  $statusBar.className   = `status-bar status-${type}`;
  $statusBar.textContent = msg;
}

// ── Init ───────────────────────────────────────────────────────────────────
drawChart();
setStatus('idle', 'Connecting to Django server…');
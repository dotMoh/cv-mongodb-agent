const API_BASE = null;

const state = {
  memories: [...(window.MOCK_DATA?.memories || [])],
  currentPlan: null,
  map: null,
  heatLayer: null
};

const $ = (selector) => document.querySelector(selector);

function setModeBadge() {
  const badge = $('#mode-badge');
  if (!badge) return;
  if (API_BASE) {
    badge.textContent = `live: ${API_BASE}`;
    badge.style.background = '#dbeafe';
    badge.style.color = '#1d4ed8';
  } else {
    badge.textContent = 'mock data';
    badge.style.background = '#d1fae5';
    badge.style.color = '#065f46';
  }
}

function getRelevantMemories(plantId) {
  return state.memories.filter((m) => {
    const samePlant = !m.plant_id || m.plant_id === plantId;
    const notCorrected = !m.corrected;
    return samePlant && notCorrected;
  });
}

function getHeatPoints(plantId) {
  const memories = getRelevantMemories(plantId);
  return memories.map((memory) => {
    const coords = memory.location?.coordinates || [0, 0];
    const lat = Number(coords[1]);
    const lng = Number(coords[0]);
    const intensity = Math.min(1, Math.max(0.2, (memory.score || 0.5) * (memory.metadata?.temperature_celsius ? 1 : 0.7)));
    return [lat, lng, intensity];
  });
}

function renderMemoryOptions() {
  const targetSelect = $('#corrects');
  if (!targetSelect) return;

  targetSelect.innerHTML = '<option value="">None, this is a new lesson</option>';
  state.memories.forEach((memory) => {
    const id = memory._id || memory.id;
    const label = `${id} — ${memory.content.slice(0, 60)}${memory.content.length > 60 ? '…' : ''}`;
    const option = document.createElement('option');
    option.value = id;
    option.textContent = label;
    targetSelect.appendChild(option);
  });
}

function renderMemoryList(planMemories) {
  const list = $('#memories');
  if (!list) return;

  const entries = (planMemories || getRelevantMemories($('#plant')?.value || 'unit-3')).slice(0, 3);
  if (!entries.length) {
    list.innerHTML = '<li class="muted">None yet.</li>';
    return;
  }

  list.innerHTML = entries.map((memory) => {
    const score = (memory.score || 0).toFixed(2);
    const status = memory.corrected ? 'corrected' : (memory.metadata?.status || 'active');
    return `
      <li>
        <div>${memory.content}</div>
        <span class="meta">Score: ${score} · ${status}</span>
      </li>
    `;
  }).join('');
}

function makePlan(task, role, plantId) {
  const plant = plantId || 'unit-3';
  const activeWarnings = state.memories.filter((memory) => {
    if (!memory.plant_id || memory.plant_id !== plant) return false;
    if (memory.corrected) return false;
    return (memory.metadata?.temperature_celsius || 0) >= 28;
  });

  const isShifted = activeWarnings.length > 0 && task.toLowerCase().includes('july');

  const schedule = [
    {
      step: 'Reduce power and shut down',
      start: isShifted ? '2027-06-28' : '2027-07-05',
      end: isShifted ? '2027-06-29' : '2027-07-06',
      note: isShifted
        ? 'Moved 1 week earlier to avoid peak intake temperatures (m1)'
        : 'Keep the outage in the July window after cooling checks confirm safe intake temperatures.',
      shifted: isShifted
    },
    {
      step: 'Inspect intake system and verify lockout',
      start: isShifted ? '2027-06-29' : '2027-07-06',
      end: isShifted ? '2027-06-30' : '2027-07-07',
      note: 'Review the latest lessons and plant status before maintenance work begins.',
      shifted: false
    },
    {
      step: 'Complete maintenance and restore load',
      start: isShifted ? '2027-07-10' : '2027-07-12',
      end: isShifted ? '2027-07-12' : '2027-07-14',
      note: role === 'safety_officer' ? 'Confirm safe operating conditions before returning to full load.' : 'Return unit to service once alarms clear and checks pass.',
      shifted: false
    }
  ];

  return {
    summary: `Planned outage for ${plant.toUpperCase()} based on: "${task}"`,
    schedule,
    memories_used: getRelevantMemories(plant).slice(0, 3)
  };
}

function renderSchedule(plan) {
  const scheduleList = $('#schedule');
  const summary = $('#summary');
  if (!scheduleList || !summary) return;

  summary.textContent = plan.summary;
  scheduleList.innerHTML = plan.schedule.map((item) => `
    <li class="${item.shifted ? 'shifted' : ''}">
      <span class="schedule-title">${item.step}</span>
      <span class="schedule-meta">${item.start} → ${item.end}</span>
      <span class="schedule-note">${item.note}</span>
    </li>
  `).join('');
}

function renderHeatMap(plantId) {
  const mapEl = $('#map');
  if (!mapEl) return;

  if (!state.map) {
    state.map = L.map('map', { zoomControl: true, scrollWheelZoom: true }).setView([43.81, -79.07], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(state.map);
  }

  if (state.heatLayer) {
    state.map.removeLayer(state.heatLayer);
  }

  const points = getHeatPoints(plantId);
  state.heatLayer = L.heatLayer(points, {
    radius: 20,
    blur: 18,
    maxZoom: 12,
    minOpacity: 0.5,
    gradient: { 0.2: '#fef3c7', 0.5: '#f59e0b', 0.8: '#ef4444', 1: '#7f1d1d' }
  }).addTo(state.map);
}

function planCurrent() {
  const task = $('#task')?.value || 'Plan July maintenance outage for Unit 3';
  const role = $('#role')?.value || 'planner';
  const plant = $('#plant')?.value || 'unit-3';
  const plan = makePlan(task, role, plant);
  state.currentPlan = plan;
  renderSchedule(plan);
  renderMemoryList(plan.memories_used);
  renderHeatMap(plant);
}

function handlePlanSubmit(event) {
  event.preventDefault();
  const task = $('#task')?.value.trim();
  if (!task) return;
  planCurrent();
}

function handleLearnSubmit(event) {
  event.preventDefault();
  const lesson = $('#lesson')?.value.trim();
  const plant = $('#plant')?.value || 'unit-3';
  const correctsId = $('#corrects')?.value || '';

  if (!lesson) {
    $('#learn-status').textContent = 'Please enter a lesson or correction first.';
    return;
  }

  const newMemory = {
    _id: `m${Date.now()}`,
    content: lesson,
    score: 0.91,
    plant_id: plant,
    location: { type: 'Point', coordinates: [-79.07, 43.81] },
    metadata: { status: 'active', temperature_celsius: lesson.toLowerCase().includes('safe') ? 24 : 30, plant_id: plant }
  };

  if (correctsId) {
    const original = state.memories.find((memory) => (memory._id || memory.id) === correctsId);
    if (original) {
      original.corrected = true;
      original.metadata = { ...(original.metadata || {}), status: 'corrected' };
    }
  }

  state.memories.unshift(newMemory);
  renderMemoryOptions();
  $('#learn-status').textContent = 'Saved to memory. Re-planning…';
  setTimeout(() => {
    planCurrent();
    $('#learn-status').textContent = 'Saved to memory.';
  }, 200);
}

function init() {
  setModeBadge();
  renderMemoryOptions();
  planCurrent();

  $('#plan-form')?.addEventListener('submit', handlePlanSubmit);
  $('#learn-form')?.addEventListener('submit', handleLearnSubmit);
  $('#plant')?.addEventListener('change', planCurrent);
  $('#task')?.addEventListener('input', planCurrent);
  $('#role')?.addEventListener('change', planCurrent);
}

document.addEventListener('DOMContentLoaded', init);

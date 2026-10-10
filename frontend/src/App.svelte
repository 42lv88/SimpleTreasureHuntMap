<script>
  import { onMount, onDestroy } from 'svelte';
  import L from 'leaflet';

  // ── State ────────────────────────────────────────────────────────────
  let map, playerMarker, accuracyCircle;
  let questMarkers = [];
  let questLines   = [];

  let phase = 'gps';  // gps | loading | questing | detail | camera | verifying | result | victory
  let quests  = [];   // [{id, lat, lng, street, riddle, nominalDist}]
  let statuses = {};  // { 0: null|'found'|'wrong', 1: ..., 2: ... }
  let distances = {}; // { 0: metres, 1: ..., 2: ... } — live

  let currentPos = null;
  let gpsError   = '';
  let watcher;

  // Active quest flow
  let activeId = null;
  $: activeQuest = quests.find(q => q.id === activeId);

  // Upload / camera
  let fileInput;
  let photoFile = null;
  let photoPreviewUrl = '';

  // Verification
  let verifying = false;
  let verifyResult = null;  // {matched, ocr_text, street, confidence}

  // Computed
  $: score   = Object.values(statuses).filter(s => s === 'found').length;
  $: victory = score === 3;

  // ── Lifecycle ────────────────────────────────────────────────────────
  onMount(() => {
    map = L.map('map', { zoomControl: false, attributionControl: true })
           .setView([20, 78], 4);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
      className: 'dark-tiles',
    }).addTo(map);

    L.control.zoom({ position: 'bottomright' }).addTo(map);
    startGPS();
  });

  onDestroy(() => {
    if (watcher) navigator.geolocation.clearWatch(watcher);
  });

  // ── GPS ──────────────────────────────────────────────────────────────
  function startGPS() {
    if (!('geolocation' in navigator)) { gpsError = 'Geolocation not supported.'; return; }
    watcher = navigator.geolocation.watchPosition(onGPS, e => { gpsError = e.message; },
      { enableHighAccuracy: true, maximumAge: 0 });
  }

  let questsLoaded = false;
  function onGPS(pos) {
    gpsError = '';
    currentPos = L.latLng(pos.coords.latitude, pos.coords.longitude);
    const acc = pos.coords.accuracy;

    if (!playerMarker) {
      playerMarker = L.marker(currentPos, { icon: playerIcon() }).addTo(map);
      map.setView(currentPos, 16);
    } else {
      playerMarker.setLatLng(currentPos);
    }

    if (accuracyCircle) accuracyCircle.setLatLng(currentPos).setRadius(acc);
    else accuracyCircle = L.circle(currentPos, { radius: acc, color: '#3d7dca', fillColor: '#3d7dca', fillOpacity: 0.08, weight: 1 }).addTo(map);

    // Update live distances
    quests.forEach(q => {
      distances[q.id] = Math.round(currentPos.distanceTo(L.latLng(q.lat, q.lng)));
    });
    distances = { ...distances };

    // Update dashed lines
    updateLines();

    // Load quests once on first GPS fix
    if (!questsLoaded && phase === 'gps') {
      questsLoaded = true;
      loadQuests(pos.coords.latitude, pos.coords.longitude);
    }
  }

  // ── Load Quests ──────────────────────────────────────────────────────
  async function loadQuests(lat, lng) {
    phase = 'loading';
    try {
      const apiBase = (import.meta.env.VITE_BACKEND_URL || '').replace(/\/$/, '');
      const url = apiBase ? `${apiBase}/api/generate-quests` : '/api/generate-quests';
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lat, lng }),
      });
      const data = await r.json();
      quests = data.quests;
      quests.forEach(q => {
        statuses[q.id] = null;
        distances[q.id] = currentPos
          ? Math.round(currentPos.distanceTo(L.latLng(q.lat, q.lng)))
          : q.nominalDist;
      });
      statuses  = { ...statuses };
      distances = { ...distances };
      placeQuestMarkers();
      if (currentPos) map.setView(currentPos, 15);
      phase = 'questing';
    } catch (e) {
      gpsError = 'Failed to load quests. Check API.';
      phase = 'gps';
      questsLoaded = false;
    }
  }

  // ── Map: Markers & Lines ─────────────────────────────────────────────
  function playerIcon() {
    return L.divIcon({
      className: '',
      html: `<div class="player-dot"><div class="player-pulse"></div><div class="player-inner">🧙</div></div>`,
      iconSize: [48, 48], iconAnchor: [24, 24],
    });
  }

  function questIcon(id, status) {
    const labels  = ['Ⅰ', 'Ⅱ', 'Ⅲ'];
    const colors  = { found: '#00e676', wrong: '#ff4444', null: '#aaa' };
    const symbols = { found: '✅', wrong: '❌', null: labels[id] };
    const color   = colors[status ?? 'null'];
    const symbol  = symbols[status ?? 'null'];
    return L.divIcon({
      className: '',
      html: `<div class="quest-pin" style="border-color:${color};box-shadow:0 0 12px ${color}80">${symbol}</div>`,
      iconSize: [44, 44], iconAnchor: [22, 44],
    });
  }

  function placeQuestMarkers() {
    questMarkers.forEach(m => map.removeLayer(m));
    questMarkers = [];
    quests.forEach(q => {
      const m = L.marker([q.lat, q.lng], { icon: questIcon(q.id, statuses[q.id]) }).addTo(map);
      m.bindPopup(`<b>Quest ${q.id + 1}</b><br/>${statuses[q.id] === 'found' ? '✅ Found!' : statuses[q.id] === 'wrong' ? '❌ Wrong' : '❓ Unsolved'}`);
      questMarkers.push(m);
    });
  }

  function refreshMarker(id) {
    if (questMarkers[id]) {
      questMarkers[id].setIcon(questIcon(id, statuses[id]));
      questMarkers[id].setPopupContent(`<b>Quest ${id + 1}</b><br/>${statuses[id] === 'found' ? '✅ Found!' : '❌ Wrong'}`);
    }
  }

  function updateLines() {
    questLines.forEach(l => map.removeLayer(l));
    questLines = [];
    if (!currentPos) return;
    quests.forEach(q => {
      if (statuses[q.id]) return; // skip settled quests
      const color = '#ffcb0570';
      const l = L.polyline([currentPos, [q.lat, q.lng]], { color: '#ffcb05', weight: 1.5, dashArray: '5 8', opacity: 0.5 }).addTo(map);
      questLines.push(l);
    });
  }

  // ── Quest Detail / Camera ────────────────────────────────────────────
  function openQuest(id) {
    activeId = id;
    photoFile = null;
    photoPreviewUrl = '';
    verifyResult = null;
    phase = 'detail';
  }

  function onFileSelected(e) {
    const f = e.target.files[0];
    if (!f) return;
    photoFile = f;
    photoPreviewUrl = URL.createObjectURL(f);
  }

  function triggerFileInput(capture) {
    if (capture) fileInput.setAttribute('capture', 'environment');
    else fileInput.removeAttribute('capture');
    fileInput.click();
  }

  async function verifySign() {
    if (!photoFile || !activeQuest) return;
    verifying = true;
    phase = 'verifying';
    try {
      const apiBase = (import.meta.env.VITE_BACKEND_URL || '').replace(/\/$/, '');
      const url = apiBase ? `${apiBase}/api/verify-sign` : '/api/verify-sign';
      const fd = new FormData();
      fd.append('file', photoFile);
      fd.append('street', activeQuest.street);
      const r = await fetch(url, { method: 'POST', body: fd });
      verifyResult = await r.json();
      statuses[activeId] = verifyResult.matched ? 'found' : 'wrong';
      statuses = { ...statuses };
      refreshMarker(activeId);
      updateLines();
      if (victory) { setTimeout(() => { phase = 'victory'; }, 1200); }
      else phase = 'result';
    } catch {
      verifyResult = { matched: false, ocr_text: 'Network error — check connection.', street: activeQuest.street, confidence: 0 };
      statuses[activeId] = 'wrong';
      statuses = { ...statuses };
      refreshMarker(activeId);
      phase = 'result';
    } finally {
      verifying = false;
    }
  }

  function backToMap() {
    phase = 'questing';
    activeId = null;
    photoFile = null;
    photoPreviewUrl = '';
    verifyResult = null;
  }

  function retryQuest(id) {
    statuses[id] = null;
    statuses = { ...statuses };
    refreshMarker(id);
    updateLines();
    openQuest(id);
  }

  function newHunt() {
    quests = [];
    statuses = {};
    distances = {};
    questsLoaded = false;
    placeQuestMarkers();
    phase = 'gps';
    if (currentPos) loadQuests(currentPos.lat, currentPos.lng);
  }

  // ── Helpers ──────────────────────────────────────────────────────────
  const QUEST_COLORS = ['#ffcb05', '#3d7dca', '#cc0000'];
  const QUEST_NAMES  = ['Quest Ⅰ', 'Quest Ⅱ', 'Quest Ⅲ'];
  const QUEST_EMOJIS = ['📜', '🗺️', '🏰'];

  function distColor(d) {
    if (d < 50)  return '#00e676';
    if (d < 150) return '#ffcb05';
    return '#ff6b6b';
  }
  function distLabel(d) {
    if (d < 50)  return '🔥 Very Close!';
    if (d < 150) return '🌡️ Getting Warm';
    return `🧭 ${d}m Away`;
  }
  function statusBadge(s) {
    if (s === 'found') return '✅ Found';
    if (s === 'wrong') return '❌ Wrong';
    return '❓ Unsolved';
  }
</script>

<!-- ═══ MARKUP ═══════════════════════════════════════════════════════════ -->
<div class="root">
  <!-- Full-screen map always beneath -->
  <div id="map"></div>

  <!-- Hidden file input for photo capture / gallery -->
  <input bind:this={fileInput} type="file" accept="image/*" style="display:none"
    on:change={onFileSelected} />

  <!-- ── GPS waiting ── -->
  {#if phase === 'gps'}
  <div class="overlay center">
    <div class="splash-card">
      <div class="spin-icon">🗺️</div>
      <h1 class="title-glow">Street Hunt</h1>
      <p class="sub">Acquiring your wizarding coordinates…</p>
      {#if gpsError}<p class="err">⚠️ {gpsError}</p>{/if}
    </div>
  </div>
  {/if}

  <!-- ── Loading quests ── -->
  {#if phase === 'loading'}
  <div class="overlay center">
    <div class="splash-card">
      <div class="spin-icon">📜</div>
      <h2 class="title-glow" style="font-size:1.5rem">Consulting the Marauder's Map…</h2>
      <p class="sub">Gemini is conjuring 3 mystical quests…</p>
    </div>
  </div>
  {/if}

  <!-- ── Main game screen ── -->
  {#if phase === 'questing'}
  <!-- HUD -->
  <div class="hud-top">
    <div class="hud-logo">⚡ Street Hunt</div>
    <div class="hud-score" class:all-found={score === 3}>
      {score}/3 <span class="score-label">Found</span>
    </div>
  </div>

  <!-- Bottom quest cards row -->
  <div class="quest-row">
    {#each quests as q}
    {@const st = statuses[q.id]}
    {@const dist = distances[q.id] ?? q.nominalDist}
    <div
      class="quest-card"
      class:status-found={st === 'found'}
      class:status-wrong={st === 'wrong'}
      on:click={() => openQuest(q.id)}
      role="button"
      tabindex="0"
      on:keydown={e => e.key === 'Enter' && openQuest(q.id)}
      style="--qcolor:{QUEST_COLORS[q.id]}"
    >
      <div class="qcard-top">
        <span class="qcard-emoji">{QUEST_EMOJIS[q.id]}</span>
        <span class="qcard-name">{QUEST_NAMES[q.id]}</span>
        <span class="qcard-status">{statusBadge(st)}</span>
      </div>
      <div class="qcard-dist" style="color:{distColor(dist)}">{distLabel(dist)}</div>
      <p class="qcard-riddle-preview">{q.riddle.slice(0, 80)}…</p>
    </div>
    {/each}
  </div>
  {/if}

  <!-- ── Quest Detail ── -->
  {#if phase === 'detail' && activeQuest}
  {@const dist = distances[activeId] ?? activeQuest.nominalDist}
  <div class="overlay slide-up">
    <div class="detail-card">
      <!-- Header -->
      <div class="detail-header" style="border-color:{QUEST_COLORS[activeId]}">
        <button class="back-btn" on:click={backToMap}>← Map</button>
        <div class="detail-title">
          <span>{QUEST_EMOJIS[activeId]}</span>
          <span>{QUEST_NAMES[activeId]}</span>
        </div>
        <div class="dist-badge" style="color:{distColor(dist)};border-color:{distColor(dist)}">
          <span class="dist-num">{dist}</span><span class="dist-unit">m</span>
        </div>
      </div>

      <!-- Marauder's Map riddle scroll -->
      <div class="parchment-card">
        <div class="parchment-header">
          <span>📜</span>
          <span>The Marauder's Clue · Gemini Flash</span>
        </div>
        <p class="parchment-text">{activeQuest.riddle}</p>
      </div>

      <!-- Retake or wrong info if already attempted -->
      {#if statuses[activeId] === 'wrong'}
      <div class="attempt-note wrong">
        ❌ Previous attempt incorrect — try a different sign!
      </div>
      {/if}

      <!-- Photo section -->
      {#if !photoPreviewUrl}
      <div class="upload-actions">
        <button class="btn-camera" on:click={() => triggerFileInput(true)}>
          📷 Take Photo
        </button>
        <button class="btn-gallery" on:click={() => triggerFileInput(false)}>
          🖼️ Upload from Gallery
        </button>
      </div>
      {:else}
      <div class="photo-preview-wrap">
        <img src={photoPreviewUrl} alt="Street sign photo" class="preview-img" />
        <div class="preview-actions">
          <button class="btn-retake" on:click={() => { photoFile = null; photoPreviewUrl = ''; }}>
            ↺ Retake
          </button>
          <button class="btn-verify" on:click={verifySign}>
            ✨ Verify Sign
          </button>
        </div>
      </div>
      {/if}
    </div>
  </div>
  {/if}

  <!-- ── Verifying ── -->
  {#if phase === 'verifying'}
  <div class="overlay center">
    <div class="splash-card">
      <div class="spin-icon">🔮</div>
      <h2 class="title-glow" style="font-size:1.3rem">The Marauder's Map is reading the sign…</h2>
      <p class="sub">Gemini Vision OCR at work ✨</p>
    </div>
  </div>
  {/if}

  <!-- ── OCR Result ── -->
  {#if phase === 'result' && verifyResult && activeQuest}
  <div class="overlay center">
    <div class="result-card" class:result-found={verifyResult.matched} class:result-wrong={!verifyResult.matched}>

      <div class="result-big-icon">{verifyResult.matched ? '🎉' : '❌'}</div>
      <h2 class="result-title">{verifyResult.matched ? 'Quest Complete!' : 'Not Quite Right…'}</h2>

      <div class="ocr-box">
        <div class="ocr-label">📸 Sign OCR Read:</div>
        <div class="ocr-text">"{verifyResult.ocr_text}"</div>
        {#if verifyResult.matched}
        <div class="ocr-label" style="margin-top:0.4rem">🎯 Matched: {activeQuest.street}</div>
        {/if}
        <div class="ocr-conf">Confidence: {Math.round(verifyResult.confidence * 100)}%</div>
      </div>

      {#if verifyResult.matched}
      <p class="result-sub">
        ⚡ "{activeQuest.street}" is marked on the Marauder's Map! {score}/3 quests done.
      </p>
      <button class="cta-btn green" on:click={backToMap}>← Back to Map</button>
      {:else}
      <p class="result-sub">
        The enchanted map sees "{verifyResult.ocr_text}" — look for a different sign!
      </p>
      <div class="result-actions">
        <button class="cta-btn red" on:click={() => retryQuest(activeId)}>🔁 Retry Quest</button>
        <button class="cta-btn outline" on:click={backToMap}>← Map</button>
      </div>
      {/if}
    </div>
  </div>
  {/if}

  <!-- ── Victory ── -->
  {#if phase === 'victory'}
  <div class="overlay center victory-bg">
    <div class="victory-card">
      <div class="trophy-bounce">🏆</div>
      <h1 class="victory-title">All Quests Complete!</h1>
      <p class="victory-sub">You've mastered the Marauder's Map and claimed all three streets!</p>

      <div class="quest-summary">
        {#each quests as q}
        <div class="summary-row">
          <span>{QUEST_EMOJIS[q.id]} {QUEST_NAMES[q.id]}</span>
          <span style="color:#ffcb05;font-weight:700">{q.street}</span>
          <span>{statuses[q.id] === 'found' ? '✅' : '❌'}</span>
        </div>
        {/each}
      </div>

      <button class="cta-btn" style="width:100%;margin-top:1.2rem" on:click={newHunt}>
        🗺️ Start New Hunt
      </button>
    </div>
  </div>
  {/if}
</div>

<!-- ═══ STYLES ══════════════════════════════════════════════════════════ -->
<style>
  /* ── Layout ── */
  .root { position: fixed; inset: 0; display: flex; flex-direction: column; }
  :global(#map) { position: absolute; inset: 0; z-index: 0; }

  /* ── Overlays ── */
  .overlay {
    position: fixed; inset: 0; z-index: 300;
    background: rgba(8,10,22,0.88);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
  }
  .center { display: flex; align-items: center; justify-content: center; padding: 1.5rem; }
  .slide-up { overflow-y: auto; padding: 1rem; }
  .victory-bg { background: linear-gradient(160deg, rgba(0,0,0,0.92) 0%, rgba(20,40,90,0.92) 100%); }

  /* ── Splash card ── */
  .splash-card {
    display: flex; flex-direction: column; align-items: center; gap: 0.8rem;
    text-align: center;
  }
  .spin-icon { font-size: 3.5rem; animation: spin 2s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .title-glow {
    font-size: 2rem; font-weight: 900;
    color: #ffcb05; letter-spacing: 2px;
    text-shadow: 0 0 20px #ffcb0570;
  }
  .sub  { color: rgba(255,255,255,0.65); font-size: 0.9rem; }
  .err  { color: #ff6b6b; font-size: 0.85rem; }

  /* ── HUD ── */
  .hud-top {
    position: absolute; top: 0; left: 0; right: 0; z-index: 200;
    display: flex; align-items: center; justify-content: space-between;
    padding: 0.6rem 1rem;
    background: linear-gradient(to bottom, rgba(8,10,22,0.9), transparent);
    pointer-events: none;
  }
  .hud-logo { font-size: 0.9rem; font-weight: 900; color: #ffcb05; text-shadow: 0 0 10px #ffcb0550; letter-spacing: 1px; }
  .hud-score {
    font-size: 1rem; font-weight: 900; color: #aaa;
    display: flex; align-items: baseline; gap: 0.3rem;
  }
  .hud-score.all-found { color: #00e676; text-shadow: 0 0 10px #00e67660; }
  .score-label { font-size: 0.7rem; font-weight: 600; opacity: 0.8; }

  /* ── Quest cards row ── */
  .quest-row {
    position: absolute; bottom: 0; left: 0; right: 0; z-index: 200;
    display: flex; gap: 0.75rem; overflow-x: auto; padding: 1rem;
    padding-bottom: max(1rem, env(safe-area-inset-bottom));
    scroll-snap-type: x mandatory;
    -webkit-overflow-scrolling: touch;
    background: linear-gradient(to top, rgba(8,10,22,0.95) 60%, transparent);
  }
  .quest-row::-webkit-scrollbar { display: none; }

  .quest-card {
    flex: 0 0 260px;
    scroll-snap-align: start;
    background: rgba(255,255,255,0.05);
    border: 1.5px solid var(--qcolor, #ffcb05);
    border-radius: 18px;
    padding: 0.85rem 1rem;
    cursor: pointer;
    transition: transform 0.15s, box-shadow 0.15s;
    box-shadow: 0 0 15px rgba(0,0,0,0.4);
  }
  .quest-card:active { transform: scale(0.97); }
  .quest-card.status-found { border-color: #00e676; background: rgba(0,230,118,0.07); }
  .quest-card.status-wrong { border-color: #ff4444; background: rgba(255,68,68,0.07); }

  .qcard-top { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.4rem; }
  .qcard-emoji { font-size: 1rem; }
  .qcard-name  { font-size: 0.75rem; font-weight: 900; letter-spacing: 1px; color: #ffcb05; flex: 1; }
  .qcard-status { font-size: 0.65rem; font-weight: 700; color: rgba(255,255,255,0.6); }
  .qcard-dist  { font-size: 0.75rem; font-weight: 700; margin-bottom: 0.4rem; }
  .qcard-riddle-preview { font-size: 0.75rem; color: rgba(255,255,255,0.7); font-style: italic; line-height: 1.4; margin: 0; }

  /* ── Detail card ── */
  .detail-card {
    background: rgba(10,12,26,0.97);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 24px;
    padding: 1rem;
    display: flex; flex-direction: column; gap: 1rem;
    max-width: 480px; margin: 0 auto;
    min-height: 60vh;
  }
  .detail-header {
    display: flex; align-items: center; gap: 0.75rem;
    padding-bottom: 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.1);
  }
  .back-btn {
    background: transparent; border: 1px solid rgba(255,255,255,0.25);
    color: rgba(255,255,255,0.8); border-radius: 50px; padding: 0.3rem 0.75rem;
    font-size: 0.75rem; font-weight: 700; cursor: pointer;
  }
  .detail-title {
    flex: 1; display: flex; align-items: center; gap: 0.4rem;
    font-size: 1rem; font-weight: 900; color: #ffcb05; letter-spacing: 1px;
  }
  .dist-badge {
    border: 2px solid; border-radius: 50px; padding: 0.2rem 0.65rem;
    display: flex; align-items: baseline; gap: 2px;
  }
  .dist-num { font-size: 1.2rem; font-weight: 900; line-height: 1; }
  .dist-unit { font-size: 0.65rem; opacity: 0.75; }

  /* ── Parchment riddle card ── */
  .parchment-card {
    background: linear-gradient(135deg, rgba(120, 80, 10, 0.25) 0%, rgba(60, 30, 0, 0.35) 100%);
    border: 1px solid rgba(255,203,5,0.35);
    border-radius: 16px; padding: 1rem;
  }
  .parchment-header {
    display: flex; align-items: center; gap: 0.4rem;
    font-size: 0.65rem; font-weight: 900; letter-spacing: 1.5px;
    text-transform: uppercase; color: #ffcb05; margin-bottom: 0.7rem;
  }
  .parchment-text {
    font-size: 0.9rem; line-height: 1.7; color: rgba(255,240,200,0.92);
    font-style: italic; white-space: pre-wrap; margin: 0;
  }

  /* ── Attempt note ── */
  .attempt-note {
    border-radius: 10px; padding: 0.6rem 0.9rem;
    font-size: 0.8rem; font-weight: 700;
  }
  .attempt-note.wrong { background: rgba(255,68,68,0.12); border: 1px solid rgba(255,68,68,0.35); color: #ff9999; }

  /* ── Upload actions ── */
  .upload-actions { display: flex; flex-direction: column; gap: 0.75rem; }
  .btn-camera {
    padding: 1rem; background: linear-gradient(135deg, #cc0000, #ff4444);
    border: none; border-radius: 50px; color: white;
    font-family: 'Exo 2', sans-serif; font-size: 1rem; font-weight: 700;
    cursor: pointer; box-shadow: 0 4px 20px rgba(204,0,0,0.4);
    letter-spacing: 0.5px; text-transform: uppercase;
  }
  .btn-gallery {
    padding: 0.85rem; background: rgba(255,255,255,0.07);
    border: 1.5px solid rgba(255,255,255,0.25); border-radius: 50px;
    color: rgba(255,255,255,0.85); font-family: 'Exo 2', sans-serif;
    font-size: 0.95rem; font-weight: 700; cursor: pointer; letter-spacing: 0.5px;
    text-transform: uppercase;
  }

  /* ── Photo preview ── */
  .photo-preview-wrap { display: flex; flex-direction: column; gap: 0.75rem; }
  .preview-img { width: 100%; max-height: 220px; object-fit: cover; border-radius: 14px; border: 1px solid rgba(255,255,255,0.15); }
  .preview-actions { display: flex; gap: 0.75rem; }
  .btn-retake {
    flex: 1; padding: 0.75rem; border-radius: 50px;
    background: transparent; border: 2px solid rgba(255,255,255,0.25);
    color: white; font-family: 'Exo 2', sans-serif; font-size: 0.9rem; font-weight: 700;
    cursor: pointer;
  }
  .btn-verify {
    flex: 2; padding: 0.75rem; border-radius: 50px;
    background: linear-gradient(135deg, #1a5c2e, #00c853);
    border: none; color: white; font-family: 'Exo 2', sans-serif;
    font-size: 0.9rem; font-weight: 700; cursor: pointer;
    box-shadow: 0 4px 15px rgba(0,200,83,0.4); letter-spacing: 0.5px;
    text-transform: uppercase;
  }

  /* ── Result card ── */
  .result-card {
    background: rgba(10,12,26,0.98);
    border: 2px solid rgba(255,255,255,0.1);
    border-radius: 24px; padding: 1.75rem 1.5rem;
    width: 100%; max-width: 420px;
    display: flex; flex-direction: column; align-items: center; gap: 1rem;
    text-align: center;
  }
  .result-card.result-found { border-color: rgba(0,230,118,0.5); box-shadow: 0 0 30px rgba(0,230,118,0.15); }
  .result-card.result-wrong { border-color: rgba(255,68,68,0.5); box-shadow: 0 0 30px rgba(255,68,68,0.15); }
  .result-big-icon { font-size: 4rem; animation: pop 0.4s ease; }
  @keyframes pop { 0% { transform: scale(0); } 80% { transform: scale(1.15); } 100% { transform: scale(1); } }
  .result-title { font-size: 1.6rem; font-weight: 900; color: #ffcb05; margin: 0; }
  .ocr-box {
    background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12);
    border-radius: 12px; padding: 0.85rem 1rem; width: 100%; text-align: left;
  }
  .ocr-label { font-size: 0.65rem; font-weight: 900; letter-spacing: 1px; color: #aaa; text-transform: uppercase; }
  .ocr-text  { font-size: 0.9rem; font-weight: 700; color: white; margin-top: 0.3rem; font-style: italic; }
  .ocr-conf  { font-size: 0.65rem; color: rgba(255,255,255,0.45); margin-top: 0.4rem; }
  .result-sub { font-size: 0.8rem; color: rgba(255,255,255,0.65); margin: 0; }
  .result-actions { display: flex; gap: 0.75rem; width: 100%; }

  /* ── CTAs ── */
  .cta-btn {
    padding: 0.9rem 1.5rem; border-radius: 50px; border: none;
    font-family: 'Exo 2', sans-serif; font-size: 0.95rem; font-weight: 700;
    letter-spacing: 0.5px; text-transform: uppercase; cursor: pointer;
    flex: 1;
    background: linear-gradient(135deg, #cc0000, #ff4444);
    color: white; box-shadow: 0 4px 18px rgba(204,0,0,0.4);
    transition: transform 0.1s; width: auto;
  }
  .cta-btn:active { transform: scale(0.97); }
  .cta-btn.green { background: linear-gradient(135deg, #1a5c2e, #00c853); box-shadow: 0 4px 18px rgba(0,200,83,0.4); }
  .cta-btn.red   { background: linear-gradient(135deg, #8b0000, #cc0000); box-shadow: 0 4px 18px rgba(204,0,0,0.4); }
  .cta-btn.outline { background: transparent; border: 2px solid rgba(255,255,255,0.3); color: white; box-shadow: none; }

  /* ── Victory ── */
  .victory-card {
    background: linear-gradient(160deg, rgba(15,25,55,0.98), rgba(8,10,20,0.98));
    border: 1px solid rgba(255,203,5,0.4);
    border-radius: 28px; padding: 2rem 1.5rem;
    width: 100%; max-width: 430px; text-align: center;
    display: flex; flex-direction: column; align-items: center; gap: 0.9rem;
    box-shadow: 0 0 50px rgba(255,203,5,0.15);
    max-height: 90vh; overflow-y: auto;
  }
  .trophy-bounce { font-size: 5rem; animation: bounce 0.8s ease-in-out infinite alternate; }
  @keyframes bounce { to { transform: translateY(-12px); } }
  .victory-title { font-size: 1.8rem; font-weight: 900; color: #ffcb05; text-shadow: 0 0 20px #ffcb0560; margin: 0; }
  .victory-sub { font-size: 0.85rem; color: rgba(255,255,255,0.6); margin: 0; }
  .quest-summary { width: 100%; display: flex; flex-direction: column; gap: 0.5rem; }
  .summary-row {
    display: flex; align-items: center; justify-content: space-between;
    background: rgba(255,255,255,0.05); border-radius: 10px;
    padding: 0.5rem 0.8rem; font-size: 0.8rem;
  }

  /* ── Map markers ── */
  :global(.player-dot) {
    width: 48px; height: 48px; display: flex; align-items: center; justify-content: center;
    position: relative;
  }
  :global(.player-pulse) {
    position: absolute; inset: 0; border-radius: 50%;
    background: rgba(61,125,202,0.4); animation: pulse 2s ease-out infinite;
  }
  :global(.player-inner) { font-size: 1.6rem; z-index: 1; position: relative; }
  @keyframes pulse { 0% { transform: scale(0.8); opacity: 0.8; } 70% { transform: scale(2); opacity: 0; } 100% { transform: scale(0.8); opacity: 0; } }
  :global(.quest-pin) {
    width: 44px; height: 44px; border-radius: 50% 50% 50% 0;
    border: 2.5px solid;
    background: rgba(10,12,26,0.9); display: flex; align-items: center; justify-content: center;
    font-size: 1.1rem; transform: rotate(-45deg);
    box-shadow: 0 2px 8px rgba(0,0,0,0.5);
  }
  :global(.quest-pin > *), :global(.quest-pin)::after { transform: rotate(45deg); }
</style>

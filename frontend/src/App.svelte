<script>
  import { onMount, onDestroy } from 'svelte';
  import L from 'leaflet';

  /* ─── State ─────────────────────────────────────── */
  let map, playerMarker, targetMarker, accuracyCircle, line;
  let currentPos   = null;   // L.LatLng
  let targetPos    = null;   // L.LatLng
  let streetName   = '';
  let distance     = 0;
  let riddle       = '';
  let phase        = 'gps';  // gps | hunting | camera | captured | solved
  let loadingRiddle = false;
  let gpsError     = '';
  let watcher;

  /* Camera */
  let videoEl, canvasEl;
  let photoUrl = '';
  let cameraStream;

  /* ─── Lifecycle ──────────────────────────────────── */
  onMount(() => {
    map = L.map('map', { zoomControl: false, attributionControl: true })
           .setView([20, 78], 4);

    // OSM tiles are free with no API key — dark filter applied via CSS class below
    L.tileLayer(
      'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
        className: 'dark-tiles'   // CSS class applies the dark invert filter
      }
    ).addTo(map);

    // Zoom control bottom-right
    L.control.zoom({ position: 'bottomright' }).addTo(map);

    startGPS();
  });

  onDestroy(() => {
    if (watcher) navigator.geolocation.clearWatch(watcher);
    stopCamera();
  });

  /* ─── GPS ────────────────────────────────────────── */
  function startGPS() {
    if (!('geolocation' in navigator)) {
      gpsError = 'Geolocation not supported by this browser.';
      return;
    }
    watcher = navigator.geolocation.watchPosition(
      onGPS,
      (e) => { gpsError = e.message; },
      { enableHighAccuracy: true, maximumAge: 0 }
    );
  }

  function onGPS(pos) {
    gpsError = '';
    const lat = pos.coords.latitude;
    const lng = pos.coords.longitude;
    const acc = pos.coords.accuracy;
    currentPos = L.latLng(lat, lng);

    // Player marker
    if (!playerMarker) {
      playerMarker = L.marker(currentPos, { icon: playerIcon() }).addTo(map);
      map.setView(currentPos, 17);
      if (phase === 'gps') {
        phase = 'loading';
        spawnTarget(lat, lng);
      }
    } else {
      playerMarker.setLatLng(currentPos);
    }

    // Accuracy ring
    if (accuracyCircle) accuracyCircle.setLatLng(currentPos).setRadius(acc);
    else accuracyCircle = L.circle(currentPos, { radius: acc, color: '#3d7dca', fillColor: '#3d7dca', fillOpacity: 0.08, weight: 1 }).addTo(map);

    if (targetPos) {
      distance = Math.round(currentPos.distanceTo(targetPos));
      if (line) line.setLatLngs([currentPos, targetPos]);
    }
  }

  function playerIcon() {
    return L.divIcon({
      className: '',
      html: `
        <div class="player-dot">
          <div class="player-pulse"></div>
          <div class="player-inner">🧍</div>
        </div>`,
      iconSize: [48, 48],
      iconAnchor: [24, 24],
    });
  }

  function targetIcon() {
    return L.divIcon({
      className: '',
      html: `<div class="target-pin">📍</div>`,
      iconSize: [40, 40],
      iconAnchor: [20, 40],
    });
  }

  /* ─── Spawn Target ───────────────────────────────── */
  async function spawnTarget(lat, lng) {
    // Random offset ~100–400 m away
    const dlat = (Math.random() - 0.5) * 0.006;
    const dlng = (Math.random() - 0.5) * 0.006;
    targetPos = L.latLng(lat + dlat, lng + dlng);
    distance  = Math.round(currentPos.distanceTo(targetPos));

    targetMarker = L.marker(targetPos, { icon: targetIcon() }).addTo(map);
    line = L.polyline([currentPos, targetPos], {
      color: '#ffcb05', weight: 2, dashArray: '6 10', opacity: 0.6
    }).addTo(map);
    map.fitBounds(L.latLngBounds(currentPos, targetPos), { padding: [60, 60] });

    // Reverse-geocode
    try {
      const r = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${targetPos.lat}&lon=${targetPos.lng}`
      );
      const d = await r.json();
      streetName =
        d.address?.road ||
        d.address?.pedestrian ||
        d.address?.path ||
        d.address?.suburb ||
        d.name ||
        'Mystery Lane';
    } catch {
      streetName = 'Mystery Lane';
    }

    phase = 'loading_riddle';
    await fetchRiddle();
    phase = 'hunting';
  }

  /* ─── Riddle ─────────────────────────────────────── */
  async function fetchRiddle() {
    loadingRiddle = true;
    try {
      // On Vercel, /api is same-origin — no env var needed.
      // For local dev, set VITE_BACKEND_URL=http://localhost:8000 in .env
      const apiBase = (import.meta.env.VITE_BACKEND_URL || '').replace(/\/$/, '');
      const url = apiBase ? `${apiBase}/api/generate-riddle` : '/api/generate-riddle';
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ street: streetName, distance })
      });
      const d = await r.json();
      riddle = d.riddle;
    } catch {
      riddle = `I'm a pathway ${distance}m from you, hidden in plain sight. Find my sign to claim your victory! 🗺️`;
    }
    loadingRiddle = false;
  }


  /* ─── Camera ─────────────────────────────────────── */
  async function openCamera() {
    phase = 'camera';
    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }
      });
      await new Promise(r => setTimeout(r, 100));
      videoEl.srcObject = cameraStream;
    } catch (e) {
      alert('Camera permission denied or unavailable.');
      phase = 'hunting';
    }
  }

  function takePhoto() {
    const ctx = canvasEl.getContext('2d');
    canvasEl.width  = videoEl.videoWidth;
    canvasEl.height = videoEl.videoHeight;
    ctx.drawImage(videoEl, 0, 0);
    photoUrl = canvasEl.toDataURL('image/jpeg', 0.85);
    stopCamera();
    phase = 'captured';
  }

  function stopCamera() {
    cameraStream?.getTracks().forEach(t => t.stop());
    cameraStream = null;
  }

  function confirmCapture() { phase = 'solved'; }
  function retakePhoto() { photoUrl = ''; openCamera(); }
  function resetHunt() {
    phase = 'gps';
    streetName = ''; riddle = ''; photoUrl = '';
    if (targetMarker) { map.removeLayer(targetMarker); targetMarker = null; }
    if (line)         { map.removeLayer(line); line = null; }
    targetPos = null; distance = 0;
    spawnTarget(currentPos.lat, currentPos.lng);
  }

  /* ─── Helpers ────────────────────────────────────── */
  $: distanceColor = distance < 50 ? '#00e676' : distance < 150 ? '#ffcb05' : '#cc0000';
  $: distanceLabel = distance < 50 ? 'Very Close!' : distance < 150 ? 'Getting Warm' : `${distance}m Away`;
  $: huntPhase = phase === 'hunting' || phase === 'camera' || phase === 'captured' || phase === 'solved';
</script>

<!-- ═══ MARKUP ════════════════════════════════════════════════════════ -->

<div class="root">
  <!-- Full-screen map -->
  <div id="map"></div>

  <!-- HUD top bar -->
  {#if huntPhase}
  <div class="hud-top">
    <div class="hud-logo">🗺️ StreetHunt</div>
    {#if phase !== 'solved'}
    <div class="hud-distance" style="color:{distanceColor}">
      <span class="dist-num">{distance}</span><span class="dist-unit">m</span>
    </div>
    {/if}
  </div>
  {/if}

  <!-- ─── GPS waiting overlay ─── -->
  {#if phase === 'gps'}
  <div class="overlay center-flex">
    <div class="splash-card">
      <div class="pokeball spin">⚙️</div>
      <h1>StreetHunt</h1>
      <p>Locking onto your position…</p>
      {#if gpsError}<p class="err">⚠️ {gpsError}</p>{/if}
    </div>
  </div>
  {/if}

  <!-- ─── Loading riddle ─── -->
  {#if phase === 'loading' || phase === 'loading_riddle'}
  <div class="overlay center-flex">
    <div class="splash-card">
      <div class="pokeball spin">🔮</div>
      <h2>Summoning Clue…</h2>
      <p>Gemma 2B is crafting your riddle</p>
    </div>
  </div>
  {/if}

  <!-- ─── Hunting bottom panel ─── -->
  {#if phase === 'hunting'}
  <div class="bottom-panel">
    <div class="panel-handle"></div>

    <div class="radar-row">
      <div class="radar-badge" style="border-color:{distanceColor}; box-shadow: 0 0 16px {distanceColor}40">
        <span class="radar-dist" style="color:{distanceColor}">{distance}m</span>
        <span class="radar-label">{distanceLabel}</span>
      </div>
      <div class="compass">🧭</div>
    </div>

    <div class="riddle-card">
      <div class="riddle-header">
        <span class="gem-icon">💎</span>
        <span>Gemma 2B's Riddle</span>
      </div>
      <p class="riddle-text">{riddle || '…'}</p>
    </div>

    <button class="cta-btn" on:click={openCamera}>
      📸 Scan Street Sign
    </button>
  </div>
  {/if}

  <!-- ─── Camera view ─── -->
  {#if phase === 'camera'}
  <div class="camera-overlay">
    <!-- svelte-ignore a11y-media-has-caption -->
    <video bind:this={videoEl} autoplay playsinline class="cam-video"></video>

    <!-- Viewfinder overlay -->
    <div class="viewfinder">
      <div class="vf-corner tl"></div>
      <div class="vf-corner tr"></div>
      <div class="vf-corner bl"></div>
      <div class="vf-corner br"></div>
      <p class="vf-hint">Point at the Street Name Board</p>
    </div>

    <div class="cam-controls">
      <button class="cam-cancel" on:click={() => { stopCamera(); phase = 'hunting'; }}>✕</button>
      <button class="cam-shutter" on:click={takePhoto}><span class="shutter-inner"></span></button>
      <div style="width:48px"></div><!-- spacer -->
    </div>
  </div>
  {/if}

  <!-- ─── Captured review ─── -->
  {#if phase === 'captured'}
  <div class="overlay center-flex">
    <div class="review-card">
      <img src={photoUrl} alt="Captured street name" class="review-photo" />
      <div class="review-actions">
        <button class="btn-outline" on:click={retakePhoto}>↺ Retake</button>
        <button class="btn-solid" on:click={confirmCapture}>✓ Confirm</button>
      </div>
    </div>
  </div>
  {/if}

  <!-- ─── Victory screen ─── -->
  {#if phase === 'solved'}
  <div class="overlay center-flex victory-bg">
    <div class="victory-card">
      <div class="victory-trophy">🏆</div>
      <h2 class="victory-title">Street Found!</h2>
      <p class="victory-street">{streetName}</p>
      <img src={photoUrl} alt="Street sign" class="victory-photo" />
      <p class="victory-sub">You solved the riddle and captured proof!</p>
      <button class="cta-btn" style="width:100%;margin-top:1rem" on:click={resetHunt}>
        🗺️ New Hunt
      </button>
    </div>
  </div>
  {/if}
</div>

<!-- Hidden canvas for photo capture -->
<canvas bind:this={canvasEl} style="display:none"></canvas>

<!-- ═══ STYLES ═════════════════════════════════════════════════════════ -->
<style>
  /* ── Layout ── */
  .root {
    position: fixed;
    inset: 0;
    display: flex;
    flex-direction: column;
  }
  :global(#map) {
    position: absolute;
    inset: 0;
    z-index: 0;
  }

  /* ── Overlays ── */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 300;
    background: rgba(10, 10, 24, 0.82);
    backdrop-filter: blur(6px);
  }
  .center-flex {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
  }
  .victory-bg {
    background: linear-gradient(160deg, rgba(0,0,0,0.9) 0%, rgba(26,58,107,0.9) 100%);
  }

  /* ── Splash / loading card ── */
  .splash-card {
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
  }
  .splash-card h1 {
    font-size: 2rem;
    font-weight: 900;
    color: #ffcb05;
    text-shadow: 0 0 20px #ffcb0580;
    letter-spacing: 2px;
  }
  .splash-card h2 { color: #ffcb05; font-size: 1.4rem; }
  .splash-card p  { color: rgba(255,255,255,0.75); font-size: 0.95rem; }
  .err { color: #ff6b6b !important; }

  .pokeball {
    font-size: 3.5rem;
    display: block;
  }
  .spin { animation: spin 1.5s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Top HUD ── */
  .hud-top {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    z-index: 200;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.6rem 1rem;
    background: linear-gradient(to bottom, rgba(10,10,24,0.9) 0%, transparent 100%);
    pointer-events: none;
  }
  .hud-logo {
    font-size: 1rem;
    font-weight: 900;
    color: #ffcb05;
    letter-spacing: 1px;
    text-shadow: 0 0 10px #ffcb0580;
  }
  .hud-distance {
    font-size: 0.85rem;
    font-weight: 700;
    display: flex;
    align-items: baseline;
    gap: 2px;
  }
  .dist-num { font-size: 1.6rem; font-weight: 900; }
  .dist-unit { font-size: 0.8rem; opacity: 0.8; }

  /* ── Bottom panel (hunting) ── */
  .bottom-panel {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 200;
    background: var(--poke-panel);
    border-top: 1px solid var(--glass-border);
    border-radius: 24px 24px 0 0;
    padding: 0.5rem 1.25rem 1.25rem;
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
  }
  .panel-handle {
    width: 40px;
    height: 4px;
    background: rgba(255,255,255,0.2);
    border-radius: 2px;
    align-self: center;
    margin-bottom: 0.25rem;
  }

  /* Radar row */
  .radar-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .radar-badge {
    display: flex;
    flex-direction: column;
    align-items: center;
    border: 2px solid;
    border-radius: 50px;
    padding: 0.5rem 1.1rem;
    min-width: 110px;
    transition: all 0.4s ease;
  }
  .radar-dist  { font-size: 1.5rem; font-weight: 900; line-height: 1; }
  .radar-label { font-size: 0.7rem; opacity: 0.8; font-weight: 600; letter-spacing: 0.5px; }
  .compass { font-size: 2rem; }

  /* Riddle card */
  .riddle-card {
    background: rgba(61, 125, 202, 0.15);
    border: 1px solid rgba(61, 125, 202, 0.4);
    border-radius: 14px;
    padding: 0.85rem 1rem;
  }
  .riddle-header {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 1px;
    color: #3d7dca;
    text-transform: uppercase;
    margin-bottom: 0.5rem;
  }
  .gem-icon { font-size: 0.9rem; }
  .riddle-text {
    font-size: 0.95rem;
    line-height: 1.6;
    color: rgba(255,255,255,0.9);
    font-style: italic;
  }

  /* CTA button */
  .cta-btn {
    width: 100%;
    padding: 0.9rem;
    background: linear-gradient(135deg, #cc0000 0%, #ff4444 100%);
    color: white;
    border: none;
    border-radius: 50px;
    font-family: 'Exo 2', sans-serif;
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: 0.5px;
    cursor: pointer;
    box-shadow: 0 4px 20px rgba(204, 0, 0, 0.5);
    transition: transform 0.1s, box-shadow 0.1s;
    text-transform: uppercase;
  }
  .cta-btn:active { transform: scale(0.97); box-shadow: 0 2px 10px rgba(204,0,0,0.4); }

  /* ── Player / target map icons ── */
  :global(.player-dot) {
    width: 48px; height: 48px;
    display: flex; align-items: center; justify-content: center;
    position: relative;
  }
  :global(.player-pulse) {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: rgba(61,125,202,0.4);
    animation: pulse 2s ease-out infinite;
  }
  :global(.player-inner) { font-size: 1.6rem; z-index: 1; position: relative; }
  :global(.target-pin) { font-size: 2rem; filter: drop-shadow(0 0 6px rgba(255,203,5,0.8)); }
  @keyframes pulse {
    0%   { transform: scale(0.8); opacity: 0.8; }
    70%  { transform: scale(1.8); opacity: 0; }
    100% { transform: scale(0.8); opacity: 0; }
  }

  /* ── Camera overlay ── */
  .camera-overlay {
    position: fixed;
    inset: 0;
    z-index: 400;
    background: #000;
    display: flex;
    flex-direction: column;
  }
  .cam-video {
    flex: 1;
    width: 100%;
    object-fit: cover;
  }
  .viewfinder {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -60%);
    width: min(80vw, 340px);
    height: 160px;
    pointer-events: none;
  }
  .vf-corner {
    position: absolute;
    width: 28px; height: 28px;
    border-color: #ffcb05;
    border-style: solid;
  }
  .vf-corner.tl { top: 0; left: 0;  border-width: 3px 0 0 3px; border-radius: 4px 0 0 0; }
  .vf-corner.tr { top: 0; right: 0; border-width: 3px 3px 0 0; border-radius: 0 4px 0 0; }
  .vf-corner.bl { bottom: 0; left: 0;  border-width: 0 0 3px 3px; border-radius: 0 0 0 4px; }
  .vf-corner.br { bottom: 0; right: 0; border-width: 0 3px 3px 0; border-radius: 0 0 4px 0; }
  .vf-hint {
    position: absolute;
    bottom: -30px;
    left: 50%;
    transform: translateX(-50%);
    white-space: nowrap;
    color: rgba(255,255,255,0.8);
    font-size: 0.8rem;
    text-align: center;
  }
  .cam-controls {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1.2rem 2rem 2.5rem;
    background: rgba(0,0,0,0.6);
    backdrop-filter: blur(10px);
  }
  .cam-cancel {
    width: 48px; height: 48px;
    background: rgba(255,255,255,0.15);
    border: 1px solid rgba(255,255,255,0.3);
    border-radius: 50%;
    color: #fff;
    font-size: 1.2rem;
    cursor: pointer;
    display: flex; align-items: center; justify-content: center;
  }
  .cam-shutter {
    width: 72px; height: 72px;
    background: rgba(255,255,255,0.9);
    border: 4px solid #fff;
    border-radius: 50%;
    cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 0 0 6px rgba(255,255,255,0.3);
    transition: transform 0.1s;
  }
  .cam-shutter:active { transform: scale(0.92); }
  .shutter-inner {
    width: 56px; height: 56px;
    background: #fff;
    border-radius: 50%;
    border: 3px solid rgba(0,0,0,0.15);
  }

  /* ── Review ── */
  .review-card {
    background: var(--poke-panel);
    border: 1px solid var(--glass-border);
    border-radius: 20px;
    overflow: hidden;
    width: 100%;
    max-width: 420px;
  }
  .review-photo {
    width: 100%;
    max-height: 50vh;
    object-fit: cover;
    display: block;
  }
  .review-actions {
    display: flex;
    gap: 0.75rem;
    padding: 1rem;
  }
  .btn-outline {
    flex: 1;
    padding: 0.75rem;
    background: transparent;
    border: 2px solid rgba(255,255,255,0.3);
    color: #fff;
    border-radius: 50px;
    font-family: 'Exo 2', sans-serif;
    font-size: 0.95rem;
    font-weight: 700;
    cursor: pointer;
  }
  .btn-solid {
    flex: 2;
    padding: 0.75rem;
    background: linear-gradient(135deg, #1a6b2a 0%, #00e676 100%);
    border: none;
    color: #fff;
    border-radius: 50px;
    font-family: 'Exo 2', sans-serif;
    font-size: 0.95rem;
    font-weight: 700;
    cursor: pointer;
    box-shadow: 0 4px 15px rgba(0,230,118,0.4);
  }

  /* ── Victory ── */
  .victory-card {
    background: linear-gradient(160deg, rgba(26,58,107,0.95) 0%, rgba(10,10,24,0.95) 100%);
    border: 1px solid rgba(255,203,5,0.4);
    border-radius: 24px;
    padding: 2rem 1.5rem;
    width: 100%;
    max-width: 420px;
    text-align: center;
    box-shadow: 0 0 40px rgba(255,203,5,0.2);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
    max-height: 90vh;
    overflow-y: auto;
  }
  .victory-trophy {
    font-size: 4rem;
    animation: bounce 0.8s ease infinite alternate;
  }
  @keyframes bounce { to { transform: translateY(-8px); } }
  .victory-title {
    font-size: 1.8rem;
    font-weight: 900;
    color: #ffcb05;
    text-shadow: 0 0 20px #ffcb0580;
  }
  .victory-street {
    font-size: 1.1rem;
    font-weight: 700;
    color: #3d7dca;
    background: rgba(61,125,202,0.15);
    border: 1px solid rgba(61,125,202,0.4);
    border-radius: 50px;
    padding: 0.4rem 1.2rem;
  }
  .victory-photo {
    width: 100%;
    max-height: 200px;
    object-fit: cover;
    border-radius: 14px;
    border: 2px solid rgba(255,203,5,0.3);
  }
  .victory-sub {
    font-size: 0.85rem;
    color: rgba(255,255,255,0.6);
  }
</style>

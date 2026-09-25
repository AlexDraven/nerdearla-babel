(function () {
  const params = new URLSearchParams(window.location.search);
  const apiHost = params.get("api_host") || window.location.host || "localhost:8000";
  const pollIntervalMs = 1500;
  const maxLatencySamples = 5;

  const roomsEl = document.getElementById("rooms");
  const emptyStateEl = document.getElementById("empty-state");

  // room_id -> { els: {...DOM refs...}, latencies: number[], ws: WebSocket|null }
  const rooms = new Map();

  function httpUrl(path) {
    const protocol = window.location.protocol === "https:" ? "https" : "http";
    return `${protocol}://${apiHost}${path}`;
  }

  function wsUrl(roomId) {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${apiHost}/ws/room/${encodeURIComponent(roomId)}`;
  }

  function createCard(roomId, protocol) {
    const card = document.createElement("article");
    card.className = "room-card";
    // roomId NO se interpola en el innerHTML (aunque hoy solo puede venir de
    // BABEL_ROOM_IDS, controlado por quien despliega) — se setea después via
    // textContent, mismo patrón que el resto del código usa para texto que
    // viene del backend.
    const micLink =
      protocol === "mic"
        ? `<a target="_blank" rel="noopener" href="../mic/index.html?room=${encodeURIComponent(roomId)}&ws_host=${encodeURIComponent(apiHost)}">🎙️ Grabar</a>`
        : "";
    card.innerHTML = `
      <div class="room-card__header">
        <span class="room-card__title"></span>
        <span class="status-dot" data-status="connecting">conectando</span>
      </div>
      <div class="room-card__metrics">
        <span>Cola: <b class="metric-queue">0</b></span>
        <span>Latencia prom.: <b class="metric-latency">–</b></span>
      </div>
      <div class="room-card__caption">
        <div class="placeholder">Esperando el primer fragmento transcripto...</div>
      </div>
      <div class="room-card__links">
        ${micLink}
        <a target="_blank" rel="noopener" href="../overlay/index.html?room=${encodeURIComponent(roomId)}&ws_host=${encodeURIComponent(apiHost)}&mode=reading">Vista de lectura</a>
        <a target="_blank" rel="noopener" href="${httpUrl(`/rooms/${encodeURIComponent(roomId)}/transcript.txt`)}">Transcript (txt)</a>
        <a target="_blank" rel="noopener" href="${httpUrl(`/rooms/${encodeURIComponent(roomId)}/transcript`)}">Transcript (json)</a>
      </div>
    `;
    card.querySelector(".room-card__title").textContent = roomId;
    roomsEl.appendChild(card);

    return {
      card,
      statusDot: card.querySelector(".status-dot"),
      queueMetric: card.querySelector(".metric-queue"),
      latencyMetric: card.querySelector(".metric-latency"),
      caption: card.querySelector(".room-card__caption"),
    };
  }

  function ensureRoom(roomId, protocol) {
    if (rooms.has(roomId)) return rooms.get(roomId);

    emptyStateEl.hidden = true;
    const els = createCard(roomId, protocol);
    const state = { els, latencies: [], ws: null, reconnectDelayMs: 1000 };
    rooms.set(roomId, state);
    connectWs(roomId, state);
    return state;
  }

  function setStatus(state, status) {
    state.els.statusDot.dataset.status = status;
    state.els.statusDot.textContent = status;
  }

  function pushLatency(state, latencySeconds) {
    state.latencies.push(latencySeconds);
    if (state.latencies.length > maxLatencySamples) state.latencies.shift();
    const avgMs = (state.latencies.reduce((a, b) => a + b, 0) / state.latencies.length) * 1000;
    state.els.latencyMetric.textContent = `${avgMs.toFixed(0)} ms`;
  }

  function showCaption(state, originalText, translatedText) {
    state.els.caption.innerHTML = "";
    const original = document.createElement("div");
    original.className = "original";
    original.textContent = originalText;
    state.els.caption.appendChild(original);

    if (translatedText && translatedText.trim() !== originalText.trim()) {
      const translation = document.createElement("div");
      translation.className = "translation";
      translation.textContent = translatedText;
      state.els.caption.appendChild(translation);
    }
  }

  const maxReconnectDelayMs = 15000;

  function connectWs(roomId, state) {
    const ws = new WebSocket(wsUrl(roomId));
    state.ws = ws;

    ws.addEventListener("open", () => {
      state.reconnectDelayMs = 1000;
    });

    ws.addEventListener("message", (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (err) {
        return;
      }

      if (payload.type === "transcript") {
        showCaption(state, payload.original_text, payload.translated_text);
        pushLatency(state, payload.latency_s);
      } else if (payload.type === "status") {
        setStatus(state, payload.status);
      }
    });

    ws.addEventListener("close", () => {
      setTimeout(() => connectWs(roomId, state), state.reconnectDelayMs);
      state.reconnectDelayMs = Math.min(state.reconnectDelayMs * 2, maxReconnectDelayMs);
    });
    ws.addEventListener("error", () => ws.close());
  }

  async function poll() {
    let roomList;
    try {
      const res = await fetch(httpUrl("/rooms"));
      roomList = await res.json();
    } catch (err) {
      console.error("No se pudo consultar /rooms en", apiHost, err);
      return;
    }

    if (roomList.length === 0 && rooms.size === 0) {
      emptyStateEl.hidden = false;
      return;
    }

    for (const room of roomList) {
      const state = ensureRoom(room.room_id, room.protocol);
      state.els.queueMetric.textContent = String(room.queue_size);
      // el WS ya actualiza el status más rápido, pero el poll es el fallback
      // por si la conexión WS todavía no abrió.
      if (state.els.statusDot.dataset.status === "connecting") {
        setStatus(state, room.status);
      }
    }
  }

  poll();
  setInterval(poll, pollIntervalMs);
})();

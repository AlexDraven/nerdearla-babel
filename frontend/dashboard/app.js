(function () {
  const params = new URLSearchParams(window.location.search);
  const apiHost = params.get("api_host") || window.location.host || "localhost:8000";
  const pollIntervalMs = 1500;
  const maxLatencySamples = 5;

  const roomsEl = document.getElementById("rooms");
  const emptyStateEl = document.getElementById("empty-state");

  // room_id -> { els: {...DOM refs...}, latencies: number[], ws: WebSocket|null, micCapture: {stop()}|null }
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
    const isMic = protocol === "mic";
    // La sala mic ocupa todo el ancho (ver .room-card[data-protocol="mic"]
    // en style.css) y muestra varias líneas de historial en vez de solo el
    // último fragmento — es la que de verdad importa leer bien en vivo.
    card.dataset.protocol = protocol;

    // Sala mic: controles de grabación inline, en vez de un link a otra
    // pestaña — se puede probar sin salir del control room. Otras salas:
    // botón para pausar/reanudar su ingesta (ej. para liberarle capacidad
    // de inferencia a la sala mic mientras alguien graba, sin bajar Docker).
    const actionsHtml = isMic
      ? `
        <div class="mic-controls">
          <div class="mic-controls__row">
            <select class="mic-device-select" disabled>
              <option value="">Pidiendo permiso...</option>
            </select>
            <button type="button" class="mic-toggle-btn" disabled>Grabar</button>
          </div>
          <p class="mic-permission-error banner banner--error" hidden></p>
          <div class="mic-meter-row meter-row" hidden>
            <span class="meter-label">Nivel de audio</span>
            <div class="level-meter" aria-hidden="true"><div class="level-meter__fill"></div></div>
            <span class="mic-sent-info sent-info">0 fragmentos enviados (0 KB)</span>
          </div>
        </div>
      `
      : `
        <div class="room-card__actions">
          <button type="button" class="room-toggle-btn" data-action="pause">Detener</button>
        </div>
      `;

    const micFullscreenLink = isMic
      ? `<a target="_blank" rel="noopener" href="../mic/index.html?room=${encodeURIComponent(roomId)}&ws_host=${encodeURIComponent(apiHost)}">↗ pantalla completa</a>`
      : "";

    card.innerHTML = `
      <div class="room-card__header">
        <span class="room-card__title"></span>
        <span class="status-dot" data-status="connecting">conectando</span>
      </div>
      <div class="room-card__metrics">
        <span>Cola: <b class="metric-queue">0</b></span>
        <span>Demora audio→texto: <b class="metric-latency">–</b></span>
      </div>
      ${actionsHtml}
      <div class="room-card__caption${isMic ? " room-card__caption--mic" : ""}" role="log" aria-live="polite">
        <div class="placeholder">Esperando el primer fragmento transcripto...</div>
      </div>
      <div class="room-card__links">
        ${micFullscreenLink}
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
      roomToggleBtn: card.querySelector(".room-toggle-btn"),
      mic: isMic
        ? {
            deviceSelect: card.querySelector(".mic-device-select"),
            toggleBtn: card.querySelector(".mic-toggle-btn"),
            permissionError: card.querySelector(".mic-permission-error"),
            meterRow: card.querySelector(".mic-meter-row"),
            meterFill: card.querySelector(".level-meter__fill"),
            sentInfo: card.querySelector(".mic-sent-info"),
          }
        : null,
    };
  }

  // --- Grabar con el propio micrófono, inline en la card (BabelMicCapture,
  // ver frontend/shared/mic-capture.js — misma lógica que frontend/mic/). ---

  function setupMicControls(roomId, state) {
    const mic = state.els.mic;

    if (!window.BabelMicCapture || !window.BabelMicCapture.isSupported()) {
      mic.toggleBtn.disabled = true;
      mic.deviceSelect.disabled = true;
      mic.permissionError.textContent =
        "Este navegador no soporta grabación en el formato que usa este proyecto (audio/webm;codecs=opus). Probá con Chrome, Edge o Firefox.";
      mic.permissionError.hidden = false;
      return;
    }

    window.BabelMicCapture.listMicrophones()
      .then((mics) => {
        mic.deviceSelect.innerHTML = "";
        mics.forEach((m, i) => {
          const option = document.createElement("option");
          option.value = m.deviceId;
          option.textContent = m.label || `Micrófono ${i + 1}`;
          mic.deviceSelect.appendChild(option);
        });
        mic.deviceSelect.disabled = false;
        mic.toggleBtn.disabled = false;
      })
      .catch((err) => {
        mic.permissionError.textContent = `No se pudo acceder al micrófono (${err.name || err}). Revisá los permisos del navegador para este sitio y recargá la página.`;
        mic.permissionError.hidden = false;
      });

    function updateSentInfo(chunksSent, bytesSent) {
      mic.sentInfo.textContent = `${chunksSent} fragmento${chunksSent === 1 ? "" : "s"} enviado${chunksSent === 1 ? "" : "s"} (${(bytesSent / 1024).toFixed(0)} KB)`;
    }

    async function startMicCapture() {
      mic.meterRow.hidden = false;
      state.micCapture = await window.BabelMicCapture.startCapture({
        wsHost: apiHost,
        roomId,
        deviceId: mic.deviceSelect.value || null,
        onLevel: (level) => {
          mic.meterFill.style.width = `${Math.round(level * 100)}%`;
        },
        onSentInfo: updateSentInfo,
        onClose: () => stopMicCapture(),
      });
      mic.toggleBtn.textContent = "Parar";
      mic.toggleBtn.dataset.recording = "true";
      mic.deviceSelect.disabled = true;
    }

    function stopMicCapture() {
      if (!state.micCapture) return;
      state.micCapture.stop();
      state.micCapture = null;
      mic.meterRow.hidden = true;
      mic.toggleBtn.textContent = "Grabar";
      mic.toggleBtn.dataset.recording = "false";
      mic.deviceSelect.disabled = false;
    }

    mic.toggleBtn.addEventListener("click", async () => {
      mic.toggleBtn.disabled = true;
      try {
        if (state.micCapture) {
          stopMicCapture();
        } else {
          await startMicCapture();
        }
      } catch (err) {
        mic.permissionError.textContent = `No se pudo grabar: ${err.message || err}`;
        mic.permissionError.hidden = false;
      } finally {
        mic.toggleBtn.disabled = false;
      }
    });
  }

  // --- Pausar/reanudar la ingesta de una sala no-mic desde su card ---

  function setupRoomToggle(roomId, state) {
    const btn = state.els.roomToggleBtn;
    btn.addEventListener("click", async () => {
      const action = btn.dataset.action === "resume" ? "resume" : "pause";
      btn.disabled = true;
      try {
        await fetch(httpUrl(`/rooms/${encodeURIComponent(roomId)}/${action}`), { method: "POST" });
        // La confirmación real llega por WS (RoomStatusEvent) o, como
        // fallback, en el próximo poll() — no hace falta tocar el label acá:
        // dejarlo desincronizado hasta esa confirmación sería peor que
        // esperar el instante que tarda en llegar.
      } catch (err) {
        console.error(`No se pudo ${action === "pause" ? "detener" : "reanudar"} la sala`, roomId, err);
      } finally {
        btn.disabled = false;
      }
    });
  }

  function ensureRoom(roomId, protocol) {
    if (rooms.has(roomId)) return rooms.get(roomId);

    emptyStateEl.hidden = true;
    const els = createCard(roomId, protocol);
    const state = {
      els,
      isMic: protocol === "mic",
      latencies: [],
      ws: null,
      reconnectDelayMs: 1000,
      micCapture: null,
    };
    rooms.set(roomId, state);
    connectWs(roomId, state);
    if (protocol === "mic") setupMicControls(roomId, state);
    if (els.roomToggleBtn) setupRoomToggle(roomId, state);
    return state;
  }

  function setStatus(state, status) {
    state.els.statusDot.dataset.status = status;
    state.els.statusDot.textContent = status;

    // El botón de pausar/reanudar siempre refleja el último estado conocido
    // (llega por WS en cuanto pause()/resume() lo confirman del lado del
    // servidor, con poll() como fallback).
    const btn = state.els.roomToggleBtn;
    if (btn) {
      const isPaused = status === "paused";
      btn.textContent = isPaused ? "Reanudar" : "Detener";
      btn.dataset.action = isPaused ? "resume" : "pause";
    }
  }

  function pushDelay(state, audioToTextMs) {
    state.latencies.push(audioToTextMs);
    if (state.latencies.length > maxLatencySamples) state.latencies.shift();
    const avgMs = state.latencies.reduce((a, b) => a + b, 0) / state.latencies.length;
    state.els.latencyMetric.textContent = `${avgMs.toFixed(0)} ms`;
    state.els.latencyMetric.dataset.speed = avgMs < 5000 ? "fast" : avgMs < 15000 ? "medium" : "slow";
  }

  function showCaption(state, textEs, textEn) {
    state.els.caption.innerHTML = "";
    const esLine = document.createElement("div");
    esLine.className = "original";
    esLine.lang = "es";
    esLine.textContent = textEs;
    state.els.caption.appendChild(esLine);

    const enLine = document.createElement("div");
    enLine.className = "translation";
    enLine.lang = "en";
    enLine.textContent = textEn;
    state.els.caption.appendChild(enLine);
  }

  const maxMicCaptionEntries = 30;

  // La card de mic acumula historial (en vez de reemplazar el último
  // fragmento como el resto) — ocupa todo el ancho y muestra ~6 renglones,
  // así que tiene sentido ver de dónde viene la conversación, no solo la
  // última frase.
  function appendMicCaption(state, textEs, textEn) {
    const placeholder = state.els.caption.querySelector(".placeholder");
    if (placeholder) placeholder.remove();

    const entry = document.createElement("div");
    entry.className = "caption-entry";

    const esLine = document.createElement("div");
    esLine.className = "original";
    esLine.lang = "es";
    esLine.textContent = textEs;
    entry.appendChild(esLine);

    const enLine = document.createElement("div");
    enLine.className = "translation";
    enLine.lang = "en";
    enLine.textContent = textEn;
    entry.appendChild(enLine);

    state.els.caption.appendChild(entry);
    while (state.els.caption.children.length > maxMicCaptionEntries) {
      state.els.caption.removeChild(state.els.caption.firstChild);
    }
    state.els.caption.scrollTop = state.els.caption.scrollHeight;
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
        if (state.isMic) {
          appendMicCaption(state, payload.text_es, payload.text_en);
        } else {
          showCaption(state, payload.text_es, payload.text_en);
        }
        pushDelay(state, payload.audio_to_text_ms);
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

(function () {
  const params = new URLSearchParams(window.location.search);
  const roomId = params.get("room") || "mic";
  const wsHost = params.get("ws_host") || window.location.host || "localhost:8000";
  const maxHistoryEntries = 200;

  const deviceSelect = document.getElementById("device-select");
  const toggleBtn = document.getElementById("toggle-record");
  const statusEl = document.getElementById("status");
  const historyEl = document.getElementById("history");
  const unsupportedEl = document.getElementById("unsupported");
  const permissionErrorEl = document.getElementById("permission-error");
  const meterRowEl = document.getElementById("meter-row");
  const meterFillEl = document.getElementById("level-meter-fill");
  const sentInfoEl = document.getElementById("sent-info");

  let capture = null; // { stop() } de BabelMicCapture.startCapture()

  function setStatus(state, label) {
    statusEl.dataset.state = state;
    statusEl.textContent = label || state;
  }

  function showPermissionError(message) {
    permissionErrorEl.textContent = message;
    permissionErrorEl.hidden = false;
  }

  function appendHistoryEntry(payload) {
    const placeholder = historyEl.querySelector(".placeholder");
    if (placeholder) placeholder.remove();

    const entry = document.createElement("div");
    entry.className = "history-entry";

    const time = document.createElement("time");
    const date = payload.ts ? new Date(payload.ts * 1000) : new Date();
    time.textContent = date.toLocaleTimeString();
    if (typeof payload.audio_to_text_ms === "number") {
      const ms = payload.audio_to_text_ms;
      const delay = document.createElement("span");
      delay.className = "delay-badge";
      delay.textContent = `${ms} ms`;
      delay.dataset.speed = ms < 5000 ? "fast" : ms < 15000 ? "medium" : "slow";
      delay.title = "Tiempo desde que terminaste de decir esto hasta que apareció el texto";
      time.appendChild(document.createTextNode(" · "));
      time.appendChild(delay);
    }
    entry.appendChild(time);

    const esLine = document.createElement("div");
    esLine.className = "original";
    esLine.lang = "es";
    esLine.textContent = payload.text_es;
    entry.appendChild(esLine);

    const enLine = document.createElement("div");
    enLine.className = "translation";
    enLine.lang = "en";
    enLine.textContent = payload.text_en;
    entry.appendChild(enLine);

    historyEl.appendChild(entry);
    while (historyEl.children.length > maxHistoryEntries) {
      historyEl.removeChild(historyEl.firstChild);
    }
    historyEl.scrollTop = historyEl.scrollHeight;
  }

  // --- WS de salida: mismo canal que usa el overlay, para ver la
  // transcripción en vivo sin tener que abrir otra pestaña ---

  function connectOutputWs() {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${protocol}://${wsHost}/ws/room/${encodeURIComponent(roomId)}`);
    let reconnectDelayMs = 1000;

    ws.addEventListener("open", () => {
      reconnectDelayMs = 1000;
    });

    ws.addEventListener("message", (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (payload.type === "transcript") {
        appendHistoryEntry(payload);
      } else if (payload.type === "status") {
        setStatus(payload.status, payload.detail ? `${payload.status} (${payload.detail})` : payload.status);
      }
    });

    ws.addEventListener("close", () => {
      setTimeout(connectOutputWs, reconnectDelayMs);
      reconnectDelayMs = Math.min(reconnectDelayMs * 2, 15000);
    });
    ws.addEventListener("error", () => ws.close());
  }

  function updateSentInfo(chunksSent, bytesSent) {
    sentInfoEl.textContent = `${chunksSent} fragmento${chunksSent === 1 ? "" : "s"} enviado${chunksSent === 1 ? "" : "s"} (${(bytesSent / 1024).toFixed(0)} KB)`;
  }

  // --- Captura de mic (BabelMicCapture, ver frontend/shared/mic-capture.js) ---

  async function populateDeviceList() {
    try {
      const mics = await window.BabelMicCapture.listMicrophones();
      deviceSelect.innerHTML = "";
      mics.forEach((mic, i) => {
        const option = document.createElement("option");
        option.value = mic.deviceId;
        option.textContent = mic.label || `Micrófono ${i + 1}`;
        deviceSelect.appendChild(option);
      });
      deviceSelect.disabled = false;
      toggleBtn.disabled = false;
    } catch (err) {
      showPermissionError(
        `No se pudo acceder al micrófono (${err.name || err}). Revisá los permisos del navegador para este sitio y recargá la página.`
      );
    }
  }

  async function startCapture() {
    meterRowEl.hidden = false;

    capture = await window.BabelMicCapture.startCapture({
      wsHost,
      roomId,
      deviceId: deviceSelect.value || null,
      onLevel: (level) => {
        meterFillEl.style.width = `${Math.round(level * 100)}%`;
      },
      onSentInfo: updateSentInfo,
      onClose: () => stopCapture(),
    });

    toggleBtn.textContent = "Parar";
    toggleBtn.dataset.recording = "true";
    deviceSelect.disabled = true;
  }

  function stopCapture() {
    if (!capture) return;
    capture.stop();
    capture = null;
    meterRowEl.hidden = true;

    toggleBtn.textContent = "Grabar";
    toggleBtn.dataset.recording = "false";
    deviceSelect.disabled = false;
  }

  toggleBtn.addEventListener("click", async () => {
    toggleBtn.disabled = true;
    try {
      if (capture) {
        stopCapture();
      } else {
        await startCapture();
      }
    } catch (err) {
      showPermissionError(`No se pudo grabar: ${err.message || err}`);
    } finally {
      toggleBtn.disabled = false;
    }
  });

  if (!window.BabelMicCapture.isSupported()) {
    unsupportedEl.hidden = false;
    toggleBtn.disabled = true;
    deviceSelect.disabled = true;
  } else {
    populateDeviceList();
    setStatus("idle", "conectando...");
    connectOutputWs();
  }
})();

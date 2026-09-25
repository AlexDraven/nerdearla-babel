(function () {
  const params = new URLSearchParams(window.location.search);
  const roomId = params.get("room") || "mic";
  const wsHost = params.get("ws_host") || window.location.host || "localhost:8000";
  const MIME_TYPE = "audio/webm;codecs=opus";
  const RECORDER_TIMESLICE_MS = 250;
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

  let capture = null; // { stream, ws, recorder, audioCtx, analyser, meterRafId, bytesSent, chunksSent }

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
    entry.appendChild(time);

    const original = document.createElement("div");
    original.className = "original";
    original.textContent = payload.original_text;
    if (payload.lang && payload.lang !== "unknown") original.lang = payload.lang;
    entry.appendChild(original);

    if (payload.translated_text && payload.translated_text.trim() !== payload.original_text.trim()) {
      const translation = document.createElement("div");
      translation.className = "translation";
      translation.textContent = payload.translated_text;
      entry.appendChild(translation);
    }

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

  // --- Medidor de nivel: confirma que el mic está agarrando sonido de
  // verdad, INDEPENDIENTE de si el WS/backend/Ollama están funcionando —
  // primer paso para diagnosticar "no transcribe nada" (¿es el mic, la
  // red, o el modelo?). Usa AnalyserNode (no AudioWorklet) a propósito:
  // no carga ningún módulo aparte, así que funciona igual si la página se
  // abrió como file:// o servida por HTTP. ---

  function startLevelMeter(stream) {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const audioCtx = new AudioCtx();
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);

    const data = new Uint8Array(analyser.fftSize);
    let rafId;

    function tick() {
      analyser.getByteTimeDomainData(data);
      let sumSquares = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sumSquares += v * v;
      }
      const rms = Math.sqrt(sumSquares / data.length);
      const level = Math.min(1, rms * 4); // escalado para que un tono de voz normal se note
      meterFillEl.style.width = `${Math.round(level * 100)}%`;
      rafId = requestAnimationFrame(tick);
    }
    tick();

    return {
      audioCtx,
      stop() {
        if (rafId) cancelAnimationFrame(rafId);
        audioCtx.close().catch(() => {});
        meterFillEl.style.width = "0%";
      },
    };
  }

  function updateSentInfo(chunksSent, bytesSent) {
    sentInfoEl.textContent = `${chunksSent} fragmento${chunksSent === 1 ? "" : "s"} enviado${chunksSent === 1 ? "" : "s"} (${(bytesSent / 1024).toFixed(0)} KB)`;
  }

  // --- Captura de mic ---

  async function listMicrophones() {
    // enumerateDevices() no devuelve `label` sin permiso concedido antes —
    // pedimos getUserMedia una vez solo para desbloquear los nombres.
    const tempStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    tempStream.getTracks().forEach((t) => t.stop());
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === "audioinput");
  }

  async function populateDeviceList() {
    try {
      const mics = await listMicrophones();
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
    const deviceId = deviceSelect.value || null;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
    });

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${protocol}://${wsHost}/ws/mic/${encodeURIComponent(roomId)}`);
    ws.binaryType = "arraybuffer";

    // Esperamos a que el WS esté abierto ANTES de arrancar el MediaRecorder:
    // si no, se puede perder el primer blob (el que trae el header WebM) y
    // ffmpeg del lado del backend nunca logra interpretar el resto.
    await new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", () => reject(new Error("No se pudo conectar al servidor")), { once: true });
    });

    let bytesSent = 0;
    let chunksSent = 0;
    updateSentInfo(0, 0);
    meterRowEl.hidden = false;

    const recorder = new MediaRecorder(stream, { mimeType: MIME_TYPE, audioBitsPerSecond: 32000 });
    recorder.addEventListener("dataavailable", (e) => {
      if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
        ws.send(e.data);
        chunksSent += 1;
        bytesSent += e.data.size;
        updateSentInfo(chunksSent, bytesSent);
      }
    });
    recorder.start(RECORDER_TIMESLICE_MS);

    const meter = startLevelMeter(stream);

    ws.addEventListener("close", () => {
      // si el server cierra la conexión de golpe (ej. sala inválida), volvemos
      // al estado "sin grabar" en vez de quedar con un botón mintiendo.
      if (capture && capture.ws === ws) stopCapture();
    });

    capture = { stream, ws, recorder, meter };
    toggleBtn.textContent = "Parar";
    toggleBtn.dataset.recording = "true";
    deviceSelect.disabled = true;
  }

  function stopCapture() {
    if (!capture) return;
    const { stream, ws, recorder, meter } = capture;
    if (recorder.state !== "inactive") recorder.stop();
    stream.getTracks().forEach((t) => t.stop());
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close();
    meter.stop();
    meterRowEl.hidden = true;
    capture = null;

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

  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported(MIME_TYPE)) {
    unsupportedEl.hidden = false;
    toggleBtn.disabled = true;
    deviceSelect.disabled = true;
  } else {
    populateDeviceList();
    setStatus("idle", "conectando...");
    connectOutputWs();
  }
})();

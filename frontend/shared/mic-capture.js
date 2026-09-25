// Captura de micrófono compartida entre frontend/mic/ (página standalone) y
// frontend/dashboard/ (control room, controles inline por sala). Sin build
// step: se expone como global (window.BabelMicCapture), cargado con un
// <script> plano antes del app.js de cada página — mismo patrón vanilla-JS
// que el resto de frontend/.
window.BabelMicCapture = (function () {
  const MIME_TYPE = "audio/webm;codecs=opus";
  const RECORDER_TIMESLICE_MS = 250;

  function isSupported() {
    return typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(MIME_TYPE);
  }

  async function listMicrophones() {
    // enumerateDevices() no devuelve `label` sin permiso concedido antes —
    // pedimos getUserMedia una vez solo para desbloquear los nombres.
    const tempStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    tempStream.getTracks().forEach((t) => t.stop());
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === "audioinput");
  }

  // Medidor de nivel: confirma que el mic está agarrando sonido de verdad,
  // INDEPENDIENTE de si el WS/backend/Ollama están funcionando. Usa
  // AnalyserNode (no AudioWorklet) a propósito: no carga ningún módulo
  // aparte, así que funciona igual si la página se abrió como file:// o
  // servida por HTTP.
  function startLevelMeter(stream, onLevel) {
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
      if (onLevel) onLevel(level);
      rafId = requestAnimationFrame(tick);
    }
    tick();

    return {
      stop() {
        if (rafId) cancelAnimationFrame(rafId);
        audioCtx.close().catch(() => {});
        if (onLevel) onLevel(0);
      },
    };
  }

  /**
   * Arranca la captura: pide el mic, abre el WS de ingesta y manda blobs de
   * MediaRecorder. onLevel(0..1) y onSentInfo(chunksSent, bytesSent) se
   * llaman en cada actualización — quien use esto decide cómo pintarlo.
   * onClose() se llama solo si el servidor cierra la conexión de golpe (ej.
   * sala inválida), para que el caller vuelva al estado "sin grabar".
   * Devuelve { stop() }.
   */
  async function startCapture({ wsHost, roomId, deviceId, onLevel, onSentInfo, onClose }) {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
    });

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${protocol}://${wsHost}/ws/mic/${encodeURIComponent(roomId)}`);
    ws.binaryType = "arraybuffer";

    // Esperamos a que el WS esté abierto ANTES de arrancar el MediaRecorder:
    // si no, se puede perder el primer blob (el que trae el header WebM) y
    // ffmpeg del lado del backend nunca logra interpretar el resto.
    try {
      await new Promise((resolve, reject) => {
        ws.addEventListener("open", resolve, { once: true });
        ws.addEventListener("error", () => reject(new Error("No se pudo conectar al servidor")), { once: true });
      });
    } catch (err) {
      stream.getTracks().forEach((t) => t.stop());
      throw err;
    }

    let bytesSent = 0;
    let chunksSent = 0;
    if (onSentInfo) onSentInfo(0, 0);

    const recorder = new MediaRecorder(stream, { mimeType: MIME_TYPE, audioBitsPerSecond: 32000 });
    recorder.addEventListener("dataavailable", (e) => {
      if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
        ws.send(e.data);
        chunksSent += 1;
        bytesSent += e.data.size;
        if (onSentInfo) onSentInfo(chunksSent, bytesSent);
      }
    });
    recorder.start(RECORDER_TIMESLICE_MS);

    const meter = startLevelMeter(stream, onLevel);

    let stopped = false;
    function stop() {
      if (stopped) return;
      stopped = true;
      if (recorder.state !== "inactive") recorder.stop();
      stream.getTracks().forEach((t) => t.stop());
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close();
      meter.stop();
    }

    ws.addEventListener("close", () => {
      const wasAlreadyStopped = stopped;
      stop();
      if (!wasAlreadyStopped && onClose) onClose();
    });

    return { stop };
  }

  return { isSupported, listMicrophones, startCapture };
})();

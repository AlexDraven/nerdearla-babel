(function () {
  const params = new URLSearchParams(window.location.search);
  const roomId = params.get("room") || "main";
  const wsHost = params.get("ws_host") || window.location.host || "localhost:8000";
  const mode = params.get("mode") === "reading" ? "reading" : "broadcast";
  const captionHideDelayMs = 6000;
  const maxHistoryEntries = 200;
  const fontSizeStepRem = 0.15;
  const minFontSizeRem = 0.9;
  const maxFontSizeRem = 2.5;

  document.body.dataset.mode = mode;

  const captionEl = document.getElementById("caption");
  const statusEl = document.getElementById("status");
  const controlsEl = document.getElementById("controls");
  const historyEl = document.getElementById("history");
  const jumpLatestEl = document.getElementById("jump-latest");

  let hideTimer = null;
  let reconnectDelayMs = 1000;
  const maxReconnectDelayMs = 15000;
  let userScrolledUp = false;

  function setStatus(state, label) {
    statusEl.dataset.state = state;
    statusEl.textContent = label;
  }

  // --- Modo broadcast (OBS): línea flotante efímera, sin scrollback ---
  // Siempre las dos líneas (ES + EN) — el backend ya manda los dos idiomas
  // en cada evento, sin importar cuál se habló realmente (ver payload.lang).

  function showEphemeralCaption(textEs, textEn) {
    captionEl.innerHTML = "";

    const esLine = document.createElement("div");
    esLine.className = "original";
    esLine.lang = "es";
    esLine.textContent = textEs;
    captionEl.appendChild(esLine);

    const enLine = document.createElement("div");
    enLine.className = "translation";
    enLine.lang = "en";
    enLine.textContent = textEn;
    captionEl.appendChild(enLine);

    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      captionEl.innerHTML = "";
    }, captionHideDelayMs);
  }

  // --- Modo reading (accesibilidad): historial completo, controles ---

  function initReadingControls() {
    controlsEl.hidden = false;
    historyEl.hidden = false;

    let fontSizeRem = parseFloat(localStorage.getItem("babel_font_size_rem")) || 1.3;
    let highContrast = localStorage.getItem("babel_high_contrast") === "1";

    function applyFontSize() {
      document.documentElement.style.setProperty("--reading-font-size", `${fontSizeRem}rem`);
    }

    function applyContrast() {
      document.body.dataset.contrast = highContrast ? "high" : "normal";
    }

    document.getElementById("font-dec").addEventListener("click", () => {
      fontSizeRem = Math.max(minFontSizeRem, fontSizeRem - fontSizeStepRem);
      localStorage.setItem("babel_font_size_rem", String(fontSizeRem));
      applyFontSize();
    });

    document.getElementById("font-inc").addEventListener("click", () => {
      fontSizeRem = Math.min(maxFontSizeRem, fontSizeRem + fontSizeStepRem);
      localStorage.setItem("babel_font_size_rem", String(fontSizeRem));
      applyFontSize();
    });

    document.getElementById("contrast-toggle").addEventListener("click", () => {
      highContrast = !highContrast;
      localStorage.setItem("babel_high_contrast", highContrast ? "1" : "0");
      applyContrast();
    });

    applyFontSize();
    applyContrast();

    historyEl.addEventListener("scroll", () => {
      const distanceFromBottom = historyEl.scrollHeight - historyEl.scrollTop - historyEl.clientHeight;
      userScrolledUp = distanceFromBottom > 40;
      jumpLatestEl.hidden = !userScrolledUp;
    });

    jumpLatestEl.addEventListener("click", () => {
      historyEl.scrollTop = historyEl.scrollHeight;
      userScrolledUp = false;
      jumpLatestEl.hidden = true;
    });
  }

  function appendHistoryEntry(payload) {
    const entry = document.createElement("div");
    entry.className = "history-entry";

    const time = document.createElement("time");
    const date = payload.ts ? new Date(payload.ts * 1000) : new Date();
    time.textContent = date.toLocaleTimeString();
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

    if (!userScrolledUp) {
      historyEl.scrollTop = historyEl.scrollHeight;
      jumpLatestEl.hidden = true;
    } else {
      jumpLatestEl.hidden = false;
    }
  }

  function handleMessage(event) {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (err) {
      console.error("Mensaje WS no es JSON válido", event.data, err);
      return;
    }

    if (payload.type === "transcript") {
      if (mode === "reading") {
        appendHistoryEntry(payload);
      } else {
        showEphemeralCaption(payload.text_es, payload.text_en);
      }
    } else if (payload.type === "status") {
      setStatus(payload.status, payload.detail ? `${payload.status} (${payload.detail})` : payload.status);
    }
  }

  function connect() {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${protocol}://${wsHost}/ws/room/${encodeURIComponent(roomId)}`);

    ws.addEventListener("open", () => {
      reconnectDelayMs = 1000;
      setStatus("connected", "conectado");
    });

    ws.addEventListener("message", handleMessage);

    ws.addEventListener("close", () => {
      setStatus("disconnected", "reconectando...");
      setTimeout(connect, reconnectDelayMs);
      reconnectDelayMs = Math.min(reconnectDelayMs * 2, maxReconnectDelayMs);
    });

    ws.addEventListener("error", () => {
      ws.close();
    });
  }

  if (mode === "reading") initReadingControls();
  setStatus("connecting", "conectando...");
  connect();
})();

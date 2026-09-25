(function () {
  const params = new URLSearchParams(window.location.search);
  const roomId = params.get("room") || "main";
  const wsHost = params.get("ws_host") || window.location.host || "localhost:8000";
  const captionHideDelayMs = 6000;

  const captionEl = document.getElementById("caption");
  const statusEl = document.getElementById("status");

  let hideTimer = null;
  let reconnectDelayMs = 1000;
  const maxReconnectDelayMs = 15000;

  function setStatus(state, label) {
    statusEl.dataset.state = state;
    statusEl.textContent = label;
  }

  function showCaption(text) {
    captionEl.textContent = text;
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      captionEl.textContent = "";
    }, captionHideDelayMs);
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
      showCaption(payload.text);
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

  setStatus("connecting", "conectando...");
  connect();
})();

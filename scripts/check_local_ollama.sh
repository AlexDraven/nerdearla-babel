#!/usr/bin/env bash
# Valida que un Ollama NATIVO (fuera de Docker) esté corriendo en el host y
# tenga el modelo pulleado, antes de levantar docker-compose.local-ollama.yml
# — pensado para que alguien no técnico (ej. un jurado) tenga un mensaje
# claro de qué falta, en vez de una sala que nunca conecta sin explicación.
#
# Uso: ./scripts/check_local_ollama.sh [modelo]

set -uo pipefail

MODEL="${1:-${OLLAMA_MODEL:-gemma4:e2b}}"
OLLAMA_URL="http://localhost:11434"

echo "Verificando Ollama nativo en ${OLLAMA_URL}..."

# docker-compose.yml (el stack default) también publica el puerto 11434 —
# si ese contenedor sigue corriendo, todo lo de abajo "pasa" igual, pero en
# realidad seguirías hablando con el Ollama lento de Docker, no el nativo.
if command -v docker >/dev/null 2>&1 && docker ps --filter "name=babel-ollama" --format '{{.Names}}' 2>/dev/null | grep -q babel-ollama; then
  echo ""
  echo "⚠️  El contenedor 'babel-ollama' (de docker-compose.yml) sigue corriendo"
  echo "   y también ocupa el puerto 11434 — cualquier chequeo de acá abajo que"
  echo "   'pase' puede en realidad estar hablando con ESE Ollama (el lento, en"
  echo "   Docker), no con uno nativo de verdad."
  echo "   Corré 'docker compose down' primero si querés usar el nativo."
  echo ""
fi

if ! curl -s -m 3 "${OLLAMA_URL}/api/version" > /dev/null 2>&1; then
  echo ""
  echo "❌ No se pudo conectar a Ollama en ${OLLAMA_URL}."
  echo ""
  echo "   Instalá Ollama nativo (no en Docker) desde https://ollama.com/download"
  echo "   y confirmá que esté corriendo (la app queda en la barra de menú/system"
  echo "   tray, o corré 'ollama serve' manualmente)."
  exit 1
fi

echo "✅ Ollama está corriendo."

if ! ollama list 2>/dev/null | grep -q "^${MODEL}"; then
  echo ""
  echo "❌ El modelo '${MODEL}' todavía no está pulleado."
  echo ""
  echo "   Corré: ollama pull ${MODEL}"
  echo "   (usa la GPU del sistema automáticamente si Ollama la detecta)"
  exit 1
fi

echo "✅ Modelo '${MODEL}' disponible."
echo ""
echo "Todo listo. Ahora podés levantar:"
echo "  docker compose -f docker-compose.local-ollama.yml up -d --build"

#!/usr/bin/env bash
# Descarga (o actualiza) el modelo Gemma usado para inferencia dentro del
# contenedor de Ollama ya levantado por docker-compose.
#
# Uso:
#   ./scripts/pull_model.sh [modelo]
#
# Si no se pasa modelo, usa $OLLAMA_MODEL o gemma4:e2b por defecto.

set -euo pipefail

MODEL="${1:-${OLLAMA_MODEL:-gemma4:e2b}}"

echo "Descargando modelo '${MODEL}' en el contenedor babel-ollama..."
docker compose exec ollama ollama pull "${MODEL}"
echo "Listo. Modelos disponibles:"
docker compose exec ollama ollama list

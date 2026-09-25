#!/usr/bin/env bash
# Empuja un archivo de audio/video local al ingest RTMP del backend, a
# velocidad real (-re), simulando lo que haría OBS. Útil para validar el
# pipeline end-to-end sin depender de una sala física.
#
# Uso:
#   ./scripts/push_test_stream.sh path/al/archivo.wav [host] [puerto]

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Uso: $0 <archivo-de-audio-o-video> [host=localhost] [puerto=1935]" >&2
  exit 1
fi

INPUT_FILE="$1"
HOST="${2:-localhost}"
PORT="${3:-1935}"

echo "Empujando '${INPUT_FILE}' a rtmp://${HOST}:${PORT}/live ..."
ffmpeg -re -i "${INPUT_FILE}" -c:a aac -f flv "rtmp://${HOST}:${PORT}/live"

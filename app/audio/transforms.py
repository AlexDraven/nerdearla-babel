import base64
import io
import wave

SAMPLE_WIDTH_BYTES = 2  # s16le
CHANNELS = 1


def pcm_to_wav_base64(pcm_bytes: bytes, sample_rate: int) -> str:
    """Envuelve un buffer PCM crudo (s16le/mono, ya normalizado por FFmpeg en
    la ingesta) en un header WAV válido en memoria y lo devuelve en base64,
    listo para el bloque `input_audio` de la API OpenAI-compatible de Ollama.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return base64.b64encode(buf.getvalue()).decode("ascii")

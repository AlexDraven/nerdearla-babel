import base64
import io
import math
import wave
from array import array

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


def pcm_rms(pcm_bytes: bytes) -> float:
    """RMS normalizado (0..1) de un buffer PCM s16le mono — gate de silencio
    antes de llamar a Ollama (ver InferencePipeline._process_chunk): un
    modelo multimodal chico como gemma4:e2b, ante audio silencioso o solo
    ruido de piso, a veces "alucina" una frase plausible en vez de devolver
    texto vacío (la regla del prompt que pide vacío en silencio no es 100%
    confiable en la práctica). Cortar acá, antes de mandar el chunk, es
    determinístico y de paso ahorra una llamada de inferencia entera."""
    if not pcm_bytes:
        return 0.0
    if len(pcm_bytes) % 2:
        # chunk parcial (ej. el último, cortado por un EOF/stop a mitad de
        # frame) — array("h", ...) exige un múltiplo de 2 bytes.
        pcm_bytes = pcm_bytes[:-1]
        if not pcm_bytes:
            return 0.0
    samples = array("h", pcm_bytes)  # s16le -> int16 con signo
    if not samples:
        return 0.0
    sum_squares = sum(s * s for s in samples)
    rms = math.sqrt(sum_squares / len(samples))
    return rms / 32768.0

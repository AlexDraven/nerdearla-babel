import base64
import wave
import io

from app.audio.transforms import CHANNELS, SAMPLE_WIDTH_BYTES, pcm_to_wav_base64


def test_pcm_to_wav_base64_round_trip():
    sample_rate = 16000
    # 0.5s de PCM s16le mono "silencio"
    pcm_bytes = b"\x00\x00" * int(sample_rate * 0.5)

    encoded = pcm_to_wav_base64(pcm_bytes, sample_rate=sample_rate)
    decoded_wav = base64.b64decode(encoded)

    with wave.open(io.BytesIO(decoded_wav), "rb") as wav_file:
        assert wav_file.getnchannels() == CHANNELS
        assert wav_file.getsampwidth() == SAMPLE_WIDTH_BYTES
        assert wav_file.getframerate() == sample_rate
        assert wav_file.readframes(wav_file.getnframes()) == pcm_bytes


def test_pcm_to_wav_base64_is_valid_base64():
    encoded = pcm_to_wav_base64(b"\x01\x02\x03\x04", sample_rate=16000)
    # no debe lanzar excepción
    base64.b64decode(encoded, validate=True)

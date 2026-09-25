import base64
import math
import wave
import io
from array import array

import pytest

from app.audio.transforms import CHANNELS, SAMPLE_WIDTH_BYTES, pcm_rms, pcm_to_wav_base64


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


def test_pcm_rms_is_zero_for_digital_silence():
    assert pcm_rms(b"\x00\x00" * 8000) == 0.0


def test_pcm_rms_is_empty_bytes_safe():
    assert pcm_rms(b"") == 0.0


def test_pcm_rms_ignores_a_trailing_odd_byte():
    # un chunk cortado a mitad de frame (ej. EOF a mitad de escritura) no
    # debe explotar — se descarta el último byte suelto.
    assert pcm_rms(b"\x00\x00\x00") == 0.0


def test_pcm_rms_matches_known_amplitude_sine_wave():
    # onda senoidal a mitad de escala: RMS teórico = amplitud / sqrt(2)
    amplitude = 16384
    samples = array("h", [round(amplitude * math.sin(i * 0.1)) for i in range(2000)])
    expected_rms = (amplitude / math.sqrt(2)) / 32768.0

    assert pcm_rms(samples.tobytes()) == pytest.approx(expected_rms, rel=0.05)


def test_pcm_rms_low_amplitude_noise_is_much_smaller_than_speech():
    # ruido de piso muy bajo (± unos pocos LSB) vs. algo parecido a voz
    # (amplitud alta) — confirma que el RMS separa bien ambos casos, la base
    # del gate de silencio en InferencePipeline._process_chunk.
    noise = array("h", [3, -2, 1, -3, 2, -1] * 500).tobytes()
    speech_like = array("h", [round(20000 * math.sin(i * 0.3)) for i in range(3000)]).tobytes()

    assert pcm_rms(noise) < 0.001
    assert pcm_rms(speech_like) > 0.3

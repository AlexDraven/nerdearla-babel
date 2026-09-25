import pytest

from app.audio.ffmpeg_ingest import FFmpegIngest


def test_build_cmd_rtmp():
    ingest = FFmpegIngest(protocol="rtmp", host="0.0.0.0", port=1935, sample_rate=16000)
    cmd = ingest._build_cmd()

    assert "-listen" in cmd
    assert "rtmp://0.0.0.0:1935/live" in cmd
    assert cmd[-1] == "pipe:1"


def test_build_cmd_srt():
    ingest = FFmpegIngest(protocol="srt", host="0.0.0.0", port=9998, sample_rate=16000)
    cmd = ingest._build_cmd()

    assert "srt://0.0.0.0:9998?mode=listener" in cmd


def test_build_cmd_file_mode_with_loop():
    ingest = FFmpegIngest(
        protocol="file", host="0.0.0.0", port=0, sample_rate=16000,
        file_path="tests/fixtures/sample_audio_5s.wav", loop=True,
    )
    cmd = ingest._build_cmd()

    assert "-re" in cmd
    assert "-stream_loop" in cmd
    assert cmd[cmd.index("-stream_loop") + 1] == "-1"
    assert "tests/fixtures/sample_audio_5s.wav" in cmd


def test_build_cmd_file_mode_without_loop():
    ingest = FFmpegIngest(
        protocol="file", host="0.0.0.0", port=0, sample_rate=16000,
        file_path="tests/fixtures/sample_audio_5s.wav", loop=False,
    )
    cmd = ingest._build_cmd()

    assert "-stream_loop" not in cmd
    assert "-re" in cmd


def test_build_cmd_file_mode_requires_file_path():
    ingest = FFmpegIngest(protocol="file", host="0.0.0.0", port=0, sample_rate=16000, file_path=None)
    with pytest.raises(ValueError):
        ingest._build_cmd()


def test_build_cmd_unsupported_protocol():
    ingest = FFmpegIngest(protocol="carrier-pigeon", host="0.0.0.0", port=0, sample_rate=16000)
    with pytest.raises(ValueError):
        ingest._build_cmd()

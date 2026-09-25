import pytest

from app.audio.ffmpeg_ingest import FFmpegIngest


class FakeStdin:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.written: list[bytes] = []
        self.drained = 0

    def write(self, data: bytes) -> None:
        if self.fail:
            raise BrokenPipeError("pipe roto (simulado)")
        self.written.append(data)

    async def drain(self) -> None:
        self.drained += 1


class FakeProc:
    def __init__(self, stdin: FakeStdin | None, returncode: int | None = None):
        self.stdin = stdin
        self.returncode = returncode


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


def test_build_cmd_mic_reads_webm_from_stdin():
    ingest = FFmpegIngest(protocol="mic", host="0.0.0.0", port=0, sample_rate=16000)
    cmd = ingest._build_cmd()

    i_index = cmd.index("-i")
    assert cmd[i_index - 1] == "webm"  # -f webm justo antes de -i pipe:0
    assert cmd[i_index + 1] == "pipe:0"
    assert cmd[-1] == "pipe:1"


async def test_write_sends_bytes_to_stdin_and_drains():
    ingest = FFmpegIngest(protocol="mic", host="0.0.0.0", port=0, sample_rate=16000)
    stdin = FakeStdin()
    ingest._proc = FakeProc(stdin=stdin, returncode=None)  # type: ignore[assignment]

    await ingest.write(b"algunos bytes de audio")

    assert stdin.written == [b"algunos bytes de audio"]
    assert stdin.drained == 1


async def test_write_is_noop_without_a_running_process():
    ingest = FFmpegIngest(protocol="mic", host="0.0.0.0", port=0, sample_rate=16000)

    await ingest.write(b"no deberia lanzar")  # ingest._proc es None


async def test_write_is_noop_when_process_already_exited():
    ingest = FFmpegIngest(protocol="mic", host="0.0.0.0", port=0, sample_rate=16000)
    ingest._proc = FakeProc(stdin=FakeStdin(), returncode=0)  # type: ignore[assignment]

    await ingest.write(b"no deberia lanzar")  # returncode no es None


async def test_write_swallows_broken_pipe():
    ingest = FFmpegIngest(protocol="mic", host="0.0.0.0", port=0, sample_rate=16000)
    ingest._proc = FakeProc(stdin=FakeStdin(fail=True), returncode=None)  # type: ignore[assignment]

    await ingest.write(b"esto va a fallar adentro, no afuera")  # no debe propagar la excepción

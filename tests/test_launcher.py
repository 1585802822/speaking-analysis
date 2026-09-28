"""scripts/launcher.py 单元测试（全 mock，不真正启动服务）."""

from __future__ import annotations

import socket
import sys
import urllib.error
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import launcher  # noqa: E402


class TestFindPython:
    def test_prefers_venv_python(self, tmp_path: Path) -> None:
        venv_python = tmp_path / ".venv" / "Scripts" / "python.exe"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()
        assert launcher.find_python(tmp_path) == [str(venv_python)]

    def test_falls_back_to_uv(self, tmp_path: Path) -> None:
        assert launcher.find_python(tmp_path) == ["uv", "run", "python"]


class TestIsPortInUse:
    @staticmethod
    def _free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_free_port(self) -> None:
        assert launcher.is_port_in_use("127.0.0.1", self._free_port()) is False

    def test_occupied_port(self) -> None:
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            assert launcher.is_port_in_use("127.0.0.1", port) is True


class TestWaitReady:
    def test_ready_on_http_response(self) -> None:
        resp = mock.MagicMock()
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda *a: False
        with mock.patch.object(launcher.urllib.request, "urlopen", return_value=resp):
            assert launcher.wait_ready("127.0.0.1", 8000, timeout=1.0) is True

    def test_timeout_when_never_ready(self) -> None:
        with (
            mock.patch.object(
                launcher.urllib.request,
                "urlopen",
                side_effect=urllib.error.URLError("refused"),
            ),
            mock.patch.object(launcher.time, "sleep"),
        ):
            assert launcher.wait_ready("127.0.0.1", 8000, timeout=0.1) is False


class TestBuildCommands:
    def test_both_components(self) -> None:
        cmds = launcher.build_commands(["python"], "127.0.0.1", 8000, True, True)
        assert cmds["web"] == [
            "python",
            "-m",
            "src.cli",
            "web",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ]
        assert cmds["watch"] == ["python", "-m", "src.cli", "watch"]

    def test_skip_components(self) -> None:
        assert "web" not in launcher.build_commands(["python"], "h", 1, False, True)
        assert "watch" not in launcher.build_commands(["python"], "h", 1, True, False)


class TestParseArgs:
    def test_defaults(self) -> None:
        args = launcher.parse_args([])
        assert (args.host, args.port) == ("127.0.0.1", 8000)
        assert not (args.no_web or args.no_watch or args.no_browser)

    def test_switches(self) -> None:
        args = launcher.parse_args(["--port", "9000", "--no-watch", "--no-browser"])
        assert args.port == 9000
        assert args.no_watch and args.no_browser
        assert not args.no_web


class TestMainGuards:
    def test_no_components_returns_2(self, capsys: pytest.CaptureFixture) -> None:
        assert launcher.main(["--no-web", "--no-watch"]) == 2
        assert "没有可启动的组件" in capsys.readouterr().out

    def test_occupied_port_returns_2(self, capsys: pytest.CaptureFixture) -> None:
        with mock.patch.object(launcher, "is_port_in_use", return_value=True):
            assert launcher.main([]) == 2
        assert "已被占用" in capsys.readouterr().out


class TestStartBat:
    """start.bat 必须为纯 ASCII + CRLF，避免 cmd 按 GBK 解析 UTF-8 中文时字节错位."""

    START_BAT = Path(__file__).resolve().parent.parent / "scripts" / "start.bat"

    def test_start_bat_is_ascii(self) -> None:
        data = self.START_BAT.read_bytes()
        assert all(b < 128 for b in data), "start.bat 必须为纯 ASCII（无中文），否则 cmd 解析会错位"

    def test_start_bat_uses_crlf(self) -> None:
        data = self.START_BAT.read_bytes()
        assert b"\r\n" in data
        assert b"\n" not in data.replace(b"\r\n", b"")

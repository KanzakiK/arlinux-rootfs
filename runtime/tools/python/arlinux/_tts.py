"""Fire-and-forget, interruptible Edge TTS implementation."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import uuid


def _paths() -> tuple[str, str]:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    os.makedirs(runtime, exist_ok=True)
    return (
        os.path.join(runtime, "arlinux-tts-state.json"),
        os.path.join(runtime, "arlinux-tts-state.lock"),
    )


def _locked_update(callback):
    state_path, lock_path = _paths()
    with open(lock_path, "a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            try:
                with open(state_path, encoding="utf-8") as state_file:
                    state = json.load(state_file)
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                state = {}
            result, replacement = callback(state)
            if replacement is not None:
                with open(state_path, "w", encoding="utf-8") as state_file:
                    json.dump(replacement, state_file)
                os.chmod(state_path, 0o600)
            return result
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _claim(token: str) -> int:
    def update(state):
        return int(state.get("worker_pid") or 0), {
            "token": token,
            "worker_pid": 0,
        }

    return _locked_update(update)


def _set_worker(token: str, pid: int) -> bool:
    def update(state):
        if state.get("token") != token:
            return False, None
        return True, {"token": token, "worker_pid": pid}

    return _locked_update(update)


def _is_current(token: str) -> bool:
    return _locked_update(lambda state: (state.get("token") == token, None))


def _release(token: str, pid: int) -> None:
    def update(state):
        if state.get("token") == token and int(state.get("worker_pid") or 0) == pid:
            return None, {}
        return None, None

    _locked_update(update)


def _terminate_worker(pid: int) -> None:
    if pid <= 0:
        return
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as command_file:
            command = command_file.read().replace(b"\0", b" ")
        if b"arlinux._tts" not in command or b"--worker" not in command:
            return
        os.killpg(pid, signal.SIGTERM)
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        pass


def speak(
    text: str,
    *,
    voice: str,
    rate: str,
    volume: str,
    pitch: str,
) -> bool:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")

    token = uuid.uuid4().hex
    runtime = os.path.dirname(_paths()[0])
    request_path = os.path.join(runtime, "arlinux-tts-request-%s.json" % token)
    with open(request_path, "x", encoding="utf-8") as request_file:
        json.dump(
            {
                "text": text.strip(),
                "voice": voice,
                "rate": rate,
                "volume": volume,
                "pitch": pitch,
            },
            request_file,
            ensure_ascii=False,
        )
    os.chmod(request_path, 0o600)

    previous_pid = _claim(token)
    _terminate_worker(previous_pid)
    try:
        worker = subprocess.Popen(
            [sys.executable, "-m", "arlinux._tts", "--worker", request_path, token],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception:
        _release(token, 0)
        try:
            os.unlink(request_path)
        except FileNotFoundError:
            pass
        raise
    if not _set_worker(token, worker.pid):
        _terminate_worker(worker.pid)
        return False
    threading.Thread(target=worker.wait, daemon=True).start()
    return True


async def _run_worker(request_path: str, token: str) -> None:
    media_path = ""
    try:
        with open(request_path, encoding="utf-8") as request_file:
            request = json.load(request_file)
        os.unlink(request_path)

        import edge_tts

        with tempfile.NamedTemporaryFile(
            prefix="arlinux-tts-%s-" % token, suffix=".mp3", delete=False
        ) as media:
            media_path = media.name
        communicate = edge_tts.Communicate(
            request["text"],
            request["voice"],
            rate=request["rate"],
            volume=request["volume"],
            pitch=request["pitch"],
        )
        await communicate.save(media_path)
        if not _is_current(token):
            return
        player = await asyncio.create_subprocess_exec(
            "mpg123",
            "-q",
            "-o",
            "pulse",
            media_path,
            stdin=subprocess.DEVNULL,
        )
        await player.wait()
    finally:
        try:
            os.unlink(request_path)
        except FileNotFoundError:
            pass
        if media_path:
            try:
                os.unlink(media_path)
            except FileNotFoundError:
                pass
        _release(token, os.getpid())


def _main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] != "--worker":
        return 2
    asyncio.run(_run_worker(sys.argv[2], sys.argv[3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

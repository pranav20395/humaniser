"""Start llama-server with the flags the model needs, so `humaniser serve --model FILE` is one command."""

import shutil
import subprocess
import sys
from pathlib import Path

from .prompt import CONTEXT_TOKENS


class LlamaServerProcess:
    def __init__(self, model: Path, binary: str = "llama-server", host: str = "127.0.0.1", port: int = 8080,
                 gpu_layers: int = 99, extra_args: list[str] | None = None):
        exe = shutil.which(binary) or (binary if Path(binary).is_file() else None)
        if not exe:
            sys.exit(f"error: {binary!r} not found. Install llama.cpp (see README) or pass --llama-server PATH.")
        if not model.is_file():
            sys.exit(f"error: model file {model} not found. Run `python -m humaniser download` first.")
        self.url = f"http://{host}:{port}"
        # -np 1: the whole 8192-token context goes to one request (newer builds split it across slots).
        self.args = [exe, "-m", str(model), "-c", str(CONTEXT_TOKENS), "-np", "1", "-ngl", str(gpu_layers),
                     "--host", host, "--port", str(port), *(extra_args or [])]
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        print("starting:", " ".join(self.args), file=sys.stderr)
        self.proc = subprocess.Popen(self.args)

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def returncode(self) -> int | None:
        return self.proc.poll() if self.proc else None

    def stop(self) -> None:
        if self.running():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

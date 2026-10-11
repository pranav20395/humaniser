"""Command line: `python -m humaniser download` and `python -m humaniser serve`."""

import argparse
import sys
from pathlib import Path

from .download import QUANTS


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="humaniser", description="Web interface for the jialinyyzz/humanizer model.")
    sub = ap.add_subparsers(dest="command", required=True)

    dl = sub.add_parser("download", help="download a GGUF file of the model")
    dl.add_argument("--quant", default="auto", choices=["auto", *QUANTS],
                    help="file to download; auto picks by this machine's memory (default)")
    dl.add_argument("--dir", type=Path, default=Path("models"), help="where to save it (default: ./models)")

    sv = sub.add_parser("serve", help="start the web interface")
    sv.add_argument("--host", default="127.0.0.1", help="web interface address (default 127.0.0.1)")
    sv.add_argument("--port", type=int, default=8000, help="web interface port (default 8000)")
    model = sv.add_argument_group("run the model here (starts llama-server for you)")
    model.add_argument("--model", type=Path, help="GGUF file to load, e.g. models/humanizer-12b-Q4_K_M.gguf")
    model.add_argument("--llama-server", default="llama-server", help="llama-server binary (default: from PATH)")
    model.add_argument("--llama-port", type=int, default=8080, help="port for llama-server (default 8080)")
    model.add_argument("--gpu-layers", type=int, default=99, help="layers to offload to the GPU (default 99: all)")
    remote = sv.add_argument_group("or use a server that is already running")
    remote.add_argument("--backend", default="llama.cpp", choices=["llama.cpp", "openai"],
                        help="llama.cpp: llama-server /completion (default); "
                             "openai: an OpenAI-style /v1/completions server such as vLLM or LM Studio")
    remote.add_argument("--backend-url", default="http://127.0.0.1:8080", help="server URL (default http://127.0.0.1:8080)")
    remote.add_argument("--api-model", help="model name for --backend openai (default: the server's first model)")
    remote.add_argument("--api-key", help="API key for --backend openai, if the server needs one")

    args = ap.parse_args(argv)
    if args.command == "download":
        from .download import download

        path = download(args.quant, args.dir)
        print(f"saved {path}\nnext: python -m humaniser serve --model {path}")
        return

    import uvicorn

    from .backends import make_backend
    from .launcher import LlamaServerProcess
    from .server import create_app

    process = None
    if args.model:
        if args.backend != "llama.cpp":
            sys.exit("error: --model starts llama-server; it cannot be combined with --backend openai")
        process = LlamaServerProcess(args.model, args.llama_server, port=args.llama_port, gpu_layers=args.gpu_layers)
        args.backend_url = process.url
    backend = make_backend(args.backend, args.backend_url, model=args.api_model, api_key=args.api_key)
    app = create_app(backend, process)
    if process:
        process.start()
    print(f"\n  Humaniser: open http://{args.host}:{args.port} in your browser\n", file=sys.stderr)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        if process:
            process.stop()


if __name__ == "__main__":
    main()

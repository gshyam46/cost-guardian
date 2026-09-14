"""Launch supported Python entry points without modifying application files."""
import argparse
import json
import os
from pathlib import Path
import re
import runpy
import sys

from .configuration import Configuration, ConfigurationError
from .instrumentation import Instrumentation, detected_adapters


def _diagnostic(code):
    print(json.dumps({"sillage": "diagnostic", "code": code}), file=sys.stderr)


def _command(command):
    if command and command[0] == "--":
        command = command[1:]
    if len(command) < 2:
        raise ConfigurationError("expected_python_script_or_module")
    executable = command[0]
    if executable not in ("python", "python3", "python.exe", "python3.exe", sys.executable):
        raise ConfigurationError("target_must_use_current_python")
    rest = command[1:]
    if rest[0] == "-m":
        if len(rest) < 2 or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", rest[1]):
            raise ConfigurationError("invalid_python_module")
        mode, target, arguments = "module", rest[1], rest[2:]
        if target in ("uvicorn", "uvicorn.__main__"):
            explicit_workers = False
            for index, item in enumerate(arguments):
                if item == "--reload" or item.startswith("--reload="):
                    raise ConfigurationError("reload_not_supported")
                if item.startswith("--workers=") and item != "--workers=1":
                    raise ConfigurationError("multiple_workers_not_supported")
                if item == "--workers" and (index + 1 == len(arguments) or arguments[index + 1] != "1"):
                    raise ConfigurationError("multiple_workers_not_supported")
                explicit_workers = explicit_workers or item == "--workers" or item.startswith("--workers=")
            # Click's UVICORN_* options and Uvicorn's WEB_CONCURRENCY fallback
            # can create child processes even without explicit launcher flags.
            reload = os.environ.get("UVICORN_RELOAD", "false").lower()
            if reload not in ("false", "0", "no", "off", ""):
                raise ConfigurationError("reload_not_supported")
            if not explicit_workers:
                workers = os.environ.get("UVICORN_WORKERS") or os.environ.get("WEB_CONCURRENCY", "1")
                if workers != "1":
                    raise ConfigurationError("multiple_workers_not_supported")
    else:
        if rest[0].startswith("-"):
            raise ConfigurationError("unsupported_python_launch_option")
        script = Path(rest[0])
        if not script.is_file() or script.suffix.lower() != ".py":
            raise ConfigurationError("python_script_not_found")
        mode, target, arguments = "script", str(script.resolve()), rest[1:]
    return mode, target, arguments


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sillage-run",
        description="Observe supported AI SDK calls in the current Python process.",
        epilog="Use: sillage-run -- python app.py | sillage-run -- python -m uvicorn server:app. "
               "Set SILLAGE_URL and SILLAGE_INGEST_KEY in the environment; never pass keys as arguments.")
    parser.add_argument("--check", action="store_true", help="Validate local settings and versions; make no network calls")
    parser.add_argument("--version", action="version", version="sillage-observe 0.2.0")
    parser.add_argument("--instrumentation", choices=("native", "openinference"), default="native",
                        help="Capture mechanism; native retains the original dependency-free adapters")
    parser.add_argument("--instrumentors", default=None,
                        help="One OpenInference layer: auto, openai, litellm or langchain")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        config = Configuration.from_env()
        if args.instrumentation == "native" and args.instrumentors is not None:
            raise ConfigurationError("instrumentors_require_openinference")
        if args.instrumentation == "openinference":
            from .openinference_runtime import detected_openinference, select_instrumentor
            detected = detected_openinference()
            selected = select_instrumentor(args.instrumentors or "auto", detected)
        if args.check:
            if args.command:
                raise ConfigurationError("check_does_not_launch_application")
            adapters = detected_adapters() if args.instrumentation == "native" else detected["adapters"]
            ready = (any(info["supported"] for info in adapters.values())
                     if args.instrumentation == "native" else selected is not None)
            print(json.dumps({"sillage": "local_check", "configuration": "valid",
                              "instrumentation_ready": ready,
                              "collector_checked": False, "connected": False,
                              "adapters": adapters, "process_scope": "single_process",
                              "instrumentation": args.instrumentation,
                              **({"instrumentors_selected": [selected] if selected else [],
                                  "dependencies": detected["dependencies"]}
                                 if args.instrumentation == "openinference" else {})}))
            if not ready:
                _diagnostic("no_supported_sdk_installed" if args.instrumentation == "native"
                            else "no_supported_openinference_stack")
            return 0 if ready else 3
        if args.instrumentation == "openinference" and selected is None:
            _diagnostic("no_supported_openinference_stack")
            return 3
        mode, target, arguments = _command(args.command)
    except ConfigurationError as error:
        _diagnostic(str(error))
        return 2

    try:
        if args.instrumentation == "openinference":
            from .openinference_runtime import OpenInferenceRuntime
            instrument = OpenInferenceRuntime(config, instrumentor=selected, diagnostic=_diagnostic).install()
        else:
            instrument = Instrumentation(config, diagnostic=_diagnostic).install()
    except ConfigurationError as error:
        _diagnostic(str(error))
        return 2
    _diagnostic("ready_to_instrument_supported_calls")
    previous_argv, previous_path = sys.argv, sys.path[:]
    try:
        sys.argv = [target, *arguments]
        if mode == "script":
            sys.path.insert(0, str(Path(target).parent))
            runpy.run_path(target, run_name="__main__")
        else:
            # Python -m makes the working directory importable; a console script
            # normally has the venv's Scripts/bin directory at sys.path[0].
            sys.path.insert(0, str(Path.cwd()))
            runpy.run_module(target, run_name="__main__", alter_sys=True)
        return 0
    finally:
        sys.argv, sys.path[:] = previous_argv, previous_path
        result = instrument.close(timeout=3)
        if result is None:
            _diagnostic("no_supported_calls_observed")
        elif result.get("confirmed") is not True:
            _diagnostic("export_shutdown_unconfirmed")


if __name__ == "__main__":
    raise SystemExit(main())

"""Explicit package checks, bootstrap and supervised roles; no-argument help is inert."""
import argparse
import asyncio
import json
import logging


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("check", help="Validate configuration/static assets without network access")
    commands.add_parser("bootstrap", help="Initialize one compatible isolated database")
    run = commands.add_parser("run", help="Run a bootstrapped role")
    run.add_argument("role", choices=("api", "worker", "notifications"))
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0
    from .errors import DeploymentError
    try:
        from .configuration import prepare_environment, load_configuration
        prepare_environment()
        configuration = load_configuration()
        if arguments.command == "check":
            result = {"status": "configured", "command": "check"}
        elif arguments.command == "bootstrap":
            from .bootstrap import bootstrap
            from .runtime import database
            async def initialize():
                client, db = database(configuration)
                try:
                    await bootstrap(db, configuration)
                finally:
                    client.close()
            asyncio.run(initialize())
            result = {"status": "ready", "command": "bootstrap"}
        else:
            from .runtime import run_role
            logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            asyncio.run(run_role(configuration, arguments.role))
            result = {"status": "stopped", "command": "run", "role": arguments.role}
    except DeploymentError as error:
        result = {"status": "failed", "code": error.code}
    except BaseException:
        result = {"status": "failed", "code": "deployment_unavailable"}
    print(json.dumps(result))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

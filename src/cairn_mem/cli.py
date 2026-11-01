"""CLI de cairn-mem. M0: esqueleto. Se implementa por hitos (ver PLAN.md)."""
import argparse
import sys

COMMANDS = ["init", "save", "search", "get", "archive", "check", "render", "rebuild"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="cairn", description="Memoria persistente para agentes")
    p.add_argument("command", choices=COMMANDS)
    p.add_argument("args", nargs=argparse.REMAINDER)
    ns = p.parse_args(argv)
    print(f"cairn {ns.command}: no implementado todavía (ver PLAN.md)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

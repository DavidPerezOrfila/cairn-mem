"""Hook de Claude Code (S28.1): una sesión, como máximo un empujón.

SessionStart fija los saves iniciales y el offset del transcript de cada sesión. Stop
exige una herramienta de guardado de proyecto y un evento nuevo en ese proyecto; la
línea base de instalación es el fallback para sesiones ya en marcha.
"""
import json
import os
import re
import shlex
import sys
from pathlib import Path

NUDGE = "Al cerrar: si esta conversación te dio una razón que no está en el código (por qué el usuario quiere el cambio, una restricción, quién consume el dato), guárdala ahora en la memoria del proyecto con `cairn save`, con ese porqué en `--why` y un `--topic` estable. Una sola memoria. Si no hay ninguna razón así, no hagas nada."
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,200}")
COMMAND_SEPARATORS = {";", "&", "&&", "|", "||", "\n"}
CAIRN_COMMANDS = {"cairn", "cairn-mem", "cairn.exe", "cairn-mem.exe"}


def _saves(directory: Path) -> int:
    try:
        text = (directory / ".cairn" / "events.jsonl").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return 0
    count = 0
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("op") == "save":
            count += 1
    return count


def _read_count(path: Path) -> int | None:
    try:
        count = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return count if count >= 0 else None


def _command_name(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        token = token[1:-1]
    return token.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _save_segment(tokens: list[str]) -> bool:
    if not tokens:
        return False
    index = 0
    name = _command_name(tokens[index])
    if name in {"uv", "pipx"} and len(tokens) > 1 and tokens[1] == "run":
        index = 2
        while index < len(tokens) and tokens[index].startswith("-"):
            index += 1
        if index >= len(tokens):
            return False
        name = _command_name(tokens[index])
    return (
        name in CAIRN_COMMANDS
        and index + 1 < len(tokens)
        and tokens[index + 1] == "save"
        and "--personal" not in tokens[index + 2 :]
    )


def _project_tool_save(name: object, tool_input: object) -> bool | None:
    if name == "mcp__cairn__save":
        if not isinstance(tool_input, dict):
            return None
        return tool_input.get("scope", "project") == "project"
    if name != "Bash":
        return False
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    return _bash_save(command) if isinstance(command, str) else None


def _bash_save(command: str) -> bool:
    try:
        lexer = shlex.shlex(command, posix=False, punctuation_chars=";&|\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return False
    segment: list[str] = []
    for token in [*tokens, ";"]:
        if token and set(token) <= COMMAND_SEPARATORS:
            if _save_segment(segment):
                return True
            segment = []
        else:
            segment.append(token)
    return False


def _transcript_save(value: object, offset: int | None = None) -> bool | None:
    if not isinstance(value, str) or not value:
        return None
    pending: dict[str, bool | None] = {}
    parsed = False
    uncertain = False
    try:
        with Path(value).expanduser().open("rb") as handle:
            if offset is not None:
                size = os.fstat(handle.fileno()).st_size
                if offset < 0 or offset > size:
                    return None
                if offset == size:
                    return False
                handle.seek(offset)
            for raw in handle:
                if not raw.strip():
                    continue
                try:
                    record = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                event = record.get("type")
                message = record.get("message")
                if event not in {"assistant", "user"} or not isinstance(message, dict):
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                parsed = True
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if event == "assistant" and block.get("type") == "tool_use":
                        identifier = block.get("id")
                        if not isinstance(identifier, str):
                            uncertain = True
                            continue
                        pending[identifier] = _project_tool_save(
                            block.get("name"), block.get("input")
                        )
                    elif event == "user" and block.get("type") == "tool_result":
                        identifier = block.get("tool_use_id")
                        if not isinstance(identifier, str) or identifier not in pending:
                            uncertain = True
                            continue
                        is_save = pending.pop(identifier)
                        if is_save is None:
                            uncertain = True
                        elif is_save and not block.get("is_error", False):
                            return True
    except (OSError, RuntimeError, ValueError):
        return None
    return None if uncertain or not parsed else False


def _session_transcript_save(
    state_dir: Path, session: str, value: object
) -> bool | None:
    offset_path = state_dir / f"{session}.offset"
    if offset_path.is_symlink():
        return None
    if not offset_path.exists():
        return None
    offset = _read_count(offset_path)
    if offset is None or offset < 0:
        return None
    return _transcript_save(value, offset)


def _transcript_size(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return Path(value).expanduser().stat().st_size
    except (OSError, RuntimeError, ValueError):
        return None


def _start_session(
    root: Path,
    state_dir: Path,
    session: str,
    transcript: object,
    source: object,
) -> None:
    try:
        if state_dir.is_symlink():
            return
        state_dir.mkdir(parents=True, exist_ok=True)
        baseline = state_dir / f"{session}.baseline"
        if baseline.is_symlink():
            return
        # Un resume o compact no debe convertir los saves previos en línea base.
        if not baseline.exists():
            baseline.write_text(
                f"{_saves(root)}\n", encoding="utf-8", newline="\n"
            )
        if source == "compact":
            return
        offset = state_dir / f"{session}.offset"
        if offset.is_symlink():
            return
        size = _transcript_size(transcript)
        if size is None:
            offset.unlink(missing_ok=True)
            return
        offset.write_text(f"{size}\n", encoding="utf-8", newline="\n")
    except OSError:
        return


def _append_log(path: Path, session: str) -> None:
    try:
        if path.is_symlink():
            return
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o666)
        try:
            os.write(descriptor, (session + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)
    except OSError:
        # El log es evidencia del banco, no una condición para empujar.
        pass


def main() -> None:
    try:
        state = json.load(sys.stdin)
    except (OSError, ValueError):
        return
    if not isinstance(state, dict):
        return
    session = state.get("session_id")
    if not isinstance(session, str) or SESSION_ID.fullmatch(session) is None:
        return

    root = Path(__file__).resolve().parents[2]
    state_dir = root / ".cairn-nudge"
    event = state.get("hook_event_name")
    if event == "SessionStart":
        _start_session(
            root, state_dir, session, state.get("transcript_path"), state.get("source")
        )
        return
    if event != "Stop" or state.get("stop_hook_active"):
        return

    marker = state_dir / f"{session}.seen"
    try:
        if state_dir.is_symlink() or marker.is_symlink() or marker.exists():
            return
        saved = _session_transcript_save(
            state_dir, session, state.get("transcript_path")
        )
        session_baseline = state_dir / f"{session}.baseline"
        if session_baseline.is_symlink():
            return
        baseline = _read_count(session_baseline)
        if baseline is None:
            global_baseline = state_dir / "baseline"
            if global_baseline.is_symlink():
                return
            baseline = _read_count(global_baseline)
        if baseline is None:
            baseline = 0
        project_saved = _saves(root) > baseline
        if project_saved and saved is not False:
            return
        state_dir.mkdir(parents=True, exist_ok=True)
        with marker.open("x", encoding="utf-8", newline="\n"):
            pass
    except OSError:
        return

    _append_log(root / ".cairn-nudge.log", session)
    print(json.dumps({"decision": "block", "reason": NUDGE}))


if __name__ == "__main__":
    main()

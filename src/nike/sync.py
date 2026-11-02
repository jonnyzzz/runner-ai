#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#   "nrc-exporter @ git+https://github.com/yasoob/nrc-exporter.git@a4447c8c65b3f0d404f8f1441fded35e83871405",
#   "filelock>=4.2.1,<5",
# ]
# [tool.uv]
# override-dependencies = ["requests>=2.33.0,<3", "selenium>=4.14,<5"]
# ///
"""Fetch Nike runs through nrc-exporter; own only local persistence and selection."""

from __future__ import annotations

import argparse
import builtins
import contextlib
import getpass
import io
import json
import logging
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import warnings
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REVISION = "a4447c8c65b3f0d404f8f1441fded35e83871405"
ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
FOLDER = re.compile(r"run-\d{4}-\d{2}-\d{2}-nike-(.+)\Z")
IGNORE = ("/strava-tokens.json", "/nike-tokens.json", "/strava-mcp/", "/.sync-state/")
SECRETS: set[str] = set()


class SyncError(Exception):
    """A safe-to-display error; never include credentials or upstream bodies."""


class Excluded(Exception):
    pass


class SafeOutput:
    """Capture complete output lines, removing credentials before either sink."""

    def __init__(self, console, log):
        self.console, self.log = console, log
        self.pending = ""

    def emit(self, text):
        for secret in sorted(SECRETS, key=len, reverse=True):
            text = text.replace(secret, "[REDACTED]")
        self.console.write(text)
        self.log.write(text)

    def write(self, text):
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            self.emit(line + "\n")
        return len(text)

    def flush(self):
        if self.pending:
            self.emit(self.pending)
            self.pending = ""
        self.console.flush()
        self.log.flush()

    def isatty(self):
        return self.console.isatty()


@contextlib.contextmanager
def private_log(state_root: Path, root: Path, enabled: bool):
    if not enabled:
        yield None
        return
    directory = state_root / "logs"
    private_directory(directory, root)
    prefix = f"fetch-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-"
    fd, filename = tempfile.mkstemp(prefix=prefix, suffix=".log", dir=directory)
    with os.fdopen(fd, "w", encoding="utf-8") as log:
        out, err = SafeOutput(sys.stdout, log), SafeOutput(sys.stderr, log)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            print(f"Log file: {filename}", flush=True)
            try:
                yield Path(filename)
            except SyncError as error:
                message = str(error)
                for secret in SECRETS:
                    message = message.replace(secret, "[REDACTED]")
                log.write(f"Error: {message}\n")
                raise
            except (OSError, KeyboardInterrupt):
                log.write("Run interrupted or local file/process operation failed.\n")
                raise
            finally:
                out.flush()
                err.flush()


@contextlib.contextmanager
def private_library_input():
    """Keep the pinned library's confirmation, but hide its subsequent token input."""
    original = builtins.input
    calls = 0

    def receive(prompt=""):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original(prompt)
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                token = getpass.getpass("Nike access token (hidden): ")
            except getpass.GetPassWarning:
                raise SyncError(
                    "A terminal supporting hidden token input is required."
                ) from None
        if token:
            SECRETS.add(token)
        return token

    builtins.input = receive
    try:
        yield
    finally:
        builtins.input = original


def identifier(value: object) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise SyncError("Invalid account label or activity ID.")
    return value


def regular_file(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise SyncError(f"Expected a regular file: {path}")


def private_directory(path: Path, root: Path) -> None:
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if current.is_symlink():
            raise SyncError(f"Refusing a symlink in the private state path: {current}")
        current.mkdir(mode=0o700, exist_ok=True)
        if os.name == "posix":
            current.chmod(0o700)


def read_json(path: Path) -> dict:
    regular_file(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SyncError(f"Cannot read JSON object: {path}") from None
    if not isinstance(value, dict):
        raise SyncError(f"Expected a JSON object: {path}")
    return value


def atomic_json(path: Path, value: dict) -> bool:
    regular_file(path)
    try:
        content = (
            json.dumps(
                value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
            )
            + "\n"
        ).encode("utf-8")
    except (ValueError, TypeError):
        raise SyncError(f"Cannot serialize valid JSON for {path}.") from None
    if path.exists() and path.read_bytes() == content:
        return False
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise SyncError("data/ must be a separate Git checkout; see nike.md.")
    return result.stdout.strip()


def prepare_data(root: Path) -> Path:
    if (
        not root.is_dir()
        or Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root
    ):
        raise SyncError("data/ must be a separate Git checkout; see nike.md.")
    if git(root, "ls-files", "--", "nike-tokens.json", ".sync-state/"):
        raise SyncError(
            "Nike credentials or sync state are tracked by Git; untrack them first."
        )
    ignore = root / ".gitignore"
    regular_file(ignore)
    existing = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    missing = [rule for rule in IGNORE if rule not in existing.splitlines()]
    if missing:
        with ignore.open("a", encoding="utf-8") as stream:
            if existing and not existing.endswith("\n"):
                stream.write("\n")
            stream.write("\n".join(missing) + "\n")
    for name in ("nike-tokens.json", ".sync-state/nike/probe"):
        check = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "check-ignore",
                "--quiet",
                "--no-index",
                "--",
                name,
            ],
            check=False,
        )
        if check.returncode:
            raise SyncError(
                "Credential/state exclusions are ineffective in data/.gitignore."
            )
    state_root = root / ".sync-state" / "nike"
    private_directory(state_root, root)
    return state_root


def secure_token_file(path: Path) -> None:
    regular_file(path)
    if os.name == "posix":
        path.chmod(0o600)
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise SyncError("Cannot restrict Nike token file permissions to 0600.")


def load_token(root: Path, account: str, login: bool, library) -> str:
    path = root / "nike-tokens.json"
    if path.exists():
        secure_token_file(path)
        saved = read_json(path)
        if saved.get("account") != account:
            raise SyncError("Nike token file belongs to a different account label.")
        token = saved.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise SyncError(
                "Nike token file needs a nonempty access_token; run with --login."
            )
        SECRETS.add(token)
        if not login:
            return token
    if not sys.stdin.isatty():
        raise SyncError(
            "Nike login needs an interactive terminal. Run this command with --login."
        )
    token = library.login()
    if not isinstance(token, str) or not token.strip():
        raise SyncError("The Nike library did not return a usable token.")
    SECRETS.add(token)
    atomic_json(path, {"account": account, "access_token": token})
    secure_token_file(path)
    return token


def library_worker() -> int:
    """Isolate the library so its blocking calls can be timed out without patching it."""
    logging.disable(logging.CRITICAL)
    try:
        request = json.load(sys.stdin)
        with contextlib.redirect_stdout(io.StringIO()):
            import nrc_exporter

            options = {"access_token": request["token"]}
            if request["operation"] == "list":
                result = nrc_exporter.get_activities_list(options)
            elif request["operation"] == "detail":
                result = nrc_exporter.get_activity_details(request["id"], options)
            else:
                raise ValueError("Unknown library operation")
        response = {"result": result}
    except (Exception, SystemExit) as error:  # noqa: BLE001 - sanitize third-party errors
        kind = type(error).__name__
        response = {
            "error": kind,
            "retryable": kind
            in (
                "Timeout",
                "ConnectTimeout",
                "ReadTimeout",
                "ConnectionError",
                "ChunkedEncodingError",
            ),
        }
    json.dump(response, sys.stdout, allow_nan=False)
    return 0


class NikeLibrary:
    def __init__(self, work: Path, timeout: float):
        self.work, self.timeout = work, timeout

    def login(self) -> str:
        import nrc_exporter

        logger = logging.getLogger("nrc_exporter")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.StreamHandler(sys.stderr)
        logger.addHandler(handler)
        previous = Path.cwd()
        try:
            os.chdir(self.work)
            with private_library_input():
                return nrc_exporter.get_access_token(
                    {"gecko_path": None, "manual": True, "debug": False}
                )
        except (Exception, SystemExit):  # noqa: BLE001 - keep upstream credentials out of errors
            raise SyncError(
                "Nike library login did not complete; follow its authentication instructions."
            ) from None
        finally:
            os.chdir(previous)
            logger.removeHandler(handler)

    def call(self, operation: str, token: str, activity_id: str | None = None):
        request = {"operation": operation, "token": token, "id": activity_id}
        for attempt in range(2):
            try:
                process = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "--_worker"],
                    input=json.dumps(request),
                    capture_output=True,
                    text=True,
                    cwd=self.work,
                    timeout=max(300, self.timeout)
                    if operation == "list"
                    else self.timeout,
                    check=False,
                )
                response = json.loads(process.stdout) if process.returncode == 0 else {}
            except (subprocess.TimeoutExpired, ValueError):
                response = {
                    "error": "Timeout or invalid library response",
                    "retryable": True,
                }
            if "result" in response:
                return response["result"]
            if not response.get("retryable") or attempt:
                raise SyncError(
                    "Nike library request failed. Check the connection or renew credentials with --login."
                )
            time.sleep(1)

    def list(self, token: str):
        return self.call("list", token)

    def detail(self, activity_id: str, token: str):
        return self.call("detail", token, activity_id)


def record_start(record: dict, activity_id: str) -> datetime:
    if not isinstance(record, dict) or record.get("id") != activity_id:
        raise SyncError("Library response is not the requested activity.")
    if record.get("deleted") or record.get("type") not in ("run", "jogging"):
        if record.get("type") and record.get("type") not in ("run", "jogging"):
            raise Excluded()
        if record.get("deleted"):
            raise Excluded()
        raise SyncError("Activity is missing its run classification.")
    value = record.get("start_epoch_ms")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (isinstance(value, float) and not math.isfinite(value))
    ):
        raise SyncError("Activity is missing a valid start_epoch_ms.")
    try:
        return datetime.fromtimestamp(value / 1000, UTC)
    except (OverflowError, ValueError, OSError):
        raise SyncError("Activity timestamp is outside the supported range.") from None


def local_day(record: dict, start: datetime, fallback: str | None) -> tuple[str, dict]:
    for field in ("timezone", "time_zone"):
        value = record.get(field)
        if isinstance(value, str):
            try:
                zone = ZoneInfo(value)
            except (ValueError, ZoneInfoNotFoundError):
                continue
            return start.astimezone(zone).date().isoformat(), {
                "source": field,
                "timezone": value,
            }
    if not fallback:
        raise SyncError(
            "No source timezone is available. Supply --timezone, e.g. Europe/Berlin."
        )
    return start.astimezone(ZoneInfo(fallback)).date().isoformat(), {
        "source": "configured fallback",
        "timezone": fallback,
    }


def existing_folders(root: Path) -> dict[str, Path]:
    result = {}
    for folder in root.glob("run-*-nike-*"):
        match = FOLDER.fullmatch(folder.name)
        if not match:
            continue
        activity_id = identifier(match[1])
        if folder.is_symlink() or not folder.is_dir():
            raise SyncError(f"Expected a run directory: {folder}")
        if activity_id in result:
            raise SyncError(f"Multiple Nike folders contain activity ID {activity_id}.")
        result[activity_id] = folder
    return result


def cached_record(
    activity_id: str, cache: Path, folders: dict[str, Path]
) -> dict | None:
    paths = [cache / f"{activity_id}.json"]
    if activity_id in folders:
        paths.append(folders[activity_id] / "nike.json")
    for path in paths:
        if path.is_symlink():
            raise SyncError(f"Refusing a symlink source file: {path}")
        if path.exists():
            try:
                record = read_json(path)
                record_start(record, activity_id)
                return record
            except (SyncError, Excluded):
                continue
    return None


def select_history(args, state: dict, now: datetime) -> tuple[date | None, str | None]:
    if args.all_history:
        since = None
    elif args.since:
        since = args.since
    elif "since" in state:
        try:
            since = (
                date.fromisoformat(state["since"])
                if state["since"] is not None
                else None
            )
        except (TypeError, ValueError):
            raise SyncError(
                "Sync state contains an invalid history start date."
            ) from None
    else:
        try:
            since = now.date().replace(year=now.year - 1)
        except ValueError:
            since = date(now.year - 1, 2, 28)
    if since and since > now.date():
        raise SyncError("--since must not be in the future.")
    zone = args.timezone or state.get("timezone")
    if zone:
        try:
            ZoneInfo(zone)
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            raise SyncError("Use a valid IANA timezone, e.g. Europe/Berlin.") from None
    return since, zone


def possible_duplicates(root: Path, records: list[dict]) -> list[dict]:
    candidates = []
    for path in root.glob("run-*-strava-*/strava.json"):
        if path.parent.is_symlink():
            continue
        try:
            other = read_json(path)
            start = datetime.fromisoformat(other["start_date"])
            if start.tzinfo is None:
                continue
            for record in records:
                nike_start = record_start(record, record["id"])
                if abs((nike_start - start).total_seconds()) > 180:
                    continue
                duration = record.get("active_duration_ms")
                other_duration = other.get("moving_time")
                if (
                    isinstance(duration, (int, float))
                    and isinstance(other_duration, (int, float))
                    and abs(duration / 1000 - other_duration)
                    > max(60, other_duration * 0.1)
                ):
                    continue
                candidates.append(
                    {
                        "nike_id": record["id"],
                        "other_source": str(path.relative_to(root)),
                    }
                )
        except (SyncError, Excluded, ValueError, TypeError, KeyError):
            continue
    return candidates


def sync(args, root: Path, work: Path, library, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    state_path = work / "state.json"
    state = read_json(state_path) if state_path.exists() else {}
    if state and (
        state.get("account") != args.account or state.get("data_root") != str(root)
    ):
        raise SyncError(
            "Sync state belongs to a different account label or data checkout."
        )
    since, zone = select_history(args, state, now)
    folders = existing_folders(root)
    token = load_token(root, args.account, args.login, library)
    state.update(
        {
            "version": 1,
            "account": args.account,
            "data_root": str(root),
            "since": since.isoformat() if since else None,
            "timezone": zone,
            "library_revision": REVISION,
            "complete": False,
            "coverage": "nrc-exporter reported IDs; upstream excludes manual runs",
        }
    )
    atomic_json(state_path, state)
    cache = work / "activities"
    private_directory(cache, root)
    lower = datetime.combine(since, datetime.min.time(), UTC) if since else None
    print("Listing runs through nrc-exporter...", flush=True)
    ids = library.list(token)
    if not isinstance(ids, list):
        raise SyncError("Nike library did not return an activity list.")
    pending = state.get("pending_ids", [])
    if not isinstance(pending, list):
        raise SyncError("Sync state has an invalid pending-ID list.")
    ids = list(dict.fromkeys(identifier(value) for value in ids + pending))
    print(
        f"Library listed {len(ids)} runs. Reusing cached details where available.",
        flush=True,
    )
    counts = {
        "imported": 0,
        "updated": 0,
        "unchanged": 0,
        "excluded": 0,
        "incomplete": 0,
        "failed": 0,
    }
    failed = []
    selected_records = []
    consecutive_failures = 0
    for number, activity_id in enumerate(ids, 1):
        try:
            record = cached_record(activity_id, cache, folders)
            start = record_start(record, activity_id) if record else None
            selected = (
                start is not None and (lower is None or start >= lower) and start < now
            )
            if record is None or (args.full and selected):
                record = library.detail(activity_id, token)
                start = record_start(record, activity_id)
                atomic_json(cache / f"{activity_id}.json", record)
            if (lower and start < lower) or start >= now:
                counts["excluded"] += 1
                consecutive_failures = 0
                continue
            day, basis = local_day(record, start, zone)
            folder = folders.get(activity_id, root / f"run-{day}-nike-{activity_id}")
            if folder.is_symlink():
                raise SyncError("Refusing a symlink run folder.")
            folder.mkdir(mode=0o700, exist_ok=True)
            metadata_path = folder / "import.json"
            if (
                metadata_path.exists()
                and read_json(metadata_path).get("account", args.account)
                != args.account
            ):
                raise SyncError("Run folder belongs to a different account label.")
            exists = (folder / "nike.json").exists()
            changed = atomic_json(folder / "nike.json", record)
            metadata = {
                "provider": "nike",
                "activity_id": activity_id,
                "account": args.account,
                "technology": "nrc-exporter",
                "library_revision": REVISION,
                "date_basis": basis,
            }
            atomic_json(metadata_path, metadata)
            folders[activity_id] = folder
            counts[
                "updated"
                if exists and changed
                else "unchanged"
                if exists
                else "imported"
            ] += 1
            if not record.get("metrics"):
                counts["incomplete"] += 1
            selected_records.append(record)
            consecutive_failures = 0
        except Excluded:
            counts["excluded"] += 1
            consecutive_failures = 0
        except SyncError as error:
            counts["failed"] += 1
            failed.append(activity_id)
            consecutive_failures += 1
            print(f"Run {activity_id}: {error}", file=sys.stderr, flush=True)
            if consecutive_failures >= 3:
                failed.extend(ids[number:])
                counts["failed"] += len(ids) - number
                print(
                    "Stopped after three consecutive failures; remaining IDs are pending for retry.",
                    file=sys.stderr,
                    flush=True,
                )
                break
        if number % 25 == 0:
            print(f"Processed {number}/{len(ids)} listed runs.", flush=True)
    state["pending_ids"] = failed
    state["possible_duplicates"] = possible_duplicates(root, selected_records)
    state["complete"] = not failed
    if not failed:
        state["last_success"] = now.isoformat()
        state["last_success_since"] = state["since"]
    atomic_json(state_path, state)
    print(", ".join(f"{key}={value}" for key, value in counts.items()))
    if state["possible_duplicates"]:
        print(
            f"Possible duplicate runs: {len(state['possible_duplicates'])}; review {state_path} before planning."
        )
    print(
        "Coverage is limited to runs supplied by nrc-exporter; manual runs are excluded upstream."
    )
    return 1 if failed else 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=ROOT / "data",
        help="Separate private data checkout",
    )
    parser.add_argument(
        "--account",
        default="athlete",
        type=identifier,
        help="Local account label (not verified identity)",
    )
    history = parser.add_mutually_exclusive_group()
    history.add_argument(
        "--since", type=date.fromisoformat, help="Inclusive UTC start date, YYYY-MM-DD"
    )
    history.add_argument(
        "--all-history", action="store_true", help="Remove the saved history boundary"
    )
    parser.add_argument(
        "--timezone", help="IANA timezone fallback; saved for subsequent imports"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Refresh existing runs in the selected period",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Run the library's login flow again and replace the saved token",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Write a private, redacted run log under data/.sync-state/nike/logs",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60,
        help="Seconds per detail call; listing gets at least 300 seconds",
    )
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be positive and finite")
    select_history(args, {}, datetime.now(UTC))
    return args


def main(argv=None) -> int:
    try:
        args = parse_args(argv)
        root = args.data_dir.expanduser().resolve()
        state_root = prepare_data(root)
        from filelock import FileLock, Timeout

        try:
            with FileLock(state_root / "sync.lock", timeout=0, mode=0o600):
                work = state_root / args.account
                private_directory(work, root)
                with private_log(state_root, root, args.log):
                    result = sync(args, root, work, NikeLibrary(work, args.timeout))
                    print(f"Finished with exit status {result}.", flush=True)
                    return result
        except Timeout:
            raise SyncError(
                "Another Nike sync is already using this data checkout."
            ) from None
    except SyncError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "Interrupted. Completed records are preserved; rerun to continue.",
            file=sys.stderr,
        )
        return 130
    except OSError:
        print(
            "File or process operation failed. Check checkout access and available disk space.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(library_worker() if sys.argv[1:] == ["--_worker"] else main())

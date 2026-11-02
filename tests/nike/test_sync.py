"""Offline integration checks. All tokens and activities here are synthetic."""

import builtins
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[2] / "src" / "nike" / "sync.py"
spec = importlib.util.spec_from_file_location("nike_sync", MODULE)
nike = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nike)
NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)
TOKEN = "synthetic-private-token"


def run_record(activity_id, when="2026-10-15T12:00:00+00:00", **fields):
    value = {
        "id": activity_id,
        "type": "run",
        "start_epoch_ms": datetime.fromisoformat(when).timestamp() * 1000,
        "active_duration_ms": 1800000,
        "metrics": [{"type": "heart_rate", "values": []}],
    }
    value.update(fields)
    return value


class FakeLibrary:
    def __init__(self, records):
        self.records = records
        self.ids = list(records)
        self.fetched = []
        self.logins = 0

    def list(self, token):
        assert token == TOKEN
        return self.ids

    def detail(self, activity_id, token):
        assert token == TOKEN
        self.fetched.append(activity_id)
        result = self.records[activity_id]
        if isinstance(result, Exception):
            raise result
        return result

    def login(self):
        self.logins += 1
        return TOKEN


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        self.state_root = nike.prepare_data(self.root)
        self.work = self.state_root / "athlete"
        nike.private_directory(self.work, self.root)
        nike.atomic_json(
            self.root / "nike-tokens.json",
            {"account": "athlete", "access_token": TOKEN},
        )
        self.stdout, self.stderr = io.StringIO(), io.StringIO()

    def tearDown(self):
        self.temp.cleanup()

    def run_sync(self, library, *flags, now=NOW):
        args = nike.parse_args(
            ["--data-dir", str(self.root), "--timezone", "Europe/Berlin", *flags]
        )
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            result = nike.sync(args, self.root, self.work, library, now)
        self.assertNotIn(TOKEN, self.stdout.getvalue() + self.stderr.getvalue())
        return result

    def state(self):
        return nike.read_json(self.work / "state.json")

    def test_first_import_filters_and_repeat_preserves_files_and_notes(self):
        library = FakeLibrary(
            {
                "first": run_record("first"),
                "second": run_record("second"),
                "old": run_record("old", "2020-01-01T12:00:00+00:00"),
                "ride": run_record("ride", type="ride"),
                "manual": run_record(
                    "manual", metrics=None, tags={"com.nike.running.runtype": "manual"}
                ),
            }
        )
        library.ids.append("first")
        self.assertEqual(0, self.run_sync(library))
        self.assertEqual(3, len(list(self.root.glob("run-*-nike-*"))))
        folders = nike.existing_folders(self.root)
        source = folders["first"] / "nike.json"
        original = source.read_bytes(), source.stat().st_mtime_ns
        (folders["first"] / "notes.md").write_text("Keep this athlete note")
        library.fetched.clear()
        self.assertEqual(0, self.run_sync(library))
        self.assertEqual(["ride"], library.fetched)
        self.assertEqual(original, (source.read_bytes(), source.stat().st_mtime_ns))
        self.assertEqual(
            "Keep this athlete note", (folders["first"] / "notes.md").read_text()
        )
        self.assertIn("incomplete=1", self.stdout.getvalue())

    def test_full_refresh_reuses_folder_after_date_correction(self):
        library = FakeLibrary(
            {
                "first": run_record("first"),
                "old": run_record("old", "2020-01-01T12:00:00+00:00"),
            }
        )
        self.run_sync(library)
        original = nike.existing_folders(self.root)["first"]
        (original / "notes.md").write_text("keep")
        library.records["first"] = run_record(
            "first", "2026-10-16T12:00:00+00:00", name="corrected"
        )
        library.fetched.clear()
        self.assertEqual(0, self.run_sync(library, "--full"))
        self.assertEqual(["first"], library.fetched)
        self.assertEqual(original, nike.existing_folders(self.root)["first"])
        self.assertEqual("corrected", nike.read_json(original / "nike.json")["name"])
        self.assertEqual("keep", (original / "notes.md").read_text())

    def test_failed_record_keeps_checkpoint_and_is_retried_even_if_unlisted(self):
        library = FakeLibrary({"first": run_record("first")})
        self.run_sync(library)
        checkpoint = self.state()["last_success"]
        library.records["failed"] = nike.SyncError("Synthetic library failure")
        library.ids.append("failed")
        self.assertEqual(
            1, self.run_sync(library, now=datetime(2026, 11, 3, tzinfo=UTC))
        )
        self.assertEqual(checkpoint, self.state()["last_success"])
        self.assertFalse(self.state()["complete"])
        self.assertEqual(["failed"], self.state()["pending_ids"])
        library.records["failed"] = run_record("failed")
        library.ids.remove("failed")
        library.fetched.clear()
        self.assertEqual(0, self.run_sync(library))
        self.assertEqual(["failed"], library.fetched)
        self.assertEqual([], self.state()["pending_ids"])
        self.assertTrue(self.state()["complete"])

    def test_backdated_new_run_and_wider_history_are_imported(self):
        library = FakeLibrary(
            {
                "first": run_record("first"),
                "older": run_record("older", "2024-01-01T12:00:00+00:00"),
            }
        )
        self.run_sync(library)
        library.records["late"] = run_record("late", "2026-01-01T12:00:00+00:00")
        library.ids.append("late")
        self.run_sync(library)
        self.assertIn("late", nike.existing_folders(self.root))
        library.fetched.clear()
        self.run_sync(library, "--since", "2023-01-01")
        self.assertIn("older", nike.existing_folders(self.root))
        self.assertEqual([], library.fetched)

    def test_local_date_and_exact_utc_cutoff(self):
        library = FakeLibrary(
            {
                "inside": run_record("inside", "2025-11-02T00:00:00+00:00"),
                "outside": run_record("outside", "2025-11-01T23:59:59+00:00"),
                "midnight": run_record("midnight", "2026-10-15T23:30:00+00:00"),
            }
        )
        self.run_sync(library)
        self.assertFalse(any(self.root.glob("run-*-nike-outside")))
        self.assertTrue(
            (self.root / "run-2026-10-16-nike-midnight" / "nike.json").exists()
        )
        self.assertIn("inside", nike.existing_folders(self.root))

    def test_source_timezone_takes_priority_over_configured_fallback(self):
        library = FakeLibrary(
            {
                "first": run_record(
                    "first", "2026-10-15T23:30:00+00:00", timezone="America/New_York"
                )
            }
        )
        self.run_sync(library)
        folder = self.root / "run-2026-10-15-nike-first"
        self.assertTrue((folder / "nike.json").exists())
        self.assertEqual(
            "timezone", nike.read_json(folder / "import.json")["date_basis"]["source"]
        )

    def test_failed_listing_does_not_claim_wider_history_is_complete(self):
        library = FakeLibrary({"first": run_record("first")})
        self.run_sync(library)
        original = self.state()
        with (
            patch.object(
                library, "list", side_effect=nike.SyncError("Synthetic listing failure")
            ),
            self.assertRaises(nike.SyncError),
        ):
            self.run_sync(library, "--since", "2020-01-01")
        state = self.state()
        self.assertFalse(state["complete"])
        self.assertEqual("2020-01-01", state["since"])
        self.assertEqual(original["last_success_since"], state["last_success_since"])

    def test_api_error_body_is_not_stored_and_missing_metrics_are_valid(self):
        library = FakeLibrary(
            {
                "bad": {"error_id": "unauthorized"},
                "good": run_record("good", metrics=None),
            }
        )
        self.assertEqual(1, self.run_sync(library))
        self.assertEqual(["bad"], self.state()["pending_ids"])
        self.assertFalse((self.work / "activities" / "bad.json").exists())
        self.assertIn("good", nike.existing_folders(self.root))

    def test_repeated_failures_stop_requests_and_keep_remaining_ids_pending(self):
        library = FakeLibrary(
            {f"run{i}": nike.SyncError("Synthetic request failure") for i in range(6)}
        )
        self.assertEqual(1, self.run_sync(library))
        self.assertEqual(3, len(library.fetched))
        self.assertEqual(6, len(self.state()["pending_ids"]))
        self.assertNotIn("last_success", self.state())

    def test_state_loss_reuses_canonical_source_records(self):
        library = FakeLibrary({"first": run_record("first")})
        self.run_sync(library)
        (self.work / "state.json").unlink()
        (self.work / "activities" / "first.json").unlink()
        library.fetched.clear()
        self.run_sync(library)
        self.assertEqual([], library.fetched)

    def test_data_checkout_and_credentials_are_private_and_untracked(self):
        nike.load_token(self.root, "athlete", False, FakeLibrary({}))
        if os.name == "posix":
            self.assertEqual(
                0o600, stat.S_IMODE((self.root / "nike-tokens.json").stat().st_mode)
            )
            self.assertEqual(0o700, stat.S_IMODE(self.work.stat().st_mode))
        for name in ("nike-tokens.json", ".sync-state/nike/athlete/state.json"):
            subprocess.run(
                ["git", "-C", str(self.root), "check-ignore", "--quiet", name],
                check=True,
            )
        subprocess.run(
            ["git", "-C", str(self.root), "add", "--force", "nike-tokens.json"],
            check=True,
        )
        with self.assertRaises(nike.SyncError):
            nike.prepare_data(self.root)

    def test_parent_repository_is_not_accepted_as_private_checkout(self):
        child = self.root / "not-a-checkout"
        child.mkdir()
        with self.assertRaises(nike.SyncError):
            nike.prepare_data(child)

    def test_symlinks_and_cross_account_token_reuse_are_rejected(self):
        with self.assertRaises(nike.SyncError):
            nike.load_token(self.root, "another-athlete", False, FakeLibrary({}))
        token = self.root / "nike-tokens.json"
        token.unlink()
        outside = self.root / "outside.json"
        outside.write_text('{"access_token":"synthetic"}')
        token.symlink_to(outside)
        with self.assertRaises(nike.SyncError):
            nike.load_token(self.root, "athlete", False, FakeLibrary({}))

    def test_renewal_uses_library_and_keeps_token_in_selected_file(self):
        library = FakeLibrary({})
        with patch.object(sys.stdin, "isatty", return_value=True):
            self.assertEqual(
                TOKEN, nike.load_token(self.root, "athlete", True, library)
            )
        self.assertEqual(1, library.logins)
        self.assertEqual(
            TOKEN, nike.read_json(self.root / "nike-tokens.json")["access_token"]
        )

    def test_possible_strava_duplicate_is_reported_without_merging(self):
        folder = self.root / "run-2026-10-15-strava-123"
        folder.mkdir()
        nike.atomic_json(
            folder / "strava.json",
            {"id": 123, "start_date": "2026-10-15T12:00:30Z", "moving_time": 1800},
        )
        self.run_sync(FakeLibrary({"first": run_record("first")}))
        self.assertEqual(1, len(self.state()["possible_duplicates"]))
        self.assertTrue((folder / "strava.json").exists())
        self.assertIn("first", nike.existing_folders(self.root))

    def test_actual_uv_cli_and_upstream_library_with_offline_http(self):
        shim = self.work / "http-fixture"
        shim.mkdir()
        calls = shim / "requests.jsonl"
        fixtures = {"gps-free": run_record("gps-free", metrics=None)}
        (shim / "records.json").write_text(json.dumps(fixtures))
        (shim / "sitecustomize.py").write_text("""
import json, os
from pathlib import Path
import requests
fixture = Path(os.environ["NIKE_TEST_FIXTURE"])
class Response:
    def __init__(self, data): self.data = data
    def json(self): return self.data
def offline_get(url, headers):
    assert headers["Authorization"] == "Bearer synthetic-private-token"
    with (fixture / "requests.jsonl").open("a") as f:
        f.write(json.dumps(url) + "\\n")
    if "/activities/before_id/" in url:
        return Response({"activities": [
            {"id": "gps-free", "type": "run", "tags": {}},
            {"id": "upstream-manual", "type": "run", "tags": {"com.nike.running.runtype": "manual"}}
        ], "paging": {}})
    if "/activity/gps-free?" in url:
        return Response(json.loads((fixture / "records.json").read_text())["gps-free"])
    raise AssertionError("Unexpected HTTP request; live network is disabled in this test")
requests.get = offline_get
if os.environ.get("NIKE_TEST_LOGIN"):
    import builtins, getpass, sys, webbrowser
    builtins.input = lambda prompt="": "y"
    getpass.getpass = lambda prompt="": "synthetic-private-token"
    sys.stdin.isatty = lambda: True
    webbrowser.open_new_tab = lambda url: None
""")
        env = dict(
            os.environ,
            PYTHONPATH=str(shim),
            NIKE_TEST_FIXTURE=str(shim),
            NIKE_TEST_LOGIN="1",
        )
        command = [
            "uv",
            "run",
            "--offline",
            "--locked",
            str(MODULE),
            "--data-dir",
            str(self.root),
            "--since",
            "2025-11-02",
            "--timezone",
            "Europe/Berlin",
            "--log",
            "--login",
        ]
        result = subprocess.run(
            command, env=env, text=True, capture_output=True, timeout=30, check=False
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        log = next((self.state_root / "logs").glob("*.log"))
        self.assertNotIn(TOKEN, log.read_text())
        self.assertEqual(0o600, stat.S_IMODE(log.stat().st_mode))
        self.assertEqual(
            fixtures["gps-free"],
            nike.read_json(self.root / "run-2026-10-15-nike-gps-free" / "nike.json"),
        )
        self.assertFalse(any(self.root.glob("run-*-nike-upstream-manual")))
        self.assertEqual(2, len(calls.read_text().splitlines()))
        calls.unlink()
        command.remove("--login")
        result = subprocess.run(
            command, env=env, text=True, capture_output=True, timeout=30, check=False
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(1, len(calls.read_text().splitlines()))


class LibraryBoundaryTests(unittest.TestCase):
    def test_library_token_input_is_hidden_and_cannot_fall_back_to_echo(self):
        with (
            patch.object(builtins, "input", return_value="y") as confirmation,
            patch.object(nike.getpass, "getpass", return_value=TOKEN) as secret,
        ):
            with nike.private_library_input():
                self.assertEqual("y", input())
                self.assertEqual(TOKEN, input())
            self.assertEqual(1, confirmation.call_count)
            self.assertEqual(1, secret.call_count)
            self.assertEqual("y", input())
        with (
            patch.object(builtins, "input", return_value="y"),
            patch.object(
                nike.getpass, "getpass", side_effect=nike.getpass.GetPassWarning()
            ),
            nike.private_library_input(),
        ):
            input()
            with self.assertRaises(nike.SyncError):
                input()

    def test_log_redacts_split_token_output_before_console_and_file(self):
        console, log = io.StringIO(), io.StringIO()
        with patch.object(nike, "SECRETS", {TOKEN}):
            output = nike.SafeOutput(console, log)
            output.write("Credential: " + TOKEN[:8])
            output.write(TOKEN[8:] + "\n")
            output.flush()
        self.assertNotIn(TOKEN, console.getvalue() + log.getvalue())
        self.assertIn("[REDACTED]", log.getvalue())

    def test_worker_uses_upstream_functions_and_suppresses_output(self):
        def details(activity_id, options):
            self.assertEqual("first", activity_id)
            self.assertEqual({"access_token": TOKEN}, options)
            print(TOKEN)
            return run_record("first")

        fake = types.SimpleNamespace(get_activity_details=details)
        output = io.StringIO()
        request = {"operation": "detail", "id": "first", "token": TOKEN}
        with (
            patch.dict(sys.modules, {"nrc_exporter": fake}),
            patch.object(sys, "stdin", io.StringIO(json.dumps(request))),
            redirect_stdout(output),
        ):
            nike.library_worker()
        self.assertNotIn(TOKEN, output.getvalue())
        self.assertEqual("first", json.loads(output.getvalue())["result"]["id"])

    def test_upstream_zero_exit_is_not_treated_as_an_empty_success(self):
        fake = types.SimpleNamespace(get_activities_list=lambda options: sys.exit(0))
        output = io.StringIO()
        with (
            patch.dict(sys.modules, {"nrc_exporter": fake}),
            patch.object(
                sys,
                "stdin",
                io.StringIO(json.dumps({"operation": "list", "token": TOKEN})),
            ),
            redirect_stdout(output),
        ):
            nike.library_worker()
        self.assertEqual("SystemExit", json.loads(output.getvalue())["error"])

    def test_token_uses_stdin_not_process_arguments_and_stderr_is_not_exposed(self):
        library = nike.NikeLibrary(Path(tempfile.gettempdir()), 5)
        response = subprocess.CompletedProcess([], 1, stdout="", stderr=TOKEN)
        with (
            patch.object(nike.subprocess, "run", return_value=response) as run,
            self.assertRaises(nike.SyncError) as failure,
        ):
            library.detail("first", TOKEN)
        self.assertNotIn(TOKEN, str(run.call_args.args[0]))
        self.assertIn(TOKEN, run.call_args.kwargs["input"])
        self.assertNotIn(TOKEN, str(failure.exception))


if __name__ == "__main__":
    unittest.main()

"""archive.py: the failed builds' logs kept for build-logs.nixkeeper.com,
and cli.look_up_reasons adding the logs it reads."""

import gzip
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from nixkeeper_hydra import archive, cli, hydra

FINISHED = "2026-11-11T15:56:05+00:00"


def row(attr, build="352346093", system="x86_64-linux"):
    return {
        "attr": attr,
        "system": system,
        "build": build,
        "status": "failed",
        "finished": FINISHED,
    }


class Path(unittest.TestCase):
    def test_a_folder_per_package(self):
        self.assertEqual(
            archive.path(row("python313Packages.foo")),
            "python313Packages.foo/2026-11-11T1556-x86_64-linux-352346093.log",
        )

    def test_unsafe_names_are_left_out(self):
        for attr in ("../etc", "a/b", ".hidden", "", "a..b"):
            self.assertIsNone(archive.path(row(attr)), attr)
        self.assertIsNone(archive.path(row("hello", build="1/2")))
        self.assertIsNone(archive.path({**row("hello"), "finished": ""}))


class Kept(unittest.TestCase):
    def test_written_gzipped_indexed_and_summed_up(self):
        with tempfile.TemporaryDirectory() as d:
            kept = archive.Archive(d)
            text = b"error: hash mismatch\n" * 100
            kept.add(row("hello"), hydra.Log(text, len(text)), "hash")
            cut = hydra.Log(b"head [...] tail", 5_000_000, truncated=True)
            kept.add(row("big", build="2"), cut, "other")
            self.assertIsNone(kept.add(row("../x"), cut, "other"))
            kept.write_index()
            where = os.path.join(d, archive.path(row("hello")) + ".gz")
            with gzip.open(where) as f:
                self.assertEqual(f.read(), text)
            with gzip.open(os.path.join(d, archive.INDEX)) as f:
                index = json.load(f)
        self.assertEqual([e["attr"] for e in index], ["big", "hello"])
        self.assertTrue(index[0]["truncated"])
        self.assertNotIn("truncated", index[1])
        self.assertEqual(index[1]["reason"], "hash")
        self.assertEqual(index[1]["bytes"], len(text))
        lines = kept.summary()
        self.assertTrue(lines[0].startswith("Build logs: 2 kept, 5.00 MB as read"))
        self.assertIn("1 truncated", lines[0])
        self.assertTrue(lines[1].startswith("- big (x86_64-linux): 5.00 MB"))
        self.assertEqual(
            archive.Archive("unused").summary(), ["Build logs: none read this run."]
        )


class LookUp(unittest.TestCase):
    def test_each_log_read_is_kept(self):
        rows = [row("a", build="1"), row("b", build="2")]
        text = b"error: hash mismatch\n"
        logs = {"1": hydra.Log(text, len(text)), "2": None}  # b: Hydra has none
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(hydra, "build_drv", side_effect=lambda b: b),
            mock.patch.object(hydra, "build_log", side_effect=logs.get),
        ):
            kept = archive.Archive(d)
            self.assertEqual(cli.look_up_reasons(rows, {}, time.monotonic(), kept), 2)
        self.assertEqual([e["build"] for e in kept.entries], ["1"])

    def test_only_with_a_folder_and_reported(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(cli.archive_from_env())
        with tempfile.TemporaryDirectory() as d:
            summary = os.path.join(d, "summary.md")
            env = {
                "BUILD_LOGS_DIR": os.path.join(d, "logs"),
                "GITHUB_STEP_SUMMARY": summary,
            }
            with mock.patch.dict(os.environ, env), mock.patch("builtins.print"):
                kept = cli.archive_from_env()
                cli.report_archive(kept)
            with open(summary) as f:
                self.assertEqual(f.read(), "Build logs: none read this run.\n")
            self.assertTrue(os.path.exists(os.path.join(d, "logs", archive.INDEX)))


if __name__ == "__main__":
    unittest.main()

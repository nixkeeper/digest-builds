"""Failed builds' whole logs, kept for build-logs.nixkeeper.com: a folder per
package, a log per failed build, as nixpkgs-update-logs.nixos.org keeps the
update bot's.

The digest already reads every failed build's log once (cli.look_up_reasons)
and keeps only a reason and a few lines (reasons.py). With an archive
folder, each log read is also written there, gzipped, at the path it's
served from:

    <attr>/<finished>-<system>-<build>.log   e.g.
    hello/2026-11-11T1556-x86_64-linux-352346093.log

(stored as that path plus ".gz"), and index.json.gz lists them. Nothing is
uploaded yet: a run reports what it kept (summary), to measure the sizes
before choosing what to keep."""

import gzip
import json
import os
import re
from dataclasses import dataclass, field

INDEX = "index.json.gz"
# Hydra's job names: a folder each. Anything else (a path separator, "..")
# isn't kept.
ATTR = re.compile(r"[A-Za-z0-9_+'-][A-Za-z0-9_.+'-]*")
SYSTEM = re.compile(r"[a-z0-9_]+-[a-z0-9_]+")


def path(row):
    """The path row's log is served from: <attr>/<finished>-<system>-<build>.log,
    finished as 2026-11-11T1556 (UTC, to the minute). None for a row whose
    names don't make a safe path."""
    attr, system, build = row["attr"], row["system"], str(row["build"])
    if not (
        ATTR.fullmatch(attr)
        and ".." not in attr
        and SYSTEM.fullmatch(system)
        and build.isdigit()
        and row.get("finished")
    ):
        return None
    stamp = row["finished"][:16].replace(":", "")
    return f"{attr}/{stamp}-{system}-{build}.log"


@dataclass
class Archive:
    """Logs written to directory in a run, and their index entries."""

    directory: str
    entries: list = field(default_factory=list)

    def add(self, row, log, reason):
        """Write log (hydra.Log) of row's build, gzipped, and index it with
        reason. Returns its entry, or None when row has no safe path."""
        where = path(row)
        if where is None:
            return None
        body = gzip.compress(log.kept, compresslevel=9, mtime=0)
        file = os.path.join(self.directory, where + ".gz")
        os.makedirs(os.path.dirname(file), exist_ok=True)
        with open(file, "wb") as f:
            f.write(body)
        entry = {
            "build": str(row["build"]),
            "attr": row["attr"],
            "system": row["system"],
            "finished": row["finished"],
            "reason": reason,
            "bytes": log.size,
            "kept": len(log.kept),
            "gzip": len(body),
            "path": where,
        }
        if log.truncated:
            entry["truncated"] = True
        self.entries.append(entry)
        return entry

    def write_index(self):
        """Write index.json.gz: the entries, by path."""
        os.makedirs(self.directory, exist_ok=True)
        entries = sorted(self.entries, key=lambda e: e["path"])
        body = json.dumps(entries, separators=(",", ":")).encode()
        with open(os.path.join(self.directory, INDEX), "wb") as f:
            f.write(gzip.compress(body, compresslevel=9, mtime=0))

    def summary(self, largest=5):
        """What this run kept, as Markdown lines: how many logs, their sizes
        raw and gzipped, how many truncated, and the largest."""
        if not self.entries:
            return ["Build logs: none read this run."]
        raw = sum(e["bytes"] for e in self.entries)
        kept = sum(e["kept"] for e in self.entries)
        packed = sum(e["gzip"] for e in self.entries)
        cut = sum(1 for e in self.entries if e.get("truncated"))
        lines = [
            f"Build logs: {len(self.entries):,} kept, {_mb(raw)} as read "
            f"({_mb(kept)} kept), {_mb(packed)} gzipped"
            + (f", {cut:,} truncated" if cut else "")
            + "."
        ]
        top = sorted(self.entries, key=lambda e: -e["bytes"])[:largest]
        lines += [
            f"- {e['attr']} ({e['system']}): {_mb(e['bytes'])}, "
            f"{_mb(e['gzip'])} gzipped"
            for e in top
        ]
        return lines


def _mb(n):
    """n bytes as MB, to two decimals."""
    return f"{n / 1e6:,.2f} MB"

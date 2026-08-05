#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2020 The SymbiFlow Authors.
#
# Use of this source code is governed by a ISC-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/ISC
#
# SPDX-License-Identifier: ISC

import json
import os
import resource
import shutil
import signal
import subprocess

from BaseRunner import BaseRunner


def kill_child_processes(parent_pid, sig=signal.SIGKILL):
    try:
        import psutil
        parent = psutil.Process(parent_pid)
    except (ImportError, Exception):
        return
    children = parent.children(recursive=True)
    for process in children:
        process.send_signal(sig)


LOCATION_KEYS = {"start", "end", "location", "line", "column", "offset"}
TRIVIA_KEYS = {"trivia"}


def _strip_locations(obj):
    if isinstance(obj, dict):
        return {
            k: _strip_locations(v)
            for k, v in obj.items()
            if k not in LOCATION_KEYS and k not in TRIVIA_KEYS
        }
    if isinstance(obj, list):
        return [_strip_locations(item) for item in obj]
    return obj


class VerihoggFormat(BaseRunner):
    def __init__(self):
        super().__init__("VerihoggFormat", "verihogg-format", {'parsing'})

        self.submodule = "third_party/tools/verihogg-format"
        self.url = f"https://github.com/verihogg/verihogg-format/tree/{self.get_commit()}"

    def _profile(self):
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        return (usage.ru_utime, usage.ru_stime, usage.ru_maxrss)

    def prepare_run_cb(self, tmp_dir, params):
        self.cmd = [self.executable] + params['files']

    def run(self, tmp_dir, params):
        timeout = int(params['timeout'])
        if 'DISABLE_TEST_TIMEOUTS' in os.environ:
            timeout = None
        else:
            try:
                timeout = int(os.environ['OVERRIDE_TEST_TIMEOUTS'])
            except KeyError:
                pass

        originals_dir = os.path.join(tmp_dir, "originals")
        formatted_dir = os.path.join(tmp_dir, "formatted")
        os.makedirs(originals_dir)
        os.makedirs(formatted_dir)

        file_pairs = []
        for f in params['files']:
            basename = os.path.basename(f)
            orig_path = os.path.join(originals_dir, basename)
            fmt_path = os.path.join(formatted_dir, basename)
            shutil.copy2(f, orig_path)
            shutil.copy2(f, fmt_path)
            file_pairs.append((orig_path, fmt_path))

        fmt_cmd = [self.executable, "--inplace"]
        fmt_cmd += [f"-I{d}" for d in params['incdirs']]
        fmt_cmd += [f"-D{d}" for d in params['defines']]
        fmt_cmd += [fmt for _, fmt in file_pairs]
        fmt_log, fmt_rc = self._run(fmt_cmd, tmp_dir, timeout)
        invocation = " ".join(fmt_cmd) + "\n"

        if fmt_rc != 0:
            return (invocation + fmt_log, fmt_rc) + self._profile()

        for orig, fmt in file_pairs:
            orig_json = os.path.join(tmp_dir, "orig_cst.json")
            fmt_json = os.path.join(tmp_dir, "fmt_cst.json")

            slang_base = [
                "slang-driver", "--parse-only", "--single-unit",
                "--timescale=1ns/1ns"
            ]
            slang_base += [f"-I{d}" for d in params['incdirs']]
            slang_base += [f"-D{d}" for d in params['defines']]

            orig_cmd = slang_base + ["--cst-json", orig_json, orig]
            orig_log, orig_rc = self._run(orig_cmd, tmp_dir, timeout)
            if orig_rc != 0:
                return (
                    invocation + f"slang-driver (original) {orig}\n" + orig_log,
                    1) + self._profile()

            fmt_cmd_slang = slang_base + ["--cst-json", fmt_json, fmt]
            fmt_slang_log, fmt_slang_rc = self._run(
                fmt_cmd_slang, tmp_dir, timeout)
            if fmt_slang_rc != 0:
                return (
                    invocation + f"slang-driver (formatted) {fmt}\n" + fmt_slang_log,
                    1) + self._profile()

            try:
                with open(orig_json) as jf:
                    orig_cst = json.load(jf)
                with open(fmt_json) as jf:
                    fmt_cst = json.load(jf)
            except (json.JSONDecodeError, OSError) as e:
                return (invocation + f"Failed to load CST JSON: {e}\n",
                        1) + self._profile()

            orig_cst_stripped = _strip_locations(orig_cst)
            fmt_cst_stripped = _strip_locations(fmt_cst)

            if orig_cst_stripped != fmt_cst_stripped:
                return (
                    invocation +
                    f"CST mismatch between original and formatted: {orig}\n",
                    1) + self._profile()

        return (invocation + "CST verification passed\n", 0) + self._profile()

    def _run(self, cmd, cwd, timeout):
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
        try:
            log, _ = proc.communicate(timeout=timeout)
            return (log.decode('utf-8', 'ignore'), proc.returncode)
        except subprocess.TimeoutExpired:
            kill_child_processes(proc.pid)
            proc.kill()
            proc.communicate()
            return ("Timeout\n", 71)

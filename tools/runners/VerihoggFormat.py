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
from cst_normalizer import normalize_cst


def kill_child_processes(parent_pid, sig=signal.SIGKILL):
    try:
        import psutil
        parent = psutil.Process(parent_pid)
    except (ImportError, Exception):
        return
    children = parent.children(recursive=True)
    for process in children:
        process.send_signal(sig)


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
        comparison_dir = os.path.join(tmp_dir, "comparison")
        for directory in (originals_dir, formatted_dir, comparison_dir):
            os.makedirs(directory)

        source_files = [os.path.abspath(f) for f in params['files']]
        source_dirs = list(
            dict.fromkeys(os.path.dirname(f) for f in source_files))
        source_root = os.path.commonpath(source_dirs)
        relative_files = [
            os.path.relpath(f, source_root) for f in source_files
        ]
        for source, relative in zip(source_files, relative_files):
            for directory in (originals_dir, formatted_dir):
                target = os.path.join(directory, relative)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)

        def include_args(directory):
            # Prefer staged copies of supplied headers; use original directories
            # for headers outside the test's input files.
            originals = list(
                dict.fromkeys(
                    [os.path.abspath(d) for d in params['incdirs']] +
                    source_dirs))
            staged = [
                os.path.join(directory, os.path.relpath(d, source_root))
                for d in originals
                if os.path.commonpath([source_root, d]) == source_root
            ]
            return [f"-I{d}" for d in staged + originals]

        fmt_cmd = [self.executable, "--inplace"]
        fmt_cmd += include_args(formatted_dir)
        fmt_cmd += [f"-D{d}" for d in params['defines']]
        fmt_cmd += [os.path.join(formatted_dir, f) for f in relative_files]
        fmt_log, fmt_rc = self._run(fmt_cmd, tmp_dir, timeout)
        invocation = " ".join(fmt_cmd) + "\n"

        if fmt_rc != 0:
            return (invocation + fmt_log, fmt_rc) + self._profile()

        slang_base = [
            "slang-driver", "--parse-only", "--single-unit",
            "--timescale=1ns/1ns"
        ]
        slang_base += include_args(comparison_dir)
        slang_base += [f"-D{d}" for d in params['defines']]
        original_csts = {}
        for label, directory in (("original", originals_dir), ("formatted",
                                                               formatted_dir)):
            # Both parses must see the same filenames for __FILE__. Stage all
            # inputs together so includes also see the right version of headers.
            for relative in relative_files:
                target = os.path.join(comparison_dir, relative)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(os.path.join(directory, relative), target)
            for relative in relative_files:
                source = os.path.join(comparison_dir, relative)
                json_path = os.path.join(tmp_dir, "cst.json")
                cmd = slang_base + ["--cst-json", json_path, source]
                log, rc = self._run(cmd, tmp_dir, timeout)
                if rc != 0:
                    return (
                        invocation + f"slang-driver ({label}) {source}\n" +
                        log, 1) + self._profile()
                try:
                    with open(json_path) as jf:
                        cst = normalize_cst(json.load(jf))
                except (ValueError, OSError) as e:
                    return (invocation + f"Cannot compare CST JSON: {e}\n",
                            1) + self._profile()
                if label == "original":
                    original_csts[relative] = cst
                elif original_csts[relative] != cst:
                    return (
                        invocation +
                        f"CST mismatch between original and formatted: {relative}\n",
                        1) + self._profile()

        return (invocation + "CST verification passed\n", 0) + self._profile()

    def _run(self, cmd, cwd, timeout):
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            log, _ = proc.communicate(timeout=timeout)
            return (log.decode('utf-8', 'ignore'), proc.returncode)
        except subprocess.TimeoutExpired:
            kill_child_processes(proc.pid)
            proc.kill()
            proc.communicate()
            return ("Timeout\n", 71)

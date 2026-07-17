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

from BaseRunner import BaseRunner


class VerihoggLint(BaseRunner):
    def __init__(self):
        super().__init__("VerihoggLint", "verihogg-lint",
                         {'parsing', 'elaboration'})

        self.submodule = "third_party/tools/verihogg-lint"
        self.url = f"https://github.com/verihogg/verihogg-lint/tree/{self.get_commit()}"

    def prepare_run_cb(self, tmp_dir, params):
        self.cmd = [self.executable, '-nobuiltin']

        top = params['top_module'].strip()
        if top:
            self.cmd.append('--top-module=' + top)

        for incdir in params['incdirs']:
            self.cmd.append('-I' + incdir)

        for define in params['defines']:
            self.cmd.append('-D' + define)

        self.cmd += params['files']

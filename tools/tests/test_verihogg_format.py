#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2026 The sv-tests Authors.
#
# Use of this source code is governed by a ISC-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/ISC
#
# SPDX-License-Identifier: ISC
"""Run with python3 -m unittest discover -s tools/tests -v.

Set SLANG_DRIVER to a slang executable with --cst-json support to also run
integration tests against real syntax trees.
"""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cst_normalizer import normalize_cst as _normalize_cst
from runners.VerihoggFormat import VerihoggFormat


class NormalizeCSTTests(unittest.TestCase):
    def test_whitespace_does_not_change_comparison(self):
        original = {"kind": "Identifier", "text": "m"}
        formatted = {
            **original,
            "trivia": [
                {
                    "kind": "Whitespace",
                    "text": " \t"
                },
                {
                    "kind": "EndOfLine",
                    "text": "\r\n\n"
                },
                {
                    "kind": "DisabledText",
                    "text": " \n"
                },
            ],
        }
        self.assertEqual(_normalize_cst(original), _normalize_cst(formatted))

    def test_field_names_are_not_treated_as_locations(self):
        for key in ("start", "end", "location", "line", "column", "offset"):
            with self.subTest(key=key):
                original = {key: {"kind": "Identifier", "text": "first"}}
                changed = {key: {"kind": "Identifier", "text": "second"}}
                self.assertNotEqual(
                    _normalize_cst(original), _normalize_cst(changed))

    def test_incomplete_trivia_is_rejected(self):
        for trivia in ("`define M 1", ["`define M 1"], [{"kind": "Directive",
                                                         "text": ""}],
                       [{"kind": "Directive", "syntax": None}]):
            with self.subTest(trivia=trivia):
                with self.assertRaises(ValueError):
                    _normalize_cst({"trivia": trivia})

    def test_non_ascii_disabled_text_is_preserved(self):
        self.assertNotEqual(
            _normalize_cst({}),
            _normalize_cst(
                {"trivia": [{
                    "kind": "DisabledText",
                    "text": "\u00a0"
                }]}))

    def test_unknown_trivia_and_opaque_disabled_text_are_preserved(self):
        for kind in ("FutureTriviaKind", "DisabledText"):
            with self.subTest(kind=kind):
                original = {"trivia": [{"kind": kind, "text": "a b"}]}
                changed = {"trivia": [{"kind": kind, "text": "a  b"}]}
                self.assertNotEqual(
                    _normalize_cst(original), _normalize_cst(changed))

    def test_ordinary_comments_are_ignored(self):
        for kind, text in (("LineComment", "// explanation"),
                           ("BlockComment", "/* explanation */"),
                           ("DisabledText", "// explanation")):
            with self.subTest(kind=kind):
                self.assertEqual(
                    _normalize_cst({}),
                    _normalize_cst({"trivia": [{
                        "kind": kind,
                        "text": text
                    }]}))

    def test_nested_directive_trivia_is_normalized_without_mutating_input(
            self):
        original = {
            "kind":
            "Identifier",
            "text":
            "m",
            "trivia": [
                {
                    "kind": "Directive",
                    "syntax": {
                        "kind": "DefineDirective",
                        "body": [{
                            "kind": "IntegerLiteral",
                            "text": "1"
                        }],
                    },
                }
            ],
        }
        formatted = copy.deepcopy(original)
        body = formatted["trivia"][0]["syntax"]["body"][0]
        body["trivia"] = [{"kind": "Whitespace", "text": "  "}]
        before = copy.deepcopy(formatted)
        self.assertEqual(_normalize_cst(original), _normalize_cst(formatted))
        self.assertEqual(formatted, before)
        body["text"] = "2"
        self.assertNotEqual(
            _normalize_cst(original), _normalize_cst(formatted))

    def test_meaningful_trivia_is_preserved(self):
        for trivia in (
            {"kind": "LineComment", "text": "// synopsys translate_off"},
            {"kind": "BlockComment", "text": "/* verilator lint_off WIDTH */"},
            {"kind": "DisabledText", "text": "wire hidden;"},
            {"kind": "SkippedTokens", "tokens": [{"text": "hidden"}]},
            {"kind": "SkippedSyntax", "syntax": {"kind": "Unknown"}},
        ):
            with self.subTest(kind=trivia["kind"]):
                original = {"kind": "Identifier", "text": "m"}
                formatted = {**original, "trivia": [trivia]}
                self.assertNotEqual(
                    _normalize_cst(original), _normalize_cst(formatted))

    def test_trivia_order_is_preserved(self):
        original = {
            "trivia": [
                {
                    "kind": "LineComment",
                    "text": "// synopsys translate_off"
                },
                {
                    "kind": "LineComment",
                    "text": "// synopsys translate_on"
                },
            ]
        }
        formatted = {"trivia": list(reversed(original["trivia"]))}
        self.assertNotEqual(
            _normalize_cst(original), _normalize_cst(formatted))

    def test_whitespace_inside_text_is_preserved(self):
        for kind, original_text, changed_text in (
            ("StringLiteral", '"a b"',
             '"ab"'), ("LineComment", "// synthesis translate_off",
                       "// synthesis translate_on"),
            ("BlockComment", "/* verilator lint_off WIDTH */",
             "/* verilator lint_on WIDTH */"), ("DisabledText", "a b", "ab")):
            with self.subTest(kind=kind):
                original = {"kind": kind, "text": original_text}
                formatted = {"kind": kind, "text": changed_text}
                if kind != "StringLiteral":
                    original = {"trivia": [original]}
                    formatted = {"trivia": [formatted]}
                self.assertNotEqual(
                    _normalize_cst(original), _normalize_cst(formatted))

    def test_final_newline_is_ignored_but_trailing_tool_comment_is_preserved(
            self):
        original = {"kind": "CompilationUnit"}
        formatted = {
            **original,
            "endOfFile": {
                "kind": "EndOfFile",
                "text": "",
                "trivia": [{
                    "kind": "EndOfLine",
                    "text": "\n"
                }],
            },
        }
        self.assertEqual(_normalize_cst(original), _normalize_cst(formatted))
        formatted["endOfFile"]["trivia"].append(
            {
                "kind": "LineComment",
                "text": "// synthesis translate_on"
            })
        self.assertNotEqual(
            _normalize_cst(original), _normalize_cst(formatted))


SLANG_DRIVER = os.environ.get("SLANG_DRIVER") or shutil.which("slang-driver")


@unittest.skipUnless(
    SLANG_DRIVER, "Set SLANG_DRIVER to run CST integration tests")
class SlangCSTTests(unittest.TestCase):
    def parse(self, source, directory):
        source_path = Path(directory) / "input.sv"
        json_path = Path(directory) / "cst.json"
        source_path.write_bytes(source.encode())
        result = subprocess.run(
            [
                SLANG_DRIVER, "--parse-only", "--single-unit",
                "--std=1800-2023", "--cst-json",
                str(json_path),
                str(source_path)
            ],
            capture_output=True,
            text=True,
            timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return _normalize_cst(json.loads(json_path.read_text()))

    def test_formatting_changes_compare_equal(self):
        cases = [
            ('module m; endmodule', '\nmodule  m ;\n\nendmodule\n\n'),
            (
                '`define UNUSED(x) x+1\nmodule m; endmodule',
                '`define UNUSED(x)  x + 1\n\nmodule m;\nendmodule\n'),
            (
                '`ifdef ABSENT\n`define UNUSED 1\n`endif\nmodule m; endmodule',
                '`ifdef ABSENT\n  `define UNUSED  1\n\n `endif\nmodule m; endmodule\n'
            ),
            (
                '// lead\nmodule m; endmodule\n// tail\n',
                '\n // lead\n\nmodule m;\nendmodule\n\n// tail\n\n'),
            (
                'module m; /* first\n second */ endmodule\n',
                'module m; /* first\r\n\r\n   second */ endmodule\n'),
            (
                'module m; // first  second\nendmodule\n',
                'module m; // first second   \nendmodule\n'),
            (
                '`define ADD(x) x + 1\nmodule m; localparam P = `ADD(2); endmodule\n',
                '`define ADD(x) x + \\\n1\nmodule m; localparam P = `ADD(2); endmodule\n'
            ),
            (
                '`define ADD(x) x + /* keep */ 1\nmodule m; endmodule\n',
                '`define ADD(x) x + /* keep */ \\\n1\nmodule m; endmodule\n'),
            (
                '`ifdef ABSENT\n`define ADD(x) x + 1\n`endif\nmodule m; endmodule\n',
                '`ifdef ABSENT\n`define ADD(x) x + \\\n1\n`endif\nmodule m; endmodule\n'
            ),
            (
                '`ifdef ABSENT\n`define X (a)\n`endif\nmodule m; endmodule\n',
                '`ifdef ABSENT\n`define X \\\n(a)\n`endif\nmodule m; endmodule\n'
            ),
            (
                '`ifdef ABSENT\n`define X(a,b) a+b\n`endif\nmodule m; endmodule\n',
                '`ifdef ABSENT\n`define X( a, b )  a + b\n`endif\nmodule m; endmodule\n'
            ),
            (
                '`define LABEL `"a b`" + 1\nmodule m; endmodule\n',
                '`define LABEL  `"a b`"+  1\nmodule m; endmodule\n'),
            (
                '`ifdef ABSENT\nwire x;\n// same\n`endif\nmodule m; endmodule\n',
                '`ifdef ABSENT\n  wire x ;\n\n//  same\n`endif\nmodule m; endmodule\n'
            ),
            (
                '// first\nmodule m; endmodule',
                '// changed\nmodule m; endmodule'),
            ('module m; endmodule\n// tail\n', 'module m; endmodule\n'),
            (
                'module m; initial begin /* keep */ end endmodule\n',
                'module m; initial begin /* changed */ end endmodule\n'),
            (
                '`define X a /* keep */ + 1\nmodule m; endmodule\n',
                '`define X a \\\n+ 1\nmodule m; endmodule\n'),
            (
                'module m; /* words */ endmodule',
                'module m; // different words\nendmodule'),
            (
                '// first second\nmodule m; endmodule',
                '// first\n// second\nmodule m; endmodule'),
            (
                '`define SUM(a=1,b=2) a+b\nmodule m; localparam P=`SUM(); endmodule',
                '`define SUM(a= 1,b= 2) a + b\nmodule m; localparam P = `SUM(); endmodule'
            ),
            (
                '`define PLUS(x) ((x)+1)\n'
                '`define VALUE `PLUS(2+3)\n'
                'module m; localparam P=`VALUE; endmodule',
                '`define PLUS(x) ((x) + 1)\n'
                '`define VALUE `PLUS(2 + 3)\n'
                'module m; localparam P=`VALUE; endmodule'),
            (
                '`define F(x={a, b + c}) x\nmodule m; endmodule',
                '`define F(x={a,b+c}) x\nmodule m; endmodule'),
            (
                '`ifdef ABSENT\n'
                '`define PLUS(x) x+1\n'
                '`define VALUE(x={a, b + c}) `PLUS(x)\n'
                '`endif\n'
                'module m; endmodule', '`ifdef ABSENT\n'
                '`define PLUS(x) x + 1\n'
                '`define VALUE(x={a,b+c}) `PLUS( x )\n'
                '`endif\n'
                'module m; endmodule'),
            (
                '`ifdef ABSENT\n`undef A module n; endmodule\n`endif\nmodule m; endmodule',
                '`ifdef ABSENT\n`undef A\nmodule n; endmodule\n`endif\nmodule m; endmodule'
            ),
            (
                '`ifdef ABSENT\n`timescale 1ns/1ps module n; endmodule\n`endif\nmodule m; endmodule',
                '`ifdef ABSENT\n`timescale 1ns / 1ps\nmodule n; endmodule\n`endif\nmodule m; endmodule'
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            for original, formatted in cases:
                with self.subTest(source=original):
                    self.assertEqual(
                        self.parse(original, directory),
                        self.parse(formatted, directory))

    def test_meaningful_changes_compare_unequal(self):
        cases = [
            (
                '`define UNUSED 1\nmodule m; endmodule',
                '`define UNUSED 2\nmodule m; endmodule'),
            (
                '`define UNUSED(x) x+1\nmodule m; endmodule',
                '`define UNUSED (x) x+1\nmodule m; endmodule'),
            ('`define UNUSED 1\nmodule m; endmodule', 'module m; endmodule'),
            (
                '`timescale 1ns/1ps\nmodule m; endmodule',
                '`timescale 1us/1ps\nmodule m; endmodule'),
            (
                '`ifdef ABSENT\nwire hidden;\n`endif\nmodule m; endmodule',
                '`ifdef ABSENT\nwire changed;\n`endif\nmodule m; endmodule'),
            (
                'module m; endmodule\n`define UNUSED 1\n',
                'module m; endmodule\n`define UNUSED 2\n'),
            (
                '`define VALUE(x) 1\nmodule m; localparam P = `VALUE(2); endmodule',
                '`define VALUE(x) 1\nmodule m; localparam P = `VALUE(3); endmodule'
            ),
            (
                'module m; localparam S = "a b"; endmodule',
                'module m; localparam S = "ab"; endmodule'),
            (
                'module m; initial begin\n`define UNUSED 1\nend endmodule\n',
                'module m; initial begin\n`define UNUSED 2\nend endmodule\n'),
            (
                'module m; initial fork #1; join endmodule\n',
                'module m; initial fork #1; join_none endmodule\n'),
            (
                '`define LABEL `"a b`"\nmodule m; endmodule\n',
                '`define LABEL `"a  b`"\nmodule m; endmodule\n'),
            (
                '`define LABEL `"a b`"\nmodule m; endmodule\n',
                '`define LABEL `"a b `"\nmodule m; endmodule\n'),
            (
                '`define LABEL `"a b`"\nmodule m; endmodule\n',
                '`define LABEL `" a b`"\nmodule m; endmodule\n'),
            (
                '`ifdef ABSENT\n`define FUNC(x) x+1\n`endif\nmodule m; endmodule\n',
                '`ifdef ABSENT\n`define FUNC (x) x+1\n`endif\nmodule m; endmodule\n'
            ),
            (
                '`ifdef ABSENT\n`define VALUE 1 + 2\n`endif\nmodule m; endmodule\n',
                '`ifdef ABSENT\n`define VALUE 1\n+ 2\n`endif\nmodule m; endmodule\n'
            ),
            (
                '`ifdef ABSENT\n`define LABEL `"a b`"\n`endif\nmodule m; endmodule\n',
                '`ifdef ABSENT\n`define LABEL `"a  b`"\n`endif\nmodule m; endmodule\n'
            ),
            (
                '`define STR(x) `"x`"\n`define UNUSED `STR(a + b)\nmodule m; endmodule\n',
                '`define STR(x) `"x`"\n`define UNUSED `STR(a+b)\nmodule m; endmodule\n'
            ),
            (
                '`define STR(x) `"x`"\n`define UNUSED(x=a + b) `STR(x)\nmodule m; endmodule\n',
                '`define STR(x) `"x`"\n`define UNUSED(x=a+b) `STR(x)\nmodule m; endmodule\n'
            ),
            (
                '`ifdef ABSENT\n`define UNUSED(x=a + b) `STR(x)\n`endif\nmodule m; endmodule\n',
                '`ifdef ABSENT\n`define UNUSED(x=a+b) `STR(x)\n`endif\nmodule m; endmodule\n'
            ),
            (
                '`define STR(x) `"x`"\n`define UNUSED `STR\\\n(a + b)\nmodule m; endmodule\n',
                '`define STR(x) `"x`"\n`define UNUSED `STR\\\n(a+b)\nmodule m; endmodule\n'
            ),
            (
                'module m; // synthesis translate_off\nwire x; // synthesis translate_on\nendmodule',
                'module m; wire x; endmodule'),
            (
                '`ifdef ABSENT\n`undef A `define F(x) x\n`endif\nmodule m; endmodule',
                '`ifdef ABSENT\n`undef A `define F (x) x\n`endif\nmodule m; endmodule'
            ),
            (
                '`define STR(x) `"x`"\n`define F(x={a, b + c}) `STR(x)\nmodule m; endmodule',
                '`define STR(x) `"x`"\n`define F(x={a, b+c}) `STR(x)\nmodule m; endmodule'
            ),
            (
                '`ifdef ABSENT\n`define F(x={a, b + c}) `STR(x)\n`endif\nmodule m; endmodule',
                '`ifdef ABSENT\n`define F(x={a, b+c}) `STR(x)\n`endif\nmodule m; endmodule'
            ),
            (
                '`ifdef ABSENT\n`define F(x=arr[a, b + c]) `STR(x)\n`endif\nmodule m; endmodule',
                '`ifdef ABSENT\n`define F(x=arr[a, b+c]) `STR(x)\n`endif\nmodule m; endmodule'
            ),
            (
                '`define STR(x) `"x`"\n'
                '`define WRAP(x) `STR(x)\n'
                '`define F(x=a + b) `WRAP(x)\n'
                'module m; endmodule', '`define STR(x) `"x`"\n'
                '`define WRAP(x) `STR(x)\n'
                '`define F(x=a+b) `WRAP(x)\n'
                'module m; endmodule'),
            (
                '`define F(x) `UNKNOWN(a + b)\nmodule m; endmodule',
                '`define F(x) `UNKNOWN(a+b)\nmodule m; endmodule'),
            (
                'module m;\n`define X a // continuation \\\nlocalparam P=1;\nendmodule',
                'module m;\n`define X a // continuation \\ \nlocalparam P=1;\nendmodule'
            ),
            (
                '`ifdef ABSENT\n`define X a // continuation \\\n+ 1\n`endif\nmodule m; endmodule',
                '`ifdef ABSENT\n`define X a // continuation \\ \n+ 1\n`endif\nmodule m; endmodule'
            ),
            (
                '`define CAT(a,b) a``b\nmodule m; endmodule',
                '`define CAT(a,b) a ``b\nmodule m; endmodule')
        ]
        with tempfile.TemporaryDirectory() as directory:
            for original, formatted in cases:
                with self.subTest(source=original):
                    self.assertNotEqual(
                        self.parse(original, directory),
                        self.parse(formatted, directory))

    def test_triple_quote_newlines_are_string_data(self):
        original = '`define S `"""a\\\na\\\nb`"""\nmodule m; endmodule\n'
        changed = original.replace('a\\\nb', 'a\\\r\nb')
        with tempfile.TemporaryDirectory() as directory:
            self.assertNotEqual(
                self.parse(original, directory),
                self.parse(changed, directory))


@unittest.skipUnless(
    SLANG_DRIVER, "Set SLANG_DRIVER to run runner integration tests")
class FormatterRunnerTests(unittest.TestCase):
    def run_formatter(
            self, sources, replacements=None, incdirs=(), formatter_rc=0):
        replacements = replacements or {}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            for relative, source in sources.items():
                path = inputs / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source)
            runner = VerihoggFormat.__new__(VerihoggFormat)
            runner.executable = "test-formatter"
            parser_paths = []

            def run(cmd, cwd, timeout):
                if cmd[0] == runner.executable:
                    for relative, replacement in replacements.items():
                        (Path(cwd) / "formatted" /
                         relative).write_text(replacement)
                    return "formatter log\n", formatter_rc
                parser_paths.append(cmd[-1])
                return VerihoggFormat._run(
                    runner, [SLANG_DRIVER] + cmd[1:], cwd, timeout)

            with mock.patch.object(runner, "_run", side_effect=run):
                result = runner.run(
                    str(root / "run"), {
                        "files":
                        [str(inputs / relative) for relative in sources],
                        "incdirs":
                        [str(inputs / relative) for relative in incdirs],
                        "defines": [],
                        "timeout": "30"
                    })
            for relative, source in sources.items():
                self.assertEqual((inputs / relative).read_text(), source)
            return result, parser_paths

    def test_file_macro_uses_identical_paths_in_both_parses(self):
        result, paths = self.run_formatter(
            {"input.sv": 'module m; localparam S = `__FILE__; endmodule\n'})
        self.assertEqual(result[1], 0, result[0])
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0], paths[1])

    def test_layout_passes_but_string_and_line_changes_fail(self):
        cases = [
            (
                'module m; localparam P=1+2; endmodule\n',
                '// new comment\nmodule m; localparam P = 1 + 2;\nendmodule\n',
                0),
            (
                'module m; localparam S="a b"; endmodule\n',
                'module m; localparam S="ab"; endmodule\n', 1),
            (
                'module m; localparam P=`__LINE__; endmodule\n',
                'module m;\nlocalparam P=`__LINE__; endmodule\n', 1),
        ]
        for original, formatted, expected in cases:
            with self.subTest(original=original):
                result, _ = self.run_formatter(
                    {"input.sv": original}, {"input.sv": formatted})
                self.assertEqual(result[1], expected, result[0])

    def test_same_basename_files_remain_distinct(self):
        result, paths = self.run_formatter(
            {
                "first/input.sv": "module first; endmodule\n",
                "second/input.sv": "module second; endmodule\n"
            }, {"first/input.sv": "module changed; endmodule\n"})
        self.assertEqual(result[1], 1, result[0])
        self.assertNotEqual(paths[0], paths[1])

    def test_includes_use_the_staged_header_in_each_phase(self):
        source = (
            '`include "value.svh"\n'
            'module m; localparam P=`VALUE; localparam S=`__FILE__; endmodule\n'
        )
        files = {"input.sv": source, "inc/value.svh": "`define VALUE 1\n"}
        for header, expected in (("`define VALUE  1\n", 0),
                                 ("`define VALUE 2\n", 1)):
            with self.subTest(header=header):
                result, _ = self.run_formatter(
                    files, {"inc/value.svh": header}, incdirs=("inc", ))
                self.assertEqual(result[1], expected, result[0])
                if expected:
                    self.assertIn(
                        "CST mismatch between original and formatted: input.sv",
                        result[0])

    def test_formatter_failure_is_returned_before_cst_comparison(self):
        result, paths = self.run_formatter(
            {"input.sv": "invalid syntax"}, formatter_rc=71)
        self.assertEqual(result[1], 71)
        self.assertIn("formatter log", result[0])
        self.assertFalse(paths)


if __name__ == "__main__":
    unittest.main()

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
"""Compare full slang CSTs, ignoring layout and ordinary comments.

This is a structural regression check, not a proof of semantic equivalence.
Retain directives and inactive code, including macro whitespace that can become
string data. Unknown macro callees are treated conservatively. Never discard
fields by names such as 'end': they can contain real tokens and trivia.
"""

import re

WHITESPACE = " \t\v\f\r\n"
WHITESPACE_KINDS = {"Whitespace", "EndOfLine"}
QUOTE_KINDS = {"MacroQuote", "MacroTripleQuote"}
EMPTY_EOF_TOKEN = {"kind": "EndOfFile", "text": ""}
OPEN_KINDS = {
    "OpenParenthesis", "OpenBracket", "OpenBrace", "ApostropheOpenBrace"
}
CLOSE_KINDS = {"CloseParenthesis", "CloseBracket", "CloseBrace"}
# These comments can control downstream tools. Keep their contents exactly.
# Custom comment dialects must be added here; ordinary prose is ignored.
TOOL_COMMENT = re.compile(
    r"^\s*(?:pragma|synopsys|synthesis|verilator|slang|verible|cadence|"
    r"ambit|quartus|altera|xilinx|vivado|vcs|lint|coverage|translate_off|"
    r"translate_on)\b", re.IGNORECASE)


def _ordinary_comment(text):
    if text.startswith("//") and "\n" not in text and "\r" not in text:
        content = text[2:]
    elif text.startswith("/*") and text.find("*/") == len(text) - 2:
        content = text[2:-2]
    else:
        return False
    return not TOOL_COMMENT.match(content)


def _ends_directive(trivia, continued=False):
    """Match slang's uncontinued-newline rule for a macro body."""
    for item in trivia:
        kind = item.get("kind")
        if kind == "EndOfLine":
            text = item["text"].replace("\r\n", "\n").replace("\r", "\n")
            for _ in range(text.count("\n")):
                if not continued:
                    return True
                continued = False
        elif kind == "LineComment":
            continued = item["text"].endswith("\\")
        else:
            continued = False
    return False


def _disabled(tokens):
    """Group inactive defines before stripping layout from their raw tokens.

    Only defines and pragmas consume a line. Fixed-arity directives such as
    undef and timescale need no artificial end-of-line marker.
    """
    result = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.get("text") not in {"`define", "`pragma"}:
            result.append(token)
            index += 1
            continue
        start = index
        index += 1
        node = {"kind": "$InactiveDirective", "directive": token}
        if token["text"] == "`define" and index < len(tokens):
            node["kind"] = "$InactiveDefine"
            node["name"] = tokens[index]
            index += 1
            if index < len(tokens) and tokens[index].get(
                    "kind") == "OpenParenthesis":
                trivia = tokens[index].get("trivia", [])
                escaped = node["name"].get("text", "").startswith("\\")
                if not trivia or (escaped and trivia == [{"kind": "Whitespace",
                                                          "text": " "}]):
                    formal_start = index
                    depth = 0
                    while index < len(tokens):
                        kind = tokens[index].get("kind")
                        depth += kind in OPEN_KINDS
                        depth -= kind in CLOSE_KINDS
                        index += 1
                        if depth == 0:
                            break
                    if depth:
                        # Malformed inactive text cannot be safely normalized.
                        result.append(
                            {
                                "kind": "$OpaqueMacro",
                                "raw": tokens[start:]
                            })
                        break
                    node["formals"] = tokens[formal_start:index]
        body_start = index
        while index < len(tokens):
            previous = tokens[index - 1]
            if _ends_directive(tokens[index].get("trivia", []),
                               previous.get("kind") == "LineContinuation"):
                break
            index += 1
        node["body"] = tokens[body_start:index]
        result.append(node)
    return result


def _prepare(obj):
    if isinstance(obj, list):
        return [_prepare(item) for item in obj]
    if not isinstance(obj, dict):
        return obj
    return {
        key: _disabled(_prepare(value))
        if key == "disabledTokens" else _prepare(value)
        for key, value in obj.items()
    }


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


class _Normalizer:
    def __init__(self, tree):
        dependencies = {}
        self.sensitive = set()
        for node in _walk(tree):
            if node.get("kind") not in {"DefineDirective", "$InactiveDefine"}:
                continue
            name = node.get("name", {}).get("text", "")
            refs = dependencies.setdefault(name, set())
            for token in node.get("body", []):
                if token.get("kind") in QUOTE_KINDS | {"MacroPaste"}:
                    self.sensitive.add(name)
                if token.get("kind") == "Directive":
                    refs.add(token.get("text", "")[1:])
        self.known = set(dependencies) | {"__FILE__", "__LINE__"}
        # A default can reach a stringifier through several wrappers. Include
        # inactive definitions and every redefinition; don't guess for unknowns.
        while True:
            newly_sensitive = {
                name
                for name, refs in dependencies.items()
                if any(self.is_sensitive(ref) for ref in refs)
            } - self.sensitive
            if not newly_sensitive:
                break
            self.sensitive.update(newly_sensitive)

    def is_sensitive(self, name):
        return name not in self.known or name in self.sensitive

    def trivia(self, items, keep_whitespace=False):
        if not isinstance(items, list):
            raise ValueError("CST comparison requires full, structured trivia")
        result = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(
                    "CST comparison requires full, structured trivia")
            kind = item.get("kind")
            text = item.get("text")
            blank = (
                kind == "DisabledText" and isinstance(text, str)
                and not text.strip(WHITESPACE))
            if kind in WHITESPACE_KINDS or blank:
                if keep_whitespace:
                    # CRLF and LF can produce different triple-quoted strings.
                    result.append(dict(item))
                continue
            if kind in {"Directive", "SkippedSyntax"}:
                if not isinstance(item.get("syntax"), dict):
                    raise ValueError("slang CST JSON omits directive syntax")
            if kind in {"LineComment", "BlockComment", "DisabledText"}:
                if isinstance(text, str) and _ordinary_comment(text):
                    continue
            result.append(self.normalize(item))
        return result

    def tokens(
            self,
            tokens,
            macro_body=False,
            keep_whitespace=False,
            formals=False,
            default_sensitive=False):
        result = []
        pending_trivia = []
        quote = None
        calls = []
        formal_depth = 0
        default_value = False
        previous = {}
        for index, token in enumerate(tokens):
            kind = token.get("kind")
            trivia = token.get("trivia", [])
            if formals and formal_depth == 1 and kind in {"Comma",
                                                          "CloseParenthesis"}:
                default_value = False
            preserve = (
                keep_whitespace or quote is not None or any(calls)
                or (default_value and default_sensitive))
            next_trivia = (
                tokens[index +
                       1].get("trivia", []) if index + 1 < len(tokens) else [])
            continuation = (
                kind == "LineContinuation" and next_trivia
                and next_trivia[0].get("kind") == "EndOfLine")
            if macro_body and continuation and not preserve:
                pending_trivia.extend(trivia)
                continue

            normalized = self.normalize(
                {
                    key: value
                    for key, value in token.items()
                    if key != "trivia"
                })
            normalized_trivia = self.trivia(pending_trivia + trivia, preserve)
            if normalized_trivia:
                normalized["trivia"] = normalized_trivia
            pending_trivia = []
            # Token pasting depends on adjacency, not on the number of spaces.
            if macro_body and (kind == "MacroPaste"
                               or previous.get("kind") == "MacroPaste"):
                normalized["$separated"] = bool(trivia)
            result.append(normalized)
            if kind in QUOTE_KINDS:
                if quote is None:
                    quote = kind
                elif kind == quote:
                    quote = None
            if kind == "OpenParenthesis":
                calls.append(
                    previous.get("kind") == "Directive"
                    and self.is_sensitive(previous.get("text", "")[1:]))
            elif kind == "CloseParenthesis" and calls:
                calls.pop()
            if formals:
                formal_depth += kind in OPEN_KINDS
                formal_depth -= kind in CLOSE_KINDS
                if formal_depth == 1 and kind == "Equals":
                    default_value = True
            previous = token
        return result

    def normalize(self, obj, default_sensitive=False):
        if isinstance(obj, list):
            return [self.normalize(item, default_sensitive) for item in obj]
        if not isinstance(obj, dict):
            return obj
        kind = obj.get("kind")
        if kind == "$OpaqueMacro":
            return obj
        if kind in {"DefineDirective", "$InactiveDefine"}:
            default_sensitive = self.is_sensitive(
                obj.get("name", {}).get("text", ""))
        result = {}
        for key, value in obj.items():
            if key == "trivia":
                value = self.trivia(value)
                if not value:
                    continue
            elif key == "body" and kind in {"DefineDirective",
                                            "$InactiveDefine"}:
                value = self.tokens(value, macro_body=True)
            elif key == "disabledTokens":
                value = self.tokens(value)
            elif key == "formals" and kind == "$InactiveDefine":
                value = self.tokens(
                    value, formals=True, default_sensitive=default_sensitive)
            elif key == "tokens" and kind in {"MacroActualArgument",
                                              "MacroArgumentDefault"}:
                value = self.tokens(
                    value,
                    keep_whitespace=(
                        kind == "MacroArgumentDefault" and default_sensitive))
            else:
                value = self.normalize(value, default_sensitive)
            if key == "endOfFile" and value == EMPTY_EOF_TOKEN:
                continue
            result[key] = value
        return result


def normalize_cst(obj):
    """Return a new CST retaining tokens, directives and significant trivia."""
    tree = _prepare(obj)
    return _Normalizer(tree).normalize(tree)

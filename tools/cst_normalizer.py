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
string data. Ignore case changes in numeric syntax while keeping macro text
exact. Unknown macro callees are treated conservatively. Never discard fields
by names such as 'end': they can contain real tokens and trivia.
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
NUMERIC_CASE_KINDS = {"IntegerBase", "IntegerLiteral", "UnbasedUnsizedLiteral"}
NUMERIC_EXPONENT_KINDS = {"RealLiteral", "TimeLiteral"}
ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                            "abcdefghijklmnopqrstuvwxyz")
# These comments can control downstream tools. Keep their contents exactly.
# Custom comment dialects must be added here; ordinary prose is ignored.
TOOL_COMMENT = re.compile(
    r"^\s*(?:pragma|synopsys|synthesis|verilator|slang|verible|cadence|"
    r"ambit|quartus|altera|xilinx|vivado|vcs|lint|coverage|translate_off|"
    r"translate_on)\b", re.IGNORECASE)


def _normalized_numeric_text(kind, value):
    if kind in NUMERIC_CASE_KINDS:
        return value.translate(ASCII_LOWER)
    if kind in NUMERIC_EXPONENT_KINDS:
        return re.sub(r"(?<=.)E(?=[+-]?[0-9])", "e", value)
    return value


def _ordinary_comment(text):
    if text.startswith("//") and "\n" not in text and "\r" not in text:
        content = text[2:]
    elif text.startswith("/*") and text.find("*/", 2) == len(text) - 2:
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

    def trivia(self, items, keep_whitespace=False, normalize_numeric=True):
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
            result.append(self.normalize(
                item, normalize_numeric=normalize_numeric))
        return result

    def tokens(
            self,
            tokens,
            macro_body=False,
            keep_whitespace=False,
            formals=False,
            default_sensitive=False,
            normalize_numeric=True):
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
                }, normalize_numeric=(normalize_numeric and quote is None
                                       and not any(calls)))
            # Slang lexes inactive based digits as Identifier tokens. Case in
            # such digits is still insignificant, provided they directly
            # follow the base token outside a macro argument.
            if (normalize_numeric and not any(calls) and quote is None
                    and kind == "Identifier" and not trivia
                    and previous.get("kind") == "IntegerBase"):
                base = previous.get("text", "")[-1:].lower()
                digits = {"b": r"[01xXzZ?_]+", "o": r"[0-7xXzZ?_]+",
                          "d": r"[0-9xXzZ?_]+",
                          "h": r"[0-9a-fA-FxXzZ?_]+"}.get(base)
                if digits and re.fullmatch(digits, token.get("text", "")):
                    normalized["text"] = token["text"].lower()
            normalized_trivia = self.trivia(
                pending_trivia + trivia, preserve, normalize_numeric)
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

    def normalize(self, obj, default_sensitive=False, normalize_numeric=True):
        if isinstance(obj, list):
            return [
                self.normalize(item, default_sensitive, normalize_numeric)
                for item in obj
            ]
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
                value = self.trivia(value,
                                    normalize_numeric=normalize_numeric)
                if not value:
                    continue
            elif key == "body" and kind in {"DefineDirective",
                                            "$InactiveDefine"}:
                value = self.tokens(value, macro_body=True,
                                    normalize_numeric=False)
            elif key == "disabledTokens":
                value = self.tokens(value, normalize_numeric=True)
            elif key == "formals" and kind == "$InactiveDefine":
                value = self.tokens(
                    value, formals=True, default_sensitive=default_sensitive,
                    normalize_numeric=False)
            elif key == "tokens" and kind in {"MacroActualArgument",
                                              "MacroArgumentDefault"}:
                value = self.tokens(
                    value,
                    keep_whitespace=(
                        kind == "MacroArgumentDefault" and default_sensitive),
                    normalize_numeric=False)
            else:
                value = self.normalize(value, default_sensitive,
                                       normalize_numeric)
            if key == "text" and normalize_numeric and isinstance(value, str):
                value = _normalized_numeric_text(kind, value)
            if key == "endOfFile" and value == EMPTY_EOF_TOKEN:
                continue
            result[key] = value
        return result


def normalize_cst(obj):
    """Return a new CST retaining tokens, directives and significant trivia."""
    tree = _prepare(obj)
    return _Normalizer(tree).normalize(tree)


def _line_macro_names(tree):
    dependencies = {}
    for node in _walk(tree):
        if node.get("kind") not in {"DefineDirective", "$InactiveDefine"}:
            continue
        name = node.get("name", {}).get("text", "")
        dependencies.setdefault(name, set()).update(
            token.get("text", "")[1:]
            for token in node.get("body", [])
            if token.get("kind") == "Directive")

    names = {"__LINE__"}
    while True:
        new_names = {
            name for name, refs in dependencies.items() if refs & names
        } - names
        if not new_names:
            return names
        names.update(new_names)


def _macro_call_lines(source, names):
    """Find logical call lines, excluding comments and string literals."""
    calls = {name: [] for name in names}
    index = 0
    line = 1
    line_offset = 0
    while index < len(source):
        char = source[index]
        following = source[index + 1:index + 2]
        if char == "\n":
            line += 1
        elif char == "/" and following == "/":
            end = source.find("\n", index + 2)
            index = len(source) if end < 0 else end
            continue
        elif char == "/" and following == "*":
            end = source.find("*/", index + 2)
            if end < 0:
                break
            line += source.count("\n", index, end + 2)
            index = end + 2
            continue
        elif char == '"':
            index += 1
            while index < len(source):
                if source[index] == "\\":
                    index += 2
                elif source[index] == '"':
                    break
                else:
                    if source[index] == "\n":
                        line += 1
                    index += 1
        elif char == "`":
            match = re.match(r"[a-zA-Z_][a-zA-Z_0-9$]*", source[index + 1:])
            if match:
                name = match.group()
                if name == "line":
                    directive = source[index + len(name) + 1:].split("\n", 1)[0]
                    number = re.match(r"[ \t]+([0-9]+)[ \t]+\"", directive)
                    if number:
                        # A `line directive numbers the following source line.
                        line_offset = int(number.group(1)) - line - 1
                if name in calls:
                    calls[name].append(line + line_offset)
                index += len(name) + 1
                continue
        index += 1
    return calls


def _line_expansion_pairs(original, formatted, original_source,
                          formatted_source):
    names = _line_macro_names(original) & _line_macro_names(formatted)
    original_calls = _macro_call_lines(original_source, names)
    formatted_calls = _macro_call_lines(formatted_source, names)
    return {
        pair
        for name in names
        if len(original_calls[name]) == len(formatted_calls[name])
        for pair in zip(original_calls[name], formatted_calls[name])
    }


def csts_match(original, formatted, original_source, formatted_source):
    """Compare CSTs while allowing only relocated `__LINE__ expansions."""
    original = normalize_cst(original)
    formatted = normalize_cst(formatted)
    if original == formatted:
        return True

    line_pairs = _line_expansion_pairs(original, formatted, original_source,
                                       formatted_source)

    def equal(lhs, rhs, in_definition=False):
        if type(lhs) is not type(rhs):
            return False
        if isinstance(lhs, list):
            return len(lhs) == len(rhs) and all(
                equal(left, right, in_definition)
                for left, right in zip(lhs, rhs))
        if isinstance(lhs, dict):
            if lhs.keys() != rhs.keys():
                return False
            in_definition |= lhs.get("kind") in {"DefineDirective",
                                                  "$InactiveDefine"}
            if (not in_definition and lhs.get("kind") == "IntegerLiteral"
                    and rhs.get("kind") == "IntegerLiteral"
                    and lhs.get("fromExpansion") is True
                    and rhs.get("fromExpansion") is True
                    and lhs.get("text", "").isdecimal()
                    and rhs.get("text", "").isdecimal()
                    and (int(lhs["text"]), int(rhs["text"])) in line_pairs):
                return all(
                    key == "text" or equal(lhs[key], rhs[key], in_definition)
                    for key in lhs)
            return all(equal(lhs[key], rhs[key], in_definition) for key in lhs)
        return lhs == rhs

    return equal(original, formatted)

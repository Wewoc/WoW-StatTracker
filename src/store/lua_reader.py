#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# lua_reader.py
# StatTracker - minimal reader for the Lua that WoW writes into the SavedVariables file
# (assignments to tables, strings, numbers, true/false/nil, comments). Pure text in, plain data out:
# stdlib only, no project imports (a leaf module). Moved out of stat_parser.py.

import re


class LuaError(Exception):
    pass


class LuaReader:
    """Minimal reader for what WoW writes into SavedVariables:
    assignments to tables, strings, numbers, true/false/nil, comments."""

    ESC = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b",
           "f": "\f", "v": "\v", "\\": "\\", '"': '"', "'": "'", "\n": "\n"}
    NUM = re.compile(r"-?(?:0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)")
    NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

    def __init__(self, text):
        self.s = text
        self.i = 0

    def err(self, msg):
        line = self.s.count("\n", 0, self.i) + 1
        raise LuaError(f"line {line}: {msg}")

    def ws(self):
        s, n = self.s, len(self.s)
        while self.i < n:
            c = s[self.i]
            if c.isspace():
                self.i += 1
            elif s.startswith("--", self.i):
                j = s.find("\n", self.i)
                self.i = n if j == -1 else j + 1
            else:
                break

    def parse_file(self):
        out = {}
        while True:
            self.ws()
            if self.i >= len(self.s):
                return out
            m = self.NAME.match(self.s, self.i)
            if not m:
                self.err("variable name expected")
            self.i = m.end()
            self.ws()
            if self.s[self.i:self.i + 1] != "=":
                self.err("'=' expected")
            self.i += 1
            out[m.group()] = self.value()

    def value(self):
        self.ws()
        s = self.s
        c = s[self.i:self.i + 1]
        if c == "{":
            return self.table()
        if c in ('"', "'"):
            return self.string()
        m = self.NUM.match(s, self.i)
        if m:
            self.i = m.end()
            t_ = m.group()
            if t_.lower().lstrip("-").startswith("0x"):
                return int(t_, 16)
            f = float(t_)
            return int(f) if f.is_integer() and "." not in t_ and "e" not in t_.lower() else f
        for lit, val in (("true", True), ("false", False), ("nil", None)):
            if s.startswith(lit, self.i):
                self.i += len(lit)
                return val
        self.err(f"unexpected character {c!r}")

    def string(self):
        s = self.s
        q = s[self.i]
        self.i += 1
        buf = []
        while True:
            if self.i >= len(s):
                self.err("string not terminated")
            c = s[self.i]
            if c == q:
                self.i += 1
                return "".join(buf)
            if c == "\\":
                self.i += 1
                e = s[self.i]
                if e.isdigit():
                    m = re.compile(r"\d{1,3}").match(s, self.i)
                    buf.append(chr(int(m.group())))
                    self.i = m.end()
                    continue
                buf.append(self.ESC.get(e, e))
                self.i += 1
            else:
                buf.append(c)
                self.i += 1

    def table(self):
        self.i += 1  # {
        result = {}
        pos = 1
        while True:
            self.ws()
            c = self.s[self.i:self.i + 1]
            if c == "":
                self.err("table not terminated")
            if c == "}":
                self.i += 1
                return result
            if c == "[":
                self.i += 1
                key = self.value()
                self.ws()
                if self.s[self.i:self.i + 1] != "]":
                    self.err("']' expected")
                self.i += 1
                self.ws()
                if self.s[self.i:self.i + 1] != "=":
                    self.err("'=' expected")
                self.i += 1
                result[key] = self.value()
            else:
                m = self.NAME.match(self.s, self.i)
                after = self.s[m.end():].lstrip()[:1] if m else ""
                if m and after == "=" and m.group() not in ("true", "false", "nil"):
                    self.i = m.end()
                    self.ws()
                    self.i += 1  # =
                    result[m.group()] = self.value()
                else:
                    result[pos] = self.value()
                    pos += 1
            self.ws()
            if self.s[self.i:self.i + 1] in (",", ";"):
                self.i += 1

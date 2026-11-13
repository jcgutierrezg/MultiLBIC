"""A static check of the .cir files here, for when no simulator is at hand.

It does not simulate anything. It catches the slips a simulator would
refuse: an undefined subcircuit, model or parameter, a subcircuit
called with the wrong number of pins, a node connected only once, a
duplicate designator. Run:  python check_netlists.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
NODES = {"R": 2, "C": 2, "L": 2, "V": 2, "I": 2, "B": 2, "D": 2, "M": 3,
         "E": 4, "G": 4, "S": 4}
HAS_MODEL = {"D", "M", "S"}
FUNCS = {"min", "max", "tanh", "mag", "ph", "v", "i", "time", "if"}
WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
NUMBER = re.compile(r"(?<![A-Za-z_0-9])[0-9][0-9.]*(e[-+]?[0-9]+)?(meg|[tgkmunpf])?", re.I)


def logical_lines(path: Path) -> list[str]:
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines()[1:]:
        line = raw.split(";")[0].rstrip()
        if not line.strip() or line.lstrip().startswith("*"):
            continue
        if line.lstrip().startswith("+") and out:
            out[-1] += " " + line.lstrip()[1:]
        else:
            out.append(line.strip())
    return out


def expand(path: Path) -> list[str]:
    lines: list[str] = []
    for line in logical_lines(path):
        if line.lower().startswith((".include", ".inc ", ".lib")):
            # an included file's first line is not a title
            inc = HERE / line.split()[1]
            lines += expand_included(inc)
        else:
            lines.append(line)
    return lines


def expand_included(path: Path) -> list[str]:
    text = "*\n" + path.read_text(encoding="utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        return logical_lines(tmp)
    finally:
        tmp.unlink()


def names_in(expr: str) -> set[str]:
    return {w.lower() for w in WORD.findall(NUMBER.sub(" ", expr))
            if w.lower() not in FUNCS}


def check(path: Path) -> list[str]:
    errors: list[str] = []
    lines = expand(path)
    subckts: dict[str, tuple[int, set[str]]] = {}
    models: set[str] = set()
    params: set[str] = set()
    # pass 1: definitions
    scope = None
    local_models: dict[str | None, set[str]] = {None: set()}
    for line in lines:
        low = line.lower()
        tok = line.split()
        if low.startswith(".subckt"):
            scope = tok[1].lower()
            pins = []
            sub_params = set()
            seen_params = False
            for t in tok[2:]:
                if t.lower() == "params:":
                    seen_params = True
                elif "=" in t or seen_params:
                    sub_params.add(t.split("=")[0].lower())
                else:
                    pins.append(t)
            subckts[scope] = (len(pins), sub_params)
            local_models[scope] = set()
        elif low.startswith(".ends"):
            scope = None
        elif low.startswith(".model"):
            local_models[scope].add(tok[1].lower())
            models.add(tok[1].lower())
        elif low.startswith(".param"):
            for m in re.finditer(r"([A-Za-z_]\w*)\s*=", line[6:]):
                params.add(m.group(1).lower())
        elif low.startswith(".step param"):
            params.add(tok[2].lower())
    # pass 2: uses
    scope = None
    seen: dict[str | None, set[str]] = {None: set()}
    node_count: dict[tuple[str | None, str], int] = {}
    for line in lines:
        low = line.lower()
        tok = line.split()
        if low.startswith(".subckt"):
            scope = tok[1].lower()
            seen[scope] = set()
            for t in tok[2:2 + subckts[scope][0]]:
                node_count[(scope, t.lower())] = 1  # a pin counts once
            continue
        if low.startswith(".ends"):
            scope = None
            continue
        known = params | (subckts[scope][1] if scope else set())
        for expr in re.findall(r"\{([^}]*)\}", line):
            for name in names_in(expr) - known:
                errors.append(f"undefined parameter {name!r}: {line[:60]}")
        if line.startswith("."):
            continue
        ref = tok[0].lower()
        if ref in seen[scope]:
            errors.append(f"duplicate designator {tok[0]}")
        seen[scope].add(ref)
        kind = tok[0][0].upper()
        if kind == "X":
            body = [t for t in tok[1:] if "=" not in t]
            name = body[-1].lower()
            nodes = body[:-1]
            if name not in subckts:
                errors.append(f"undefined subcircuit {body[-1]}: {line[:60]}")
            elif subckts[name][0] != len(nodes):
                errors.append(f"{tok[0]}: {len(nodes)} nodes for "
                              f"{body[-1]}, which has {subckts[name][0]}")
            else:
                given = {t.split("=")[0].lower() for t in tok[1:] if "=" in t}
                for extra in given - subckts[name][1]:
                    errors.append(f"{tok[0]}: {body[-1]} has no "
                                  f"parameter {extra!r}")
        elif kind in NODES:
            nodes = tok[1:1 + NODES[kind]]
            if kind in HAS_MODEL:
                model = tok[1 + NODES[kind]].lower()
                if model not in models:
                    errors.append(f"undefined model {model}: {line[:60]}")
        else:
            errors.append(f"unknown element {tok[0]}")
            nodes = []
        for n in nodes:
            key = (scope, n.lower())
            node_count[key] = node_count.get(key, 0) + 1
        if kind == "B":
            for n in re.findall(r"V\(([^)]*)\)", line, re.I):
                for part in n.split(","):
                    key = (scope, part.strip().lower())
                    node_count[key] = node_count.get(key, 0) + 1
    for (sc, node), count in sorted(node_count.items(), key=str):
        if node != "0" and count < 2 and node != "opt":
            where = f" in {sc}" if sc else ""
            errors.append(f"node {node!r}{where} is connected {count} time(s)")
    # measurements refer to nodes that exist
    top_nodes = {n for (sc, n) in node_count if sc is None}
    for line in lines:
        if line.lower().startswith(".meas"):
            for n in re.findall(r"V\(([^)]*)\)", line, re.I):
                for part in n.split(","):
                    if part.strip().lower() not in top_nodes:
                        errors.append(f"measured node {part!r} does not "
                                      f"exist: {line[:50]}")
    return errors


def main() -> int:
    bad = 0
    for path in sorted(HERE.glob("*.cir")):
        errors = check(path)
        print(f"{path.name}: {'ok' if not errors else ''}")
        for e in errors:
            print("   ", e)
        bad += bool(errors)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

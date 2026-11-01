#!/usr/bin/env python3
"""Walk the QMX's entire CAT-discoverable configuration menu (MM/ML) and dump
every item -- name, type, current value, and (for List/Mask items) the valid
choices -- to JSON.

This is the QMX equivalent of the IC-7300's menu_scan.py, except QMX's menu
manager is self-describing (MM<path>?; discovery), so no measurement or
guessing is needed -- just walk it.

Always walks by NUMERIC index, never by name: some menu item names are
themselves numeric strings (e.g. the "Choose filters" mask rows are named
"50", "100", "150"...), and the CAT manual is explicit that a purely-numeric
name path is parsed as an index, not a name lookup -- so a name-based walk
would silently break on exactly those rows.

Usage:
    python3 menu_dump.py [output.json]
"""

import json
import sys

from qmx import QMX, CATError

TYPE_NAMES = {
    0: "submenu",
    1: "action",
    2: "string",
    3: "number",
    4: "byte",
    5: "list",
    6: "info",
    7: "mask",
}


def walk(radio: QMX, path: list[int], depth: int = 0) -> list[dict]:
    items = []
    idx = 0
    while True:
        path_str = "|".join(str(p) for p in path + [idx])
        try:
            desc = radio.mm_query(path_str)
        except CATError:
            break  # no more siblings at this level
        parts = desc.split("|", 2)
        if len(parts) != 3:
            print(f"  ! unparseable discovery reply at {path_str}: {desc!r}", file=sys.stderr)
            idx += 1
            continue
        type_num, param2, name = parts
        type_num = int(type_num)
        node = {
            "index": idx,
            "name": name,
            "type": TYPE_NAMES.get(type_num, f"unknown({type_num})"),
        }

        is_grid = name.endswith("]") and "[" in name
        indent = "  " * (depth + 1)

        if type_num == 0:  # sub-menu
            print(f"{indent}[{idx}] {name}  (submenu)")
            if is_grid:
                node["columns"] = int(name.rsplit("[", 1)[1].rstrip("]"))
                node["rows"] = walk_grid(radio, path + [idx], node["columns"], depth + 1)
            else:
                node["children"] = walk(radio, path + [idx], depth + 1)

        elif type_num in (2, 3, 4):  # string / number / byte leaf
            node["field_len_or_range"] = param2
            try:
                node["value"] = radio.mm_get(path_str)
            except CATError as e:
                node["value_error"] = str(e)
            print(f"{indent}[{idx}] {name} = {node.get('value', node.get('value_error'))}")

        elif type_num in (5, 7):  # list / mask leaf
            node["list_type"] = int(param2)
            try:
                node["value"] = radio.mm_get(path_str)
            except CATError as e:
                node["value_error"] = str(e)
            try:
                node["choices"] = radio.ml_list_values(int(param2))
            except CATError:
                pass
            print(f"{indent}[{idx}] {name} = {node.get('value', node.get('value_error'))}"
                  f"  (choices: {node.get('choices', '?')})")

        elif type_num == 1:  # action/application
            print(f"{indent}[{idx}] {name}  (action, no value)")

        elif type_num == 6:  # info/dummy
            print(f"{indent}[{idx}] {name}  (info only)")

        items.append(node)
        idx += 1
    return items


def walk_grid(radio: QMX, path: list[int], columns: int, depth: int) -> list[dict]:
    """A grid page (like Band config.) is a list of ROWS, each a parameter
    that has one value per column (e.g. per band). Discover rows the normal
    way, then fetch every column's value for each leaf row."""
    rows = []
    row_idx = 0
    indent = "  " * (depth + 1)
    while True:
        row_path = "|".join(str(p) for p in path + [row_idx])
        try:
            desc = radio.mm_query(row_path)
        except CATError:
            break
        type_num, param2, name = desc.split("|", 2)
        type_num = int(type_num)
        row = {"index": row_idx, "name": name, "type": TYPE_NAMES.get(type_num, type_num)}
        values = []
        for col in range(columns):
            try:
                values.append(radio.mm_get(f"{row_path}[{col}]"))
            except CATError as e:
                values.append(f"ERROR: {e}")
        row["values"] = values
        print(f"{indent}[{row_idx}] {name}: {values}")
        rows.append(row)
        row_idx += 1
    return rows


def main() -> int:
    out_path = sys.argv[1] if len(sys.argv) > 1 else "menu_dump.json"
    with QMX() as radio:
        print(f"QMX firmware: {radio.version()}")
        tree = walk(radio, [])
    with open(out_path, "w") as f:
        json.dump(tree, f, indent=2)
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

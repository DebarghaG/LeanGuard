"""Print native Lean schema declarations from the pinned benchmark's tool definitions.

Maintainer utility only: output is reviewed and checked in, never dynamically loaded
from an agent's tools/list response. Unsupported schema constructs abort generation.
"""

import json

from leanguard.tau import TauAdapter


def string(s):
    return json.dumps(s, ensure_ascii=False)


def schema(s, root):
    supported = {
        "$defs",
        "$ref",
        "type",
        "title",
        "description",
        "default",
        "enum",
        "anyOf",
        "items",
        "properties",
        "required",
        "additionalProperties",
    }
    if set(s) - supported:
        raise ValueError(f"unsupported schema keywords: {set(s) - supported}")
    if "additionalProperties" in s and s["additionalProperties"] is not True:
        raise ValueError("constrained additionalProperties is not supported")
    if "$ref" in s:
        ref = s["$ref"]
        if not ref.startswith("#/$defs/"):
            raise ValueError(ref)
        return schema(root["$defs"][ref.split("/")[-1]], root)
    if "enum" in s:
        values = []
        for value in s["enum"]:
            if not isinstance(value, str):
                raise TypeError("non-string enum")
            values.append("Lean.Json.str " + string(value))
        return ".enum [" + ", ".join(values) + "]"
    if "anyOf" in s:
        return ".alternatives [" + ", ".join(schema(x, root) for x in s["anyOf"]) + "]"
    ty = s.get("type")
    if ty in {"string", "integer", "number", "boolean", "null"}:
        return "." + ty
    if ty == "array":
        return ".array (" + schema(s.get("items", {}), root) + ")"
    if ty == "object":
        required = "[" + ", ".join(map(string, s.get("required", []))) + "]"
        fields = ", ".join(
            "(" + string(k) + ", " + schema(v, root) + ")"
            for k, v in s.get("properties", {}).items()
        )
        return ".object " + required + " [" + fields + "]"
    if not s:
        return ".any"
    raise ValueError(s)


def wrap_lean(line):
    lines = []
    while len(line) > 100:
        quoted = escaped = False
        breaks = []
        for index, char in enumerate(line):
            if escaped:
                escaped = False
            elif char == "\\" and quoted:
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif char == " " and not quoted and 4 < index <= 100:
                breaks.append(index)
        if not breaks:
            raise ValueError("Lean token exceeds line width")
        split = breaks[-1]
        lines.append(line[:split])
        line = "    " + line[split + 1 :]
    return "\n".join([*lines, line])


def main():
    print("import LeanGuard.Schema\n\nnamespace LeanGuard.ToolSchemas\n")
    for domain in ("retail", "airline", "telecom"):
        print(f"def {domain} : List (String × Schema) := [")
        definitions = []
        for action, info in TauAdapter(domain).tool_schemas().items():
            s = info["parameters"]
            definitions.append("  (" + string(action) + ", " + schema(s, s) + ")")
        print(
            "\n".join(
                wrap_lean(d + ("," if i < len(definitions) - 1 else ""))
                for i, d in enumerate(definitions)
            )
        )
        print("]\n")
    print("end LeanGuard.ToolSchemas")


if __name__ == "__main__":
    main()

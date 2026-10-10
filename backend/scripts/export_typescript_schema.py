"""Generate `frontend/src/types/analysis.ts` from the Pydantic models.

Frontend and backend must agree on the analysis contract exactly, so the
TypeScript types are generated rather than hand-copied.  Regenerate after any
change to `app/schemas/`:

    /path/to/venv/bin/python backend/scripts/export_typescript_schema.py

The generated file is checked in so `npm run build` works without Python.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
OUTPUT = REPO_ROOT / "frontend" / "src" / "types" / "analysis.ts"

# Emitted as named exports; everything they reference is pulled in transitively.
ROOT_MODELS = [
    "ApplicationRequirements",
    "RequirementSignals",
    "Assumption",
    "OpenQuestion",
    "FieldProvenance",
    "AnalysisOptions",
    "AnalysisRequest",
    "WorkloadProfile",
    "ComponentInventoryItem",
    "Component",
    "ComponentTraits",
    "SecurityEvidence",
    "Connection",
    "TrustBoundary",
    "NodePosition",
    "ArchitectureGraph",
    "ServiceMapping",
    "MappingRow",
    "SuitabilityFactor",
    "ComponentSuitability",
    "SuitabilityBand",
    "SuitabilityMethodology",
    "SuitabilityReport",
    "SecurityFinding",
    "VerificationGap",
    "SecurityReport",
    "CostLineItem",
    "CostScenario",
    "CostSensitivity",
    "CostReport",
    "MigrationChange",
    "MigrationPhase",
    "MigrationReport",
    "AiAttempt",
    "Limitation",
    "AnalysisResult",
    "ProjectSummary",
    "ProjectDetail",
    "ProjectCreateRequest",
    "ProjectUpdateRequest",
    "HealthResponse",
    "ApiError",
    "ErrorResponse",
    "AiStatusPayload",
    "TemplateForm",
    "TemplateCard",
]

PRIMITIVES = {
    "string": "string",
    "number": "number",
    "integer": "number",
    "boolean": "boolean",
    "null": "null",
    "object": "Record<string, unknown>",
    "array": "unknown[]",
}


class Emitter:
    """Render a JSON-Schema (as produced by pydantic) into TypeScript declarations."""

    def __init__(self, defs: dict[str, Any]) -> None:
        self.defs = defs
        self.bodies: dict[str, str] = {}
        self.pending: list[str] = []

    # ------------------------------------------------------------------ helpers

    def ref(self, spec: dict[str, Any]) -> str:
        return str(spec["$ref"]).split("/")[-1]

    def describe(self, spec: dict[str, Any], *, limit: int = 160) -> str:
        text = " ".join(str(spec.get("description") or "").split())
        if not text:
            return ""
        return text[:limit] + ("…" if len(text) > limit else "")

    def doc(self, text: str, indent: int) -> list[str]:
        if not text:
            return []
        pad = "  " * indent
        return [f"{pad}/** {line} */" for line in wrap(text, 96 - indent * 2)]

    # -------------------------------------------------------------------- types

    def ts(self, spec: Any, indent: int = 1) -> str:
        """Return a TypeScript type expression, self-contained and indented."""
        if spec is True or spec in ({}, None):
            return "unknown"
        if spec is False:
            return "never"
        if not isinstance(spec, dict):
            return "unknown"

        if "$ref" in spec:
            name = self.ref(spec)
            self.enqueue(name)
            return name

        for wrapper in ("anyOf", "oneOf"):
            if wrapper in spec:
                parts: list[str] = []
                for item in spec[wrapper]:
                    rendered = self.ts(item, indent)
                    if rendered not in parts:
                        parts.append(rendered)
                return " | ".join(parts) if len(parts) > 1 else parts[0]

        if "const" in spec:
            return json.dumps(spec["const"])

        if "enum" in spec and spec.get("type") in (None, "string"):
            return " | ".join(json.dumps(value) for value in spec["enum"])

        kind = spec.get("type")
        if isinstance(kind, list):
            parts = [self.ts({**spec, "type": item}, indent) for item in kind]
            unique: list[str] = []
            for part in parts:
                if part not in unique:
                    unique.append(part)
            return " | ".join(unique)

        if kind == "array":
            inner = self.ts(spec.get("items", True), indent)
            return f"({inner})[]" if ("|" in inner or "\n" in inner) else f"{inner}[]"

        if isinstance(kind, str) and kind in PRIMITIVES and kind not in {"object", "array"}:
            return PRIMITIVES[kind]

        if kind in {"object", None}:
            if not any(key in spec for key in ("properties", "additionalProperties")):
                return "Record<string, unknown>"
            properties = spec.get("properties") or {}
            if not properties:
                extra = spec.get("additionalProperties")
                if isinstance(extra, dict) or extra is True:
                    return f"Record<string, {self.ts(extra, indent)}>"
                return "Record<string, unknown>"
            required = set(spec.get("required", []))
            lines = ["{"]
            for name, field in properties.items():
                key = name if name.isidentifier() else json.dumps(name)
                optional = "" if name in required else "?"
                docs = self.describe(field)
                if docs:
                    lines.extend(self.doc(docs, 1))
                lines.append(f"  {key}{optional}: {self.ts(field, indent + 1)};".replace(";\n", ";"))
                lines[-1] = lines[-1].replace(";\n;", ";").rstrip()
                if lines[-1].endswith("{"):
                    lines.pop()
                    rendered = self.ts(field, indent + 1)
                    lines.append(f"  {key}{optional}: " + rendered)
            lines.append("}")
            return "\n".join(lines)

        return "unknown"

    # ------------------------------------------------------------------ bodies

    def enqueue(self, name: str) -> None:
        if name in self.bodies or name not in self.defs or name in self.pending:
            return
        self.pending.append(name)
        while self.pending:
            current = self.pending.pop(0)
            if current in self.bodies or current not in self.defs:
                continue
            self.bodies[current] = self.interface(current, self.defs[current])

    def interface(self, name: str, spec: dict[str, Any]) -> str:
        enum_values = spec.get("enum")
        if enum_values is not None and spec.get("type") in (None, "string"):
            union = " | ".join(json.dumps(value) for value in enum_values)
            return f"export type {name} =\n{'  '}{union}\n"

        required = set(spec.get("required", []))
        lines = [f"export interface {name} {{"]
        for field_name, field in (spec.get("properties") or {}).items():
            key = field_name if field_name.isidentifier() else json.dumps(field_name)
            optional = "" if field_name in required else "?"
            rendered = self.ts(field, 1)
            docs = " ".join(filter(None, [self.describe(field)]))
            if docs:
                lines.extend(self.doc(docs, 1))
            if "\n" in rendered:
                head, *rest = rendered.split("\n")
                lines.append(f"  {key}{optional}: {head}")
                lines.extend(rest)
                lines.append("  };")
            else:
                lines.append(f"  {key}{optional}: {rendered};")
        lines.append("}")
        return "\n".join(lines) + "\n"


def wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > width and current:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def main() -> int:
    sys.path.insert(0, str(BACKEND_ROOT))
    from app.schemas import analysis, architecture, common, reports, requirements  # noqa: F401

    modules = [analysis, architecture, reports, requirements]
    defs: dict[str, Any] = {}
    roots: dict[str, Any] = {}
    for module in modules:
        for name in dir(module):
            candidate = getattr(module, name)
            if hasattr(candidate, "model_json_schema") and name in set(ROOT_MODELS):
                schema = candidate.model_json_schema(ref_template="#/$defs/{model}")
                for key, value in (schema.get("$defs") or {}).items():
                    defs.setdefault(key, value)
                body = {key: value for key, value in schema.items() if key not in {"$defs", "$schema"}}
                defs.setdefault(name, body)
                roots[name] = body

    missing = [name for name in ROOT_MODELS if name not in defs]
    if missing:
        print(f"warning: models not found: {', '.join(missing)}", file=sys.stderr)

    emitter = Emitter(defs)
    header = [
        "/**",
        " * NYX analysis contract — TypeScript types.",
        " *",
        " * GENERATED by `backend/scripts/export_typescript_schema.py` from the Pydantic",
        " * models in `backend/app/schemas/`.  Do not edit by hand: change the model, then",
        " * regenerate, so the client and server can never drift apart silently.",
        " *",
        f" * Schema version: {common.SCHEMA_VERSION}",
        " */",
        "",
        f"export const SCHEMA_VERSION = {json.dumps(common.SCHEMA_VERSION)} as const",
        "",
    ]
    blocks: list[str] = [
        f"/** Generated {datetime.now().strftime('%Y-%m-%d')} from `app/schemas`. */"
    ]
    for name in ROOT_MODELS:
        if name in defs:
            emitter.enqueue(name)
    ordered = [name for name in ROOT_MODELS if name in emitter.bodies]
    ordered += [name for name in emitter.bodies if name not in ordered]
    for name in ordered:
        blocks.append(emitter.bodies[name])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(header) + "\n" + "\n".join(blocks).replace("\n\n\n", "\n\n")
    OUTPUT.write_text(text.rstrip() + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

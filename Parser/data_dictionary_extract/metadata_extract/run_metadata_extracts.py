from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4


VIEW_NAMES = (
    "databasesv",
    "tablesv",
    "columnsv",
    "indicesv",
    "partitioningconstraintsv",
    "tabletextv",
)

MODE_NAMES = ("full", "incremental")
VARIANT_NAMES = ("standard", "export")


@dataclass(frozen=True)
class RenderedTemplate:
    view_name: str
    mode: str
    variant: str
    template_path: Path
    rendered_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render and optionally execute Teradata metadata extract SQL templates.",
    )
    parser.add_argument(
        "--source-system-name",
        required=True,
        help="Value rendered into source_system_name.",
    )
    parser.add_argument(
        "--mode",
        choices=("full", "incremental", "both"),
        default="full",
        help="Which extract mode to render.",
    )
    parser.add_argument(
        "--variant",
        choices=("standard", "export", "both"),
        default="standard",
        help="Which template variant to render.",
    )
    parser.add_argument(
        "--watermark-ts",
        help="Required for incremental mode. Format: YYYY-MM-DD HH:MM:SS.",
    )
    parser.add_argument(
        "--extract-run-id",
        help="Optional orchestration run id. If omitted, a UTC timestamp plus UUID is generated.",
    )
    parser.add_argument(
        "--template-dir",
        default=str(Path(__file__).resolve().parent),
        help="Directory containing SQL templates.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent / "rendered"),
        help="Directory where rendered SQL files are written.",
    )
    parser.add_argument(
        "--views",
        nargs="+",
        choices=VIEW_NAMES,
        help="Optional subset of views to render.",
    )
    parser.add_argument(
        "--delimiter",
        default="§",
        help="Field delimiter used only by export variants.",
    )
    parser.add_argument(
        "--escape-character",
        default="\\",
        help="Escape character used only by export variants.",
    )
    parser.add_argument(
        "--record-terminator",
        default="ENDREC",
        help="Record terminator used only by export variants.",
    )
    parser.add_argument(
        "--execute-command-template",
        help=(
            "Optional shell command template for running each rendered SQL file. "
            "Available tokens: {sql_file}, {log_file}, {view_name}, {mode}, {variant}."
        ),
    )
    parser.add_argument(
        "--manifest-path",
        help="Optional path for a JSON manifest of rendered and executed files.",
    )
    return parser.parse_args()


def build_extract_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_{uuid4().hex}"


def quote_sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def resolve_modes(mode: str) -> tuple[str, ...]:
    if mode == "both":
        return MODE_NAMES
    return (mode,)


def resolve_variants(variant: str) -> tuple[str, ...]:
    if variant == "both":
        return VARIANT_NAMES
    return (variant,)


def validate_args(args: argparse.Namespace) -> None:
    modes = resolve_modes(args.mode)
    if "incremental" in modes and not args.watermark_ts:
        raise ValueError("--watermark-ts is required when mode includes incremental.")


def template_file_name(view_name: str, mode: str, variant: str) -> str:
    if variant == "standard":
        return f"{view_name}_{mode}.sql"
    return f"{view_name}_{mode}_export.sql"


def template_relative_path(view_name: str, mode: str, variant: str) -> Path:
    file_name = template_file_name(view_name, mode, variant)
    if variant == "standard":
        return Path("standard") / file_name
    return Path(file_name)


def build_replacements(args: argparse.Namespace, extract_run_id: str) -> dict[str, str]:
    replacements = {
        "?source_system_name_literal": quote_sql_literal(args.source_system_name),
        "?extract_run_id_literal": quote_sql_literal(extract_run_id),
        "?delimiter_literal": quote_sql_literal(args.delimiter),
        "?escaped_delimiter_literal": quote_sql_literal(args.escape_character + args.delimiter),
        "?record_terminator_literal": quote_sql_literal(args.record_terminator),
    }
    if args.watermark_ts:
        replacements["?watermark_ts"] = args.watermark_ts
    return replacements


def render_template(template_text: str, replacements: dict[str, str]) -> str:
    rendered = template_text
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    return rendered


def iter_templates(
    template_dir: Path,
    output_dir: Path,
    view_names: Iterable[str],
    modes: Iterable[str],
    variants: Iterable[str],
) -> list[RenderedTemplate]:
    templates: list[RenderedTemplate] = []
    for view_name in view_names:
        for mode in modes:
            for variant in variants:
                template_path = template_dir / template_relative_path(view_name, mode, variant)
                if not template_path.exists():
                    raise FileNotFoundError(f"Template not found: {template_path}")
                rendered_name = template_path.stem + ".rendered.sql"
                templates.append(
                    RenderedTemplate(
                        view_name=view_name,
                        mode=mode,
                        variant=variant,
                        template_path=template_path,
                        rendered_path=output_dir / rendered_name,
                    )
                )
    return templates


def execute_rendered_template(command_template: str, rendered: RenderedTemplate) -> dict[str, object]:
    log_file = rendered.rendered_path.with_suffix(".log")
    command = command_template.format(
        sql_file=str(rendered.rendered_path),
        log_file=str(log_file),
        view_name=rendered.view_name,
        mode=rendered.mode,
        variant=rendered.variant,
    )
    completed = subprocess.run(command, shell=True, check=False, text=True)
    return {
        "command": command,
        "exit_code": completed.returncode,
        "log_file": str(log_file),
    }


def main() -> int:
    args = parse_args()
    validate_args(args)

    template_dir = Path(args.template_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    extract_run_id = args.extract_run_id or build_extract_run_id()
    replacements = build_replacements(args, extract_run_id)
    view_names = tuple(args.views) if args.views else VIEW_NAMES
    modes = resolve_modes(args.mode)
    variants = resolve_variants(args.variant)

    templates = iter_templates(template_dir, output_dir, view_names, modes, variants)
    manifest: list[dict[str, object]] = []

    for template in templates:
        template_text = template.template_path.read_text(encoding="utf-8")
        rendered_sql = render_template(template_text, replacements)
        template.rendered_path.write_text(rendered_sql, encoding="utf-8")

        manifest_row: dict[str, object] = {
            "view_name": template.view_name,
            "mode": template.mode,
            "variant": template.variant,
            "template_path": str(template.template_path),
            "rendered_path": str(template.rendered_path),
            "extract_run_id": extract_run_id,
        }

        if args.execute_command_template:
            manifest_row["execution"] = execute_rendered_template(
                args.execute_command_template,
                template,
            )

        manifest.append(manifest_row)
        print(f"Rendered {template.template_path.name} -> {template.rendered_path}")

    if args.manifest_path:
        manifest_path = Path(args.manifest_path).resolve()
    else:
        manifest_path = output_dir / "metadata_extract_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest written to {manifest_path}")
    print(f"extract_run_id={extract_run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

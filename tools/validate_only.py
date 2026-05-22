#!/usr/bin/env python3
"""Validador standalone de layout de arquivos do SCION.

Resumo: Reaproveita os validadores existentes (format_detector,
dict_flat_file_reader, dict_batch_validator, teradata_parser) para
validar arquivos suportados pelo SCION SEM persistir nada no banco.
Gera relatorio em TXT e JSON na mesma pasta dos arquivos.

Formatos suportados:
    - DICT_* (6 layouts do dicionario Teradata) -> readers oficiais do SCION
    - PARSER_LINEAGE (JSON DataDNA) -> teradata_parser.parse()
    - DBQL (pdcr_log_*.dat) -> validacao heuristica (delimitador + arity consistente)
    - OBJECT_USAGE (pdcr_object_usage_*.dat) -> validacao heuristica

Uso:
    python tools/validate_only.py --dir "Arquivos"
    python tools/validate_only.py --dir "Arquivos" --lang en --recursive
    python tools/validate_only.py --files arq1.dat arq2.json --lang es

Idiomas suportados: pt-br (default), es, en.

Saidas:
    - Relatorio TXT e JSON salvos na pasta dos arquivos
      (nome: scion_validacao_YYYYMMDD_HHMMSS.txt/.json).
    - exit 0: todos os arquivos validos
    - exit 1: pelo menos um arquivo invalido
    - exit 2: erro de invocacao
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Resumo: Ajusta sys.path para permitir importar modulos do backend
# sem instalar como pacote.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_PATH = PROJECT_ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app.metadata.format_detector import detect, ContentType  # noqa: E402
from app.metadata import dict_flat_file_reader as r  # noqa: E402
from app.metadata.dict_batch_validator import (  # noqa: E402
    validate_batch,
    BatchConsistencyError,
)
from app.metadata.dict_flat_file_reader import DictFlatFileError  # noqa: E402
from app.parser_ingest import teradata_parser  # noqa: E402
from app.parser_ingest.teradata_parser import ParserPayloadError  # noqa: E402

# Resumo: Tipos heuristicos (sem reader oficial no SCION). Tratados em-script.
CT_DBQL = "dbql"
CT_OBJECT_USAGE = "object_usage"

# Resumo: Prefixos de nome de arquivo usados como fallback de deteccao
# quando format_detector.detect() retornar UNKNOWN.
_HEURISTIC_FILENAME_PREFIXES = {
    "pdcr_log_": CT_DBQL,
    "pdcr_object_usage_": CT_OBJECT_USAGE,
}

# Resumo: Delimitador padrao Teradata (mesmo dos DICT_*).
_HEURISTIC_DELIMITER = "§"
_HEURISTIC_RECORD_TERMINATOR = "ENDREC"
# Resumo: Quantos registros amostrar para checar consistencia de arity.
_HEURISTIC_SAMPLE_SIZE = 1000


# ──── Dicionario de traducoes ──────────────────────────────────────────────
# Resumo: Todas as strings visiveis ao usuario. Chaves estaveis;
# texto sem acentos para evitar problemas de encoding em terminais Windows.
SUPPORTED_LANGS = ("pt-br", "es", "en")
DEFAULT_LANG = "pt-br"

I18N: Dict[str, Dict[str, str]] = {
    "pt-br": {
        # Terminal
        "header_title": "SCION - Validador de Layout de Arquivos",
        "files_to_validate": "Arquivos a validar : {n}",
        "output_folder": "Pasta de saida     : {path}",
        "validating_file": "[{i}/{total}] Validando: {name} ({size})",
        "step_detect": "   -> Detectando formato e tipo de conteudo...",
        "step_type_detected": "   -> Tipo detectado: {ct} (confianca: {conf})",
        "step_layout": "   -> Validando layout (delimitador, arity, encoding)...",
        "step_ok": "   -> OK: {n} registros validados em {ms} ms",
        "step_layout_error": "   -> LAYOUT INVALIDO ({ms} ms)",
        "step_unsupported": "   -> AVISO: tipo nao suportado pelo validador",
        "step_read_error_notfound": "   -> ERRO: arquivo nao encontrado",
        "step_read_error_io": "   -> ERRO ao ler arquivo: {err}",
        "step_unexpected": "   -> ERRO inesperado: {tp}: {err}",
        "batch_check": "Validando consistencia do batch (identidade + drift temporal)...",
        "batch_ok": "   -> Batch consistente. Snapshot: {label}",
        "batch_inconsistent": "   -> INCONSISTENCIA DETECTADA no batch",
        "report_txt_gen": "Gerando relatorio TXT : {name}",
        "report_json_gen": "Gerando relatorio JSON: {name}",
        "done": "Concluido em {sec} s. Status do batch: {status}",
        "reports_saved": "Relatorios salvos em: {path}",
        "no_files": "erro: nenhum arquivo encontrado para validar.",
        "not_a_dir": "erro: --dir nao e diretorio: {path}",
        # Relatorio
        "rep_title": "SCION - Validacao de Layout de Arquivos",
        "rep_lang": "Idioma do relatorio : {lang}",
        "rep_generated_at": "Gerado em           : {when}",
        "rep_files_analyzed": "Arquivos analisados : {n}",
        "rep_total_records": "Total de registros  : {n}",
        "rep_total_time": "Tempo total         : {ms} ms",
        "rep_batch_status": "Status do batch     : {status}",
        "rep_snapshot": "Snapshot            : {label}",
        "rep_file": "Arquivo : {name}",
        "rep_size": "Tamanho : {n} bytes",
        "rep_format": "Formato : {fmt} / {ct} (confianca: {conf})",
        "rep_reason": "Motivo  : {reason}",
        "rep_records": "Registros          : {n}",
        "rep_source": "source_system_name : {v}",
        "rep_run_id": "extract_run_id     : {v}",
        "rep_snapshot_date": "snapshot_date      : {v}",
        "rep_extracted_at": "extracted_at_utc   : {v}",
        "rep_parse_time": "Tempo de parse     : {ms} ms",
        "rep_status": "Status  : {status}",
        "rep_errors": "Erros   :",
        "rep_batch_errors_section": "ERROS DE CONSISTENCIA DE BATCH:",
        # Status (mantemos chave tecnica + label traduzida)
        "status_ok": "OK",
        "status_partial": "PARCIAL",
        "status_failed": "FALHA",
        "status_inconsistent": "INCONSISTENTE",
        "status_pending": "PENDENTE",
        "status_layout_error": "LAYOUT INVALIDO",
        "status_read_error": "ERRO DE LEITURA",
        "status_unsupported": "NAO SUPORTADO",
        # argparse helps
        "help_dir": "Diretorio com arquivos .dat",
        "help_files": "Lista explicita de arquivos",
        "help_skip_batch": "Pula validacao de consistencia entre arquivos do batch",
        "help_lang": "Idioma do relatorio e terminal: pt-br (default), es, en",
        # Erro de content-type nao suportado dentro do relatorio
        "err_unsupported_ct": (
            "Content-type nao suportado pelo validador: {ct}."
        ),
        "err_file_not_found": "Arquivo nao encontrado: {path}",
        "err_read_bytes": "Falha ao ler bytes iniciais: {err}",
        "err_unexpected": "Erro inesperado ({tp}): {err}",
        "err_validate_batch_unexpected": "Erro inesperado em validate_batch ({tp}): {err}",
        "err_invalid_json": "JSON invalido: {err}",
        "err_parser_payload": "Payload do parser invalido: {err}",
        # Etapas especificas de PARSER_LINEAGE
        "step_parser_json_load": "   -> Carregando JSON do parser...",
        "step_parser_validate": "   -> Validando payload do parser (teradata_parser.parse)...",
        "step_parser_ok": "   -> OK: {containers} containers, {datasets} datasets, {processes} processos, {steps} steps em {ms} ms",
        # Etapas especificas de DBQL/ObjectUsage
        "step_heuristic_detect": "   -> Detectado por nome: {ct} (sem reader oficial; validacao heuristica)",
        "step_heuristic_scan": "   -> Lendo arquivo e validando arity consistente...",
        "step_heuristic_ok": "   -> OK: {n} registros, {fields} campos/registro, terminador={term} em {ms} ms",
        "step_heuristic_drift": "   -> INCONSISTENCIA: registro #{rec} tem {got} campos, esperado {exp}",
        # Campos adicionais do relatorio
        "rep_parse_run_id": "parse_run_id       : {v}",
        "rep_parse_timestamp": "parse_timestamp    : {v}",
        "rep_parser_platform": "platform           : {v}",
        "rep_parser_counts": "Contagens          : {v}",
        "rep_field_count": "Campos por registro: {n}",
        "rep_record_terminator": "Terminador         : {v}",
        "rep_source_system": "source_system_name : {v}",
    },
    "es": {
        "header_title": "SCION - Validador de Disenio de Archivos",
        "files_to_validate": "Archivos a validar : {n}",
        "output_folder": "Carpeta de salida  : {path}",
        "validating_file": "[{i}/{total}] Validando: {name} ({size})",
        "step_detect": "   -> Detectando formato y tipo de contenido...",
        "step_type_detected": "   -> Tipo detectado: {ct} (confianza: {conf})",
        "step_layout": "   -> Validando disenio (delimitador, arity, encoding)...",
        "step_ok": "   -> OK: {n} registros validados en {ms} ms",
        "step_layout_error": "   -> DISENIO INVALIDO ({ms} ms)",
        "step_unsupported": "   -> AVISO: tipo no soportado por el validador",
        "step_read_error_notfound": "   -> ERROR: archivo no encontrado",
        "step_read_error_io": "   -> ERROR al leer archivo: {err}",
        "step_unexpected": "   -> ERROR inesperado: {tp}: {err}",
        "batch_check": "Validando consistencia del lote (identidad + deriva temporal)...",
        "batch_ok": "   -> Lote consistente. Snapshot: {label}",
        "batch_inconsistent": "   -> INCONSISTENCIA DETECTADA en el lote",
        "report_txt_gen": "Generando informe TXT : {name}",
        "report_json_gen": "Generando informe JSON: {name}",
        "done": "Finalizado en {sec} s. Estado del lote: {status}",
        "reports_saved": "Informes guardados en: {path}",
        "no_files": "error: no se encontraron archivos para validar.",
        "not_a_dir": "error: --dir no es directorio: {path}",
        "rep_title": "SCION - Validacion de Disenio de Archivos",
        "rep_lang": "Idioma del informe  : {lang}",
        "rep_generated_at": "Generado el         : {when}",
        "rep_files_analyzed": "Archivos analizados : {n}",
        "rep_total_records": "Total de registros  : {n}",
        "rep_total_time": "Tiempo total        : {ms} ms",
        "rep_batch_status": "Estado del lote     : {status}",
        "rep_snapshot": "Snapshot            : {label}",
        "rep_file": "Archivo : {name}",
        "rep_size": "Tamanio : {n} bytes",
        "rep_format": "Formato : {fmt} / {ct} (confianza: {conf})",
        "rep_reason": "Motivo  : {reason}",
        "rep_records": "Registros          : {n}",
        "rep_source": "source_system_name : {v}",
        "rep_run_id": "extract_run_id     : {v}",
        "rep_snapshot_date": "snapshot_date      : {v}",
        "rep_extracted_at": "extracted_at_utc   : {v}",
        "rep_parse_time": "Tiempo de parseo   : {ms} ms",
        "rep_status": "Estado  : {status}",
        "rep_errors": "Errores :",
        "rep_batch_errors_section": "ERRORES DE CONSISTENCIA DE LOTE:",
        "status_ok": "OK",
        "status_partial": "PARCIAL",
        "status_failed": "FALLO",
        "status_inconsistent": "INCONSISTENTE",
        "status_pending": "PENDIENTE",
        "status_layout_error": "DISENIO INVALIDO",
        "status_read_error": "ERROR DE LECTURA",
        "status_unsupported": "NO SOPORTADO",
        "help_dir": "Directorio con archivos .dat",
        "help_files": "Lista explicita de archivos",
        "help_skip_batch": "Omite validacion de consistencia entre archivos del lote",
        "help_lang": "Idioma del informe y terminal: pt-br (default), es, en",
        "err_unsupported_ct": (
            "Content-type no soportado por el validador: {ct}."
        ),
        "err_file_not_found": "Archivo no encontrado: {path}",
        "err_read_bytes": "Fallo al leer bytes iniciales: {err}",
        "err_unexpected": "Error inesperado ({tp}): {err}",
        "err_validate_batch_unexpected": "Error inesperado en validate_batch ({tp}): {err}",
        "err_invalid_json": "JSON invalido: {err}",
        "err_parser_payload": "Payload del parser invalido: {err}",
        "step_parser_json_load": "   -> Cargando JSON del parser...",
        "step_parser_validate": "   -> Validando payload del parser (teradata_parser.parse)...",
        "step_parser_ok": "   -> OK: {containers} containers, {datasets} datasets, {processes} procesos, {steps} steps en {ms} ms",
        "step_heuristic_detect": "   -> Detectado por nombre: {ct} (sin reader oficial; validacion heuristica)",
        "step_heuristic_scan": "   -> Leyendo archivo y validando arity consistente...",
        "step_heuristic_ok": "   -> OK: {n} registros, {fields} campos/registro, terminador={term} en {ms} ms",
        "step_heuristic_drift": "   -> INCONSISTENCIA: registro #{rec} tiene {got} campos, esperado {exp}",
        "rep_parse_run_id": "parse_run_id       : {v}",
        "rep_parse_timestamp": "parse_timestamp    : {v}",
        "rep_parser_platform": "platform           : {v}",
        "rep_parser_counts": "Conteos            : {v}",
        "rep_field_count": "Campos por registro: {n}",
        "rep_record_terminator": "Terminador         : {v}",
        "rep_source_system": "source_system_name : {v}",
    },
    "en": {
        "header_title": "SCION - File Layout Validator",
        "files_to_validate": "Files to validate  : {n}",
        "output_folder": "Output folder      : {path}",
        "validating_file": "[{i}/{total}] Validating: {name} ({size})",
        "step_detect": "   -> Detecting format and content type...",
        "step_type_detected": "   -> Detected type: {ct} (confidence: {conf})",
        "step_layout": "   -> Validating layout (delimiter, arity, encoding)...",
        "step_ok": "   -> OK: {n} records validated in {ms} ms",
        "step_layout_error": "   -> INVALID LAYOUT ({ms} ms)",
        "step_unsupported": "   -> WARNING: type not supported by validator",
        "step_read_error_notfound": "   -> ERROR: file not found",
        "step_read_error_io": "   -> ERROR reading file: {err}",
        "step_unexpected": "   -> Unexpected ERROR: {tp}: {err}",
        "batch_check": "Validating batch consistency (identity + temporal drift)...",
        "batch_ok": "   -> Batch consistent. Snapshot: {label}",
        "batch_inconsistent": "   -> INCONSISTENCY DETECTED in batch",
        "report_txt_gen": "Generating TXT report : {name}",
        "report_json_gen": "Generating JSON report: {name}",
        "done": "Done in {sec} s. Batch status: {status}",
        "reports_saved": "Reports saved at: {path}",
        "no_files": "error: no files found to validate.",
        "not_a_dir": "error: --dir is not a directory: {path}",
        "rep_title": "SCION - File Layout Validation",
        "rep_lang": "Report language     : {lang}",
        "rep_generated_at": "Generated at        : {when}",
        "rep_files_analyzed": "Files analyzed      : {n}",
        "rep_total_records": "Total records       : {n}",
        "rep_total_time": "Total time          : {ms} ms",
        "rep_batch_status": "Batch status        : {status}",
        "rep_snapshot": "Snapshot            : {label}",
        "rep_file": "File    : {name}",
        "rep_size": "Size    : {n} bytes",
        "rep_format": "Format  : {fmt} / {ct} (confidence: {conf})",
        "rep_reason": "Reason  : {reason}",
        "rep_records": "Records            : {n}",
        "rep_source": "source_system_name : {v}",
        "rep_run_id": "extract_run_id     : {v}",
        "rep_snapshot_date": "snapshot_date      : {v}",
        "rep_extracted_at": "extracted_at_utc   : {v}",
        "rep_parse_time": "Parse time         : {ms} ms",
        "rep_status": "Status  : {status}",
        "rep_errors": "Errors  :",
        "rep_batch_errors_section": "BATCH CONSISTENCY ERRORS:",
        "status_ok": "OK",
        "status_partial": "PARTIAL",
        "status_failed": "FAILED",
        "status_inconsistent": "INCONSISTENT",
        "status_pending": "PENDING",
        "status_layout_error": "INVALID LAYOUT",
        "status_read_error": "READ ERROR",
        "status_unsupported": "UNSUPPORTED",
        "help_dir": "Directory with .dat files",
        "help_files": "Explicit list of files",
        "help_skip_batch": "Skip cross-file batch consistency check",
        "help_lang": "Report and terminal language: pt-br (default), es, en",
        "err_unsupported_ct": (
            "Content-type not supported by validator: {ct}."
        ),
        "err_file_not_found": "File not found: {path}",
        "err_read_bytes": "Failed to read initial bytes: {err}",
        "err_unexpected": "Unexpected error ({tp}): {err}",
        "err_validate_batch_unexpected": "Unexpected error in validate_batch ({tp}): {err}",
        "err_invalid_json": "Invalid JSON: {err}",
        "err_parser_payload": "Invalid parser payload: {err}",
        "step_parser_json_load": "   -> Loading parser JSON...",
        "step_parser_validate": "   -> Validating parser payload (teradata_parser.parse)...",
        "step_parser_ok": "   -> OK: {containers} containers, {datasets} datasets, {processes} processes, {steps} steps in {ms} ms",
        "step_heuristic_detect": "   -> Detected by filename: {ct} (no official reader; heuristic validation)",
        "step_heuristic_scan": "   -> Reading file and validating consistent arity...",
        "step_heuristic_ok": "   -> OK: {n} records, {fields} fields/record, terminator={term} in {ms} ms",
        "step_heuristic_drift": "   -> INCONSISTENCY: record #{rec} has {got} fields, expected {exp}",
        "rep_parse_run_id": "parse_run_id       : {v}",
        "rep_parse_timestamp": "parse_timestamp    : {v}",
        "rep_parser_platform": "platform           : {v}",
        "rep_parser_counts": "Counts             : {v}",
        "rep_field_count": "Fields per record  : {n}",
        "rep_record_terminator": "Terminator         : {v}",
        "rep_source_system": "source_system_name : {v}",
    },
}

# Mapeia status tecnico (interno) para chave de label traduzido.
_STATUS_LABEL_KEY = {
    "ok": "status_ok",
    "partial": "status_partial",
    "failed": "status_failed",
    "inconsistent": "status_inconsistent",
    "pending": "status_pending",
    "layout_error": "status_layout_error",
    "read_error": "status_read_error",
    "unsupported": "status_unsupported",
}


class Translator:
    """Resumo: Wrapper de traducao com format-substitution segura."""

    def __init__(self, lang: str) -> None:
        self.lang = lang if lang in I18N else DEFAULT_LANG
        self._dict = I18N[self.lang]

    def t(self, key: str, **kw) -> str:
        s = self._dict.get(key, key)
        try:
            return s.format(**kw) if kw else s
        except (KeyError, IndexError):
            return s

    def status(self, status_key: str) -> str:
        label_key = _STATUS_LABEL_KEY.get(status_key, status_key)
        return self.t(label_key)


def _log(translator: Translator, key: str, **kw) -> None:
    """Resumo: Imprime mensagem amigavel traduzida com timestamp no stderr."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {translator.t(key, **kw)}", file=sys.stderr, flush=True)


def _log_raw(msg: str) -> None:
    """Resumo: Imprime linha bruta (sem traducao) no stderr — para separadores."""
    print(msg, file=sys.stderr, flush=True)


def _fmt_bytes(n: int) -> str:
    """Resumo: Formata bytes em unidade legivel (KB/MB/GB)."""
    val = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if val < 1024 or unit == "GB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024
    return f"{val:.1f} GB"


_READERS = {
    ContentType.DICT_DATABASES: r.read_databases,
    ContentType.DICT_TABLES: r.read_tables,
    ContentType.DICT_COLUMNS: r.read_columns,
    ContentType.DICT_INDICES: r.read_indices,
    ContentType.DICT_PARTITIONING: r.read_partitioning,
    ContentType.DICT_TABLETEXT: r.read_tabletext,
}


@dataclass
class FileReport:
    filename: str
    path: str
    size_bytes: int
    format: str = "unknown"
    content_type: str = "unknown"
    detection_confidence: str = ""
    detection_reason: str = ""
    record_count: int = 0
    source_system_name: Optional[str] = None
    extract_run_id: Optional[str] = None
    snapshot_date: Optional[str] = None
    extracted_at_utc: Optional[str] = None
    parse_seconds: float = 0.0
    status: str = "pending"
    errors: List[str] = field(default_factory=list)
    # Campos especificos de PARSER_LINEAGE
    parse_run_id: Optional[str] = None
    parse_timestamp: Optional[str] = None
    parser_platform: Optional[str] = None
    parser_counts: Optional[Dict[str, int]] = None
    # Campos especificos de DBQL/ObjectUsage (heuristico)
    field_count: Optional[int] = None
    record_terminator: Optional[str] = None


@dataclass
class BatchReport:
    files: List[FileReport] = field(default_factory=list)
    batch_status: str = "pending"
    batch_errors: List[str] = field(default_factory=list)
    snapshot_label: Optional[str] = None
    total_records: int = 0
    total_seconds: float = 0.0
    language: str = DEFAULT_LANG
    generated_at: str = ""


def _detect_heuristic(path: Path) -> Optional[str]:
    """Resumo: Fallback de deteccao por prefixo de nome quando o
    format_detector oficial retorna UNKNOWN. Retorna 'dbql' ou
    'object_usage' ou None."""
    name = path.name.lower()
    for prefix, ct in _HEURISTIC_FILENAME_PREFIXES.items():
        if name.startswith(prefix):
            return ct
    return None


def _looks_like_parser_lineage(head: bytes, filename: str) -> bool:
    """Resumo: Fallback de deteccao para JSON do parser quando o
    format_detector nao reconhece (chaves novas do DataDNA v2+).
    Verifica os primeiros bytes em busca de marcadores conhecidos do parser."""
    markers = (b'"parseRunId"', b'"parseTimestamp"', b'"platform"',
               b'"containers"', b'"datasets"')
    return any(m in head[:8192] for m in markers) or filename.lower().endswith(".json") and (
        "lineage" in filename.lower() or "parser" in filename.lower()
    )


def _validar_parser_lineage(path: Path, rep: FileReport, tr: Translator) -> bool:
    """Resumo: Valida arquivo PARSER_LINEAGE (JSON DataDNA) usando o
    parser oficial do SCION (teradata_parser.parse). Atualiza `rep` in-place.
    Retorna True se OK, False em caso de erro de layout."""
    _log(tr, "step_parser_json_load")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except json.JSONDecodeError as e:
        rep.status = "layout_error"
        rep.errors.append(tr.t("err_invalid_json", err=str(e)))
        _log(tr, "step_unexpected", tp="JSONDecodeError", err=str(e))
        return False
    except OSError as e:
        rep.status = "read_error"
        rep.errors.append(tr.t("err_read_bytes", err=str(e)))
        _log(tr, "step_read_error_io", err=str(e))
        return False

    _log(tr, "step_parser_validate")
    t0 = time.perf_counter()
    try:
        parsed = teradata_parser.parse(payload)
    except ParserPayloadError as e:
        rep.status = "layout_error"
        rep.errors.append(tr.t("err_parser_payload", err=str(e)))
        rep.parse_seconds = time.perf_counter() - t0
        _log(tr, "step_layout_error", ms=f"{rep.parse_seconds*1000:.0f}")
        return False
    except Exception as e:
        rep.status = "read_error"
        rep.errors.append(tr.t("err_unexpected", tp=type(e).__name__, err=str(e)))
        rep.parse_seconds = time.perf_counter() - t0
        _log(tr, "step_unexpected", tp=type(e).__name__, err=str(e))
        return False
    rep.parse_seconds = time.perf_counter() - t0

    rep.parse_run_id = parsed.parse_run_id
    rep.parse_timestamp = (
        parsed.parse_timestamp.isoformat()
        if hasattr(parsed.parse_timestamp, "isoformat")
        else str(parsed.parse_timestamp)
    )
    rep.parser_platform = parsed.platform.platform_natural_key
    rep.parser_counts = {
        "containers": len(parsed.containers),
        "datasets": len(parsed.datasets),
        "attributes": len(parsed.attributes),
        "process_groups": len(parsed.process_groups),
        "processes": len(parsed.processes),
        "steps": len(parsed.steps),
        "dataset_lineage": len(parsed.dataset_lineage),
        "attribute_lineage": len(parsed.attribute_lineage),
    }
    # `record_count` representa "elementos principais" para o relatorio agregado.
    rep.record_count = (
        rep.parser_counts["datasets"] + rep.parser_counts["attributes"]
    )
    rep.status = "ok"
    _log(tr, "step_parser_ok",
         containers=rep.parser_counts["containers"],
         datasets=rep.parser_counts["datasets"],
         processes=rep.parser_counts["processes"],
         steps=rep.parser_counts["steps"],
         ms=f"{rep.parse_seconds*1000:.0f}")
    return True


def _validar_heuristico(
    path: Path, ct_label: str, rep: FileReport, tr: Translator
) -> bool:
    """Resumo: Validacao leve para DBQL/ObjectUsage (sem reader oficial
    no SCION). Verifica delimitador `§`, arity consistente nos primeiros
    N registros, e extrai identidade (campo 0 = source_system_name).
    Atualiza `rep` in-place. Retorna True se OK."""
    _log(tr, "step_heuristic_detect", ct=ct_label)
    _log(tr, "step_heuristic_scan")
    t0 = time.perf_counter()
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        rep.status = "read_error"
        rep.errors.append(tr.t("err_read_bytes", err=str(e)))
        _log(tr, "step_read_error_io", err=str(e))
        return False

    # Resumo: Detecta o terminador efetivamente usado. Prefere ENDREC se presente.
    if _HEURISTIC_RECORD_TERMINATOR in raw:
        terminator = _HEURISTIC_RECORD_TERMINATOR
        records_raw = raw.split(_HEURISTIC_RECORD_TERMINATOR)
    else:
        terminator = "\\n"
        records_raw = raw.split("\n")
    # Resumo: Remove ultimo elemento vazio comum em split.
    records_raw = [rec for rec in records_raw if rec.strip()]

    if not records_raw:
        rep.status = "layout_error"
        rep.errors.append("Arquivo vazio ou sem registros legiveis.")
        rep.parse_seconds = time.perf_counter() - t0
        _log(tr, "step_layout_error", ms=f"{rep.parse_seconds*1000:.0f}")
        return False

    # Resumo: Conta campos no primeiro registro (delimitador `§`).
    first_fields = records_raw[0].split(_HEURISTIC_DELIMITER)
    expected_arity = len(first_fields)

    # Resumo: Valida arity consistente nos primeiros N registros (amostra).
    sample = records_raw[: min(_HEURISTIC_SAMPLE_SIZE, len(records_raw))]
    for i, rec in enumerate(sample, start=1):
        n = len(rec.split(_HEURISTIC_DELIMITER))
        if n != expected_arity:
            rep.status = "layout_error"
            rep.errors.append(
                tr.t("step_heuristic_drift", rec=i, got=n, exp=expected_arity).strip("-> ")
            )
            rep.parse_seconds = time.perf_counter() - t0
            _log(tr, "step_heuristic_drift", rec=i, got=n, exp=expected_arity)
            return False

    rep.record_count = len(records_raw)
    rep.field_count = expected_arity
    rep.record_terminator = terminator
    rep.source_system_name = first_fields[0].strip() if first_fields else None
    rep.parse_seconds = time.perf_counter() - t0
    rep.status = "ok"
    _log(tr, "step_heuristic_ok",
         n=f"{rep.record_count:,}", fields=expected_arity,
         term=terminator, ms=f"{rep.parse_seconds*1000:.0f}")
    return True


def _validar_arquivo(
    path: Path, idx: int, total: int, tr: Translator
) -> Tuple[FileReport, Optional[list]]:
    """Resumo: Detecta tipo, le e valida layout de um unico arquivo.
    Retorna (FileReport, registros_para_batch_consistency_or_None).
    Os registros so sao retornados quando o tipo for DICT_* (unico que
    participa do batch consistency check via dict_batch_validator)."""
    rep = FileReport(
        filename=path.name,
        path=str(path),
        size_bytes=path.stat().st_size if path.exists() else 0,
    )

    _log(tr, "validating_file", i=idx, total=total,
         name=path.name, size=_fmt_bytes(rep.size_bytes))

    if not path.exists() or not path.is_file():
        rep.status = "read_error"
        rep.errors.append(tr.t("err_file_not_found", path=str(path)))
        _log(tr, "step_read_error_notfound")
        return rep, None

    _log(tr, "step_detect")
    try:
        head = path.read_bytes()[:8192]
    except OSError as e:
        rep.status = "read_error"
        rep.errors.append(tr.t("err_read_bytes", err=str(e)))
        _log(tr, "step_read_error_io", err=str(e))
        return rep, None

    det = detect(head, path.name)
    rep.format = det.format.value
    rep.content_type = det.content_type.value
    rep.detection_confidence = det.confidence
    rep.detection_reason = det.reason
    _log(tr, "step_type_detected", ct=det.content_type.value, conf=det.confidence)

    # Resumo: Roteamento por content_type.
    # 1) DICT_* -> readers oficiais (mantem comportamento anterior).
    # 2) PARSER_LINEAGE -> teradata_parser.parse() (reusa codigo do SCION).
    # 3) UNKNOWN -> fallback heuristico por filename (DBQL/ObjectUsage).
    # 4) Outros UNKNOWN -> status unsupported.
    reader_fn = _READERS.get(det.content_type)
    if reader_fn is not None:
        # ──── DICT_* (reader oficial) ────
        _log(tr, "step_layout")
        t0 = time.perf_counter()
        try:
            records = reader_fn(path)
        except DictFlatFileError as e:
            rep.status = "layout_error"
            rep.errors.append(str(e))
            rep.parse_seconds = time.perf_counter() - t0
            _log(tr, "step_layout_error", ms=f"{rep.parse_seconds*1000:.0f}")
            return rep, None
        except Exception as e:
            rep.status = "read_error"
            rep.errors.append(tr.t("err_unexpected", tp=type(e).__name__, err=str(e)))
            rep.parse_seconds = time.perf_counter() - t0
            _log(tr, "step_unexpected", tp=type(e).__name__, err=str(e))
            return rep, None
        rep.parse_seconds = time.perf_counter() - t0

        rep.record_count = len(records)
        if records:
            tech = records[0].tech
            rep.source_system_name = tech.source_system_name
            rep.extract_run_id = tech.extract_run_id
            rep.snapshot_date = tech.snapshot_date
            rep.extracted_at_utc = tech.extracted_at_utc

        rep.status = "ok"
        _log(tr, "step_ok", n=f"{rep.record_count:,}", ms=f"{rep.parse_seconds*1000:.0f}")
        return rep, records

    if det.content_type == ContentType.PARSER_LINEAGE:
        # ──── PARSER_LINEAGE (reader oficial via teradata_parser) ────
        _validar_parser_lineage(path, rep, tr)
        return rep, None

    # ──── Fallback JSON: format = JSON mas content_type UNKNOWN ────
    # O format_detector procura chaves antigas ("objects"/"lineage").
    # Aqui complementamos com marcadores do parser v2+ (parseRunId, etc).
    if det.format.value == "json" and _looks_like_parser_lineage(head, path.name):
        rep.content_type = "parser_lineage"
        _validar_parser_lineage(path, rep, tr)
        return rep, None

    # ──── UNKNOWN: tenta fallback heuristico por nome de arquivo ────
    heuristic_ct = _detect_heuristic(path)
    if heuristic_ct is not None:
        rep.content_type = heuristic_ct
        _validar_heuristico(path, heuristic_ct, rep, tr)
        return rep, None

    # ──── Nao reconhecido em nenhum dos canais ────
    rep.status = "unsupported"
    rep.errors.append(tr.t("err_unsupported_ct", ct=det.content_type.value))
    _log(tr, "step_unsupported")
    return rep, None


def _coletar_arquivos(args, tr: Translator) -> Tuple[List[Path], Path]:
    """Resumo: Resolve lista final de arquivos e a pasta de saida do relatorio.
    Suporta extensoes .dat e .json. Modo recursivo via --recursive."""
    paths: List[Path] = []
    out_dir: Optional[Path] = None
    if args.dir:
        d = Path(args.dir).resolve()
        if not d.is_dir():
            print(tr.t("not_a_dir", path=str(d)), file=sys.stderr)
            sys.exit(2)
        if args.recursive:
            patterns = ("**/*.dat", "**/*.json")
        else:
            patterns = ("*.dat", "*.json")
        for pat in patterns:
            paths.extend(d.glob(pat))
        # Resumo: Filtra relatorios previos do proprio validador para nao se auto-validar.
        paths = [p for p in paths if not p.name.startswith("scion_validacao_")]
        paths = sorted(set(paths))
        out_dir = d
    if args.files:
        resolved = [Path(f).resolve() for f in args.files]
        paths.extend(resolved)
        if out_dir is None and resolved:
            out_dir = resolved[0].parent
    if out_dir is None:
        out_dir = Path.cwd()
    return paths, out_dir


def _imprimir_relatorio_txt(batch: BatchReport, tr: Translator, stream=sys.stdout) -> None:
    """Resumo: Imprime relatorio humano-legivel em texto plano traduzido."""
    print("=" * 72, file=stream)
    print(f"  {tr.t('rep_title')}", file=stream)
    print("=" * 72, file=stream)
    print(file=stream)
    print(f"  {tr.t('rep_lang', lang=batch.language)}", file=stream)
    print(f"  {tr.t('rep_generated_at', when=batch.generated_at)}", file=stream)
    print(f"  {tr.t('rep_files_analyzed', n=len(batch.files))}", file=stream)
    print(f"  {tr.t('rep_total_records', n=batch.total_records)}", file=stream)
    print(f"  {tr.t('rep_total_time', ms=f'{batch.total_seconds*1000:.1f}')}", file=stream)
    print(f"  {tr.t('rep_batch_status', status=tr.status(batch.batch_status))}", file=stream)
    if batch.snapshot_label:
        print(f"  {tr.t('rep_snapshot', label=batch.snapshot_label)}", file=stream)
    print(file=stream)

    for fr in batch.files:
        print("-" * 72, file=stream)
        print(f"  {tr.t('rep_file', name=fr.filename)}", file=stream)
        print(f"  {tr.t('rep_size', n=fr.size_bytes)}", file=stream)
        print(f"  {tr.t('rep_format', fmt=fr.format, ct=fr.content_type, conf=fr.detection_confidence)}", file=stream)
        print(f"  {tr.t('rep_reason', reason=fr.detection_reason)}", file=stream)
        if fr.status == "ok":
            # Resumo: Campos comuns (registros + tempo).
            print(f"  {tr.t('rep_records', n=fr.record_count)}", file=stream)
            # Resumo: Campos especificos por content_type.
            if fr.content_type.startswith("dict_"):
                print(f"  {tr.t('rep_source', v=fr.source_system_name)}", file=stream)
                print(f"  {tr.t('rep_run_id', v=fr.extract_run_id)}", file=stream)
                print(f"  {tr.t('rep_snapshot_date', v=fr.snapshot_date)}", file=stream)
                print(f"  {tr.t('rep_extracted_at', v=fr.extracted_at_utc)}", file=stream)
            elif fr.content_type == "parser_lineage":
                print(f"  {tr.t('rep_parse_run_id', v=fr.parse_run_id)}", file=stream)
                print(f"  {tr.t('rep_parse_timestamp', v=fr.parse_timestamp)}", file=stream)
                print(f"  {tr.t('rep_parser_platform', v=fr.parser_platform)}", file=stream)
                if fr.parser_counts:
                    counts_str = ", ".join(f"{k}={v}" for k, v in fr.parser_counts.items())
                    print(f"  {tr.t('rep_parser_counts', v=counts_str)}", file=stream)
            elif fr.content_type in (CT_DBQL, CT_OBJECT_USAGE):
                print(f"  {tr.t('rep_source_system', v=fr.source_system_name)}", file=stream)
                print(f"  {tr.t('rep_field_count', n=fr.field_count)}", file=stream)
                print(f"  {tr.t('rep_record_terminator', v=fr.record_terminator)}", file=stream)
            print(f"  {tr.t('rep_parse_time', ms=f'{fr.parse_seconds*1000:.1f}')}", file=stream)
        print(f"  {tr.t('rep_status', status=tr.status(fr.status))}", file=stream)
        if fr.errors:
            print(f"  {tr.t('rep_errors')}", file=stream)
            for err in fr.errors:
                for line in str(err).splitlines():
                    print(f"    {line}", file=stream)
        print(file=stream)

    if batch.batch_errors:
        print("-" * 72, file=stream)
        print(f"  {tr.t('rep_batch_errors_section')}", file=stream)
        for err in batch.batch_errors:
            for line in str(err).splitlines():
                print(f"    {line}", file=stream)
        print(file=stream)

    print("=" * 72, file=stream)


def main() -> int:
    # Resumo: Pre-parse rapido para descobrir --lang antes de montar mensagens.
    # Tolera --lang em qualquer posicao; default = pt-br.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang", type=str, default=DEFAULT_LANG)
    pre_args, _ = pre.parse_known_args()
    lang = pre_args.lang if pre_args.lang in SUPPORTED_LANGS else DEFAULT_LANG
    tr = Translator(lang)

    ap = argparse.ArgumentParser(description=__doc__)
    grupo = ap.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--dir", type=str, help=tr.t("help_dir"))
    grupo.add_argument("--files", nargs="+", help=tr.t("help_files"))
    ap.add_argument("--skip-batch-check", action="store_true", help=tr.t("help_skip_batch"))
    ap.add_argument("--recursive", action="store_true",
                    help="Varredura recursiva no --dir (inclui subpastas)")
    ap.add_argument("--lang", type=str, default=DEFAULT_LANG,
                    choices=list(SUPPORTED_LANGS), help=tr.t("help_lang"))
    args = ap.parse_args()

    # Resubstitui translator caso o --lang final difira (input com choices validados).
    tr = Translator(args.lang)

    paths, out_dir = _coletar_arquivos(args, tr)
    if not paths:
        print(tr.t("no_files"), file=sys.stderr)
        return 2

    _log_raw("=" * 60)
    _log(tr, "header_title")
    _log_raw("=" * 60)
    _log(tr, "files_to_validate", n=len(paths))
    _log(tr, "output_folder", path=str(out_dir))
    _log_raw("")

    batch = BatchReport(language=args.lang)
    t0_total = time.perf_counter()

    files_para_batch: List[Tuple[str, list]] = []
    for i, p in enumerate(paths, start=1):
        rep, records = _validar_arquivo(p, i, len(paths), tr)
        batch.files.append(rep)
        if rep.status == "ok":
            batch.total_records += rep.record_count
            # Resumo: Apenas DICT_* participam do batch consistency check do SCION.
            if records is not None:
                files_para_batch.append((p.name, records))

    if not args.skip_batch_check and files_para_batch:
        _log_raw("")
        _log(tr, "batch_check")
        try:
            identity = validate_batch(files_para_batch)
            batch.snapshot_label = identity.snapshot_label
            _log(tr, "batch_ok", label=identity.snapshot_label)
        except BatchConsistencyError as e:
            batch.batch_errors.append(str(e))
            _log(tr, "batch_inconsistent")
        except Exception as e:
            batch.batch_errors.append(
                tr.t("err_validate_batch_unexpected", tp=type(e).__name__, err=str(e))
            )
            _log(tr, "step_unexpected", tp=type(e).__name__, err=str(e))

    batch.total_seconds = time.perf_counter() - t0_total
    batch.generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    has_file_errors = any(f.status != "ok" for f in batch.files)
    has_batch_errors = bool(batch.batch_errors)
    if not has_file_errors and not has_batch_errors:
        batch.batch_status = "ok"
    elif has_batch_errors and not has_file_errors:
        batch.batch_status = "inconsistent"
    elif has_file_errors and any(f.status == "ok" for f in batch.files):
        batch.batch_status = "partial"
    else:
        batch.batch_status = "failed"

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = out_dir / f"scion_validacao_{stamp}.txt"
    json_path = out_dir / f"scion_validacao_{stamp}.json"

    _log_raw("")
    _log(tr, "report_txt_gen", name=txt_path.name)
    with open(txt_path, "w", encoding="utf-8") as fh:
        _imprimir_relatorio_txt(batch, tr, stream=fh)

    _log(tr, "report_json_gen", name=json_path.name)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(asdict(batch), fh, ensure_ascii=False, indent=2)

    _log_raw("")
    _log(tr, "done", sec=f"{batch.total_seconds:.1f}", status=tr.status(batch.batch_status))
    _log(tr, "reports_saved", path=str(out_dir))

    _imprimir_relatorio_txt(batch, tr)

    return 0 if batch.batch_status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())

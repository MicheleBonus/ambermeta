# AmberMeta Improvement Plan

**Date**: 2026-01-27
**Status**: Substantially Completed
**Version**: 2.1

## Executive Summary

This document outlines the improvements for the ambermeta package. The majority of planned features have been implemented, including all bug fixes, UX enhancements, and core data submission improvements. Remaining items are low-priority future enhancements.

---

## Completed Items

### Bug Fixes (All Complete)
- [x] BUG-001: Bare except with silent failure - Fixed in mdout.py
- [x] BUG-002: Box consistency false positives - Fixed in protocol.py
- [x] BUG-003: Inconsistent atom count attribute naming - Added `n_atoms` property to all metadata classes
- [x] BUG-004: Zero values incorrectly pruned - Fixed using explicit `len() == 0` check
- [x] BUG-005: Missing cross-stage continuity check - Added INFO note when check is skipped
- [x] BUG-006: Broad exception handling - Replaced with specific exception types
- [x] BUG-007: Missing NaN/Inf handling - Added filtering in utils.py and mdin.py
- [x] BUG-008: Unbounded statistics lists - Implemented Welford's online algorithm
- [x] BUG-009: Missing circular reference detection - Added visited set to serialization
- [x] BUG-010: Undocumented stage_role inference - Added validation note when inference occurs

### UX Improvements (All Complete)
- [x] UX-001: Structured Logging System - Created logging_config.py with level control
- [x] UX-002: Enhanced Error Messages - Improved error context in all parsers
- [x] UX-003: Progress Indicators - Added ProgressIndicator class
- [x] UX-004: Color-Coded Validation Output - Added Colors class with ANSI codes
- [x] UX-005: New CLI Subcommands - Added `validate`, `info`, `init` commands
- [x] UX-006: Interactive Mode Improvements - Enhanced prompts, file suggestions, stage role inference
- [x] UX-007: Export Format Options - Added CSV export for statistics
- [x] UX-008: Enhanced Help System - Added examples to CLI help, epilog with usage
- [x] UX-009: Example Manifest Generator - Added `init` command with templates

### Data Submission Improvements (Newly Completed)

#### DS-001: Additional Manifest Formats (COMPLETE)
- [x] Support TOML format for manifests (requires tomllib/tomli)
- [x] Support CSV format for simple workflows
- [x] Auto-detect format based on file extension

#### DS-002: Environment Variable Expansion (COMPLETE)
- [x] Allow `${VAR}` and `$VAR` syntax in manifest file paths
- [x] Useful for portable manifests across systems
- [x] Can be disabled via `--no-expand-env` CLI flag or `expand_env=False` API parameter

#### DS-004: Smart Pattern-Based Grouping (COMPLETE)
- [x] Auto-detect numeric sequences (prod_001, prod_002, etc.)
- [x] Regex pattern matching for file organization (`--pattern` CLI flag)
- [x] Stage type inference from file content
- [x] New `detect_numeric_sequences()` and `smart_group_files()` functions

#### DS-005: Restart Chain Auto-Detection (COMPLETE)
- [x] Automatically link restart files based on atom count and timestamps
- [x] Build dependency graph for stages using naming conventions
- [x] Auto-validate continuity
- [x] New `auto_detect_restart_chain()` function and `--auto-detect-restarts` CLI flag

#### DS-010: Per-Stage Tolerances (COMPLETE)
- [x] Fine-grained gap tolerance control per stage
- [x] Available via `ProtocolBuilder.with_stage_tolerance()` method
- [x] Expected gap specification per stage in manifests

#### DS-011: Builder Pattern API (COMPLETE)
- [x] Fluent `ProtocolBuilder` class for protocol construction
- [x] Method chaining for stage configuration
- [x] Built-in validation with configurable options

### Documentation Improvements (Newly Completed)

#### DOC-001: Comprehensive Documentation (COMPLETE)
- [x] Updated README.md with tutorials and comprehensive overview
- [x] Created docs/tutorials.md with step-by-step guides for metadata extraction
- [x] Created docs/tui.md with complete TUI documentation
- [x] Created docs/cli.md with CLI reference documentation
- [x] Created docs/api.md with Python API reference
- [x] Updated docs/manifest.md with TUI integration reference

---

## Remaining Items (Future Enhancements)

### Low Priority Data Submission Improvements

#### DS-003: Inline File Content (LOW)
- Embed small mdin files directly in manifest
- Useful for simple one-file protocols

#### DS-006: Multi-Run Support (LOW)
- Handle REMD replica numbering
- Group replicas into single protocol
- Validate replica consistency

#### DS-007: Remote File Support (LOW)
- HTTP/HTTPS file download with caching
- S3/GCS/Azure blob storage support (optional)
- Resume interrupted downloads

#### DS-008: Batch Processing (MEDIUM)
- Parallel parsing with multiprocessing
- Batch validation reports
- Directory watching for continuous processing

#### DS-009: Custom Validation Rules (LOW)
- User-defined validation logic in YAML
- Per-rule severity levels
- Custom error messages

### API Improvements

#### DS-012: Async Parsing Support (LOW)
- Async/await for parallel file operations
- Better performance for large batches

#### DS-013: Lazy Parsing (LOW)
- Generator-based parsers for large files
- Memory-efficient streaming

### Output Enhancements

#### DS-014: Rich Output Formats (MEDIUM)
- HTML reports with interactive charts
- PDF publication-ready summaries
- Jupyter Notebook templates
- DataCite JSON for repositories

---

## New Files Created

- `ambermeta/logging_config.py` - Structured logging configuration
- `docs/tutorials.md` - Comprehensive step-by-step tutorials
- `docs/tui.md` - Terminal User Interface documentation
- `docs/cli.md` - Command Line Interface reference
- `docs/api.md` - Python API reference

## Files Modified (This Release)

- `ambermeta/protocol.py` - Added TOML/CSV support, env var expansion, smart grouping, restart chain detection, builder API
- `ambermeta/__init__.py` - Export new symbols
- `ambermeta/cli.py` - New CLI flags for data submission features
- `README.md` - Comprehensive rewrite with tutorials and documentation links
- `docs/manifest.md` - Added TUI integration reference

## Files Modified (Previous Release)

- `ambermeta/cli.py` - New subcommands, colors, progress indicators, CSV export
- `ambermeta/protocol.py` - Bug fixes, circular reference detection, continuity notes
- `ambermeta/utils.py` - NaN/Inf handling
- `ambermeta/legacy_extractors/mdout.py` - Streaming statistics, specific exceptions
- `ambermeta/legacy_extractors/mdin.py` - NaN/Inf handling, specific exceptions
- `ambermeta/legacy_extractors/inpcrd.py` - n_atoms property, specific exceptions
- `ambermeta/legacy_extractors/mdcrd.py` - Specific exceptions
- `ambermeta/legacy_extractors/prmtop.py` - n_atoms property, specific exceptions

---

## Notes

All major data submission improvements have been implemented. The remaining items are optional enhancements that can be added in future releases based on user feedback and priorities.

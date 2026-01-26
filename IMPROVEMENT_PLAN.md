# AmberMeta Improvement Plan

**Date**: 2026-01-26
**Status**: Partially Completed
**Version**: 1.1

## Executive Summary

This document outlines remaining improvements for the ambermeta package. Bug fixes and core UX enhancements have been completed. The remaining items focus on advanced data submission workflows, enterprise features, and optional enhancements.

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

---

## Remaining Items (Future Enhancements)

### Data Submission Improvements

#### DS-001: Additional Manifest Formats (MEDIUM)
- Support TOML format for manifests
- Support CSV format for simple workflows
- Auto-detect format based on file extension

#### DS-002: Environment Variable Expansion (MEDIUM)
- Allow `${VAR}` syntax in manifest file paths
- Useful for portable manifests across systems

#### DS-003: Inline File Content (LOW)
- Embed small mdin files directly in manifest
- Useful for simple one-file protocols

#### DS-004: Smart Pattern-Based Grouping (HIGH)
- Auto-detect numeric sequences (prod_001, prod_002, etc.)
- Regex pattern matching for file organization
- Stage type inference from file content

#### DS-005: Restart Chain Auto-Detection (HIGH)
- Automatically link restart files based on atom count and timestamps
- Build dependency graph for stages
- Auto-validate continuity

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

#### DS-010: Per-Stage Tolerances (MEDIUM)
- Fine-grained gap tolerance control
- Skip continuity check for specific stages
- Expected gap specification per stage

### API Improvements

#### DS-011: Builder Pattern API (MEDIUM)
- Fluent API for protocol construction
- Method chaining for stage configuration
- Built-in validation

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

## Implementation Priority

### Next Phase (Recommended)
1. DS-004: Smart Pattern-Based Grouping
2. DS-005: Restart Chain Auto-Detection
3. DS-010: Per-Stage Tolerances
4. DS-011: Builder Pattern API

### Future Phases
- DS-008: Batch Processing
- DS-014: Rich Output Formats
- DS-001: Additional Manifest Formats
- Remaining low-priority items

---

## New Files Created

- `ambermeta/logging_config.py` - Structured logging configuration

## Files Modified

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

All bug fixes and core UX improvements have been implemented. The remaining data submission improvements are optional enhancements that can be added in future releases based on user feedback and priorities.

# AmberMeta Improvement Plan

**Date**: 2026-01-26
**Status**: Planning Phase
**Version**: 1.0

## Executive Summary

This document outlines a comprehensive plan to improve the ambermeta package through bug fixes, user experience enhancements, and data submission workflow improvements. The plan is organized by priority and impact, with specific implementation steps for each item.

---

## Table of Contents

1. [Bug Fixes](#bug-fixes)
2. [User Experience Enhancements](#user-experience-enhancements)
3. [Data Submission Improvements](#data-submission-improvements)
4. [Implementation Phases](#implementation-phases)
5. [Testing Strategy](#testing-strategy)
6. [Breaking Changes](#breaking-changes)

---

## Bug Fixes

### High Priority (Must Fix)

#### BUG-001: Bare except with silent failure
- **File**: `ambermeta/legacy_extractors/mdout.py:281`
- **Severity**: HIGH
- **Description**: `except: pass` silently swallows parsing errors when extracting wall time
- **Impact**: Invalid data leads to missing metadata without user notification
- **Fix**:
  ```python
  # Current (line 281):
  except: pass

  # Fixed:
  except (ValueError, IndexError) as e:
      md.warnings.append(f"Failed to parse wall time: {e}")
  ```
- **Test**: Add test case with malformed wall time output
- **Estimated effort**: 30 minutes

#### BUG-002: Box consistency false positives
- **File**: `ambermeta/protocol.py:148-149`
- **Severity**: HIGH
- **Description**: Warns "only X reports box information" even when only one file is expected to have box data
- **Impact**: Confusing validation warnings for legitimate simulation setups
- **Fix**:
  ```python
  # Current logic (lines 148-149):
  if boxes and len(boxes) < 2:
      return [f"Only {boxes[0]} reports box information; check consistency."]

  # Fixed logic:
  if len(boxes) >= 2:
      # Only validate if multiple sources exist
      box_values = [get_box_from_source(src) for src in boxes]
      if not all_boxes_match(box_values):
          return [f"Box dimensions inconsistent across {', '.join(boxes)}"]
  return []
  ```
- **Test**: Add test with single box source (should not warn)
- **Estimated effort**: 1 hour

#### BUG-003: Inconsistent atom count attribute naming
- **Files**: Throughout codebase
- **Severity**: HIGH
- **Description**: prmtop uses `natom`, others use `natoms` or `n_atoms`
- **Impact**: Complex validation logic, easier to miss edge cases
- **Fix**:
  1. Add `@property` methods to all metadata classes for standardized access
  2. Deprecate old attribute names with warnings
  3. Update validation logic to use standardized `n_atoms` property
- **Migration path**: Keep old names for backwards compatibility, add deprecation warnings
- **Test**: Update all tests to use new standardized names
- **Estimated effort**: 3 hours

### Medium Priority (Should Fix)

#### BUG-004: Zero values incorrectly pruned
- **File**: `ambermeta/protocol.py:65`
- **Severity**: MEDIUM
- **Description**: Falsy check `if isinstance(cleaned, (dict, list)) and not cleaned:` treats 0 as falsy
- **Impact**: Legitimate zero values removed from to_methods_dict() output
- **Fix**:
  ```python
  # Current (line 65):
  if isinstance(cleaned, (dict, list)) and not cleaned:
      continue

  # Fixed:
  if cleaned is None:
      continue
  if isinstance(cleaned, (dict, list)) and len(cleaned) == 0:
      continue
  ```
- **Test**: Add test with restraint weight = 0.0 and verify it's preserved
- **Estimated effort**: 30 minutes

#### BUG-005: Missing cross-stage continuity check
- **File**: `ambermeta/protocol.py:301-311`
- **Severity**: MEDIUM
- **Description**: Cross-stage timing validation silently skipped if trajectory file missing
- **Impact**: Undetected protocol gaps
- **Fix**: Add informational note when check is skipped
  ```python
  if not prev_mdcrd or not curr_inpcrd:
      notes.append(f"INFO: Cannot verify continuity between {prev.name} and {curr.name} "
                   f"(missing {'mdcrd' if not prev_mdcrd else 'inpcrd'})")
      return notes
  ```
- **Test**: Add test with missing trajectory file
- **Estimated effort**: 45 minutes

#### BUG-006: Broad exception handling
- **Files**: mdcrd.py:131,251; inpcrd.py:216,311; mdin.py:857; mdout.py:439; prmtop.py:516
- **Severity**: MEDIUM
- **Description**: `except Exception:` catches all errors including programming bugs
- **Impact**: Silent failures, difficult debugging
- **Fix**: Replace with specific exception types
  - File I/O errors: `IOError`, `OSError`, `FileNotFoundError`
  - Parsing errors: `ValueError`, `KeyError`, `IndexError`
  - Format errors: `struct.error` (for NetCDF)
- **Test**: Add tests with various error conditions
- **Estimated effort**: 2 hours

#### BUG-007: Missing NaN/Inf handling
- **File**: `ambermeta/utils.py:62`
- **Severity**: MEDIUM
- **Description**: Fortran D-notation conversion doesn't handle edge cases
- **Impact**: May produce invalid float values
- **Fix**:
  ```python
  def _as_float(val: str) -> Optional[float]:
      try:
          result = float(val.replace("d", "e").replace("D", "E"))
          if math.isnan(result) or math.isinf(result):
              return None
          return result
      except (ValueError, TypeError):
          return None
  ```
- **Test**: Add tests with NaN, Inf, -Inf strings
- **Estimated effort**: 30 minutes

### Low Priority (Nice to Have)

#### BUG-008: Unbounded statistics lists
- **Files**: mdout.py, mdcrd.py
- **Severity**: LOW
- **Description**: Memory usage scales linearly with frame count
- **Impact**: High memory usage for large trajectories
- **Fix**: Use Welford's online algorithm for streaming statistics
- **Estimated effort**: 2 hours

#### BUG-009: Missing circular reference detection
- **File**: `ambermeta/protocol.py:33-39`
- **Severity**: LOW
- **Description**: Serialization doesn't detect cycles
- **Impact**: Potential infinite loops if data structures have cycles
- **Fix**: Add visited set to _serialize_value()
- **Estimated effort**: 1 hour

#### BUG-010: Undocumented stage_role inference
- **File**: `ambermeta/protocol.py:753`
- **Severity**: LOW
- **Description**: Users don't know when role is automatically inferred
- **Impact**: User confusion
- **Fix**: Add logging when inference occurs
- **Estimated effort**: 15 minutes

---

## User Experience Enhancements

### Phase 1: Core UX Improvements

#### UX-001: Structured Logging System
- **Priority**: HIGH
- **Description**: Replace print statements with proper logging
- **Implementation**:
  1. Add `logging` configuration with level control
  2. Replace all `print()` with appropriate log levels
  3. Add `--log-level` CLI flag
  4. Add `--log-file` option for file output
- **Benefits**: Better debugging, cleaner output, production-ready
- **Estimated effort**: 3 hours

#### UX-002: Enhanced Error Messages
- **Priority**: HIGH
- **Description**: Make errors actionable and informative
- **Implementation**:
  1. Create error message templates with suggestions
  2. Include file path, line number, and context in all parsing errors
  3. Add "Did you mean?" suggestions for common mistakes
  4. Add error codes for documentation reference
- **Example**:
  ```
  [ERROR-001] Failed to parse mdout file
  File: /path/to/file.mdout, Line: 142
  Reason: Expected energy table but found "FINAL RESULTS"
  Suggestion: File may be truncated or incomplete. Check if simulation finished properly.
  See: https://ambermeta.readthedocs.io/errors/001
  ```
- **Estimated effort**: 4 hours

#### UX-003: Progress Indicators
- **Priority**: MEDIUM
- **Description**: Show progress for long-running operations
- **Implementation**:
  1. Add `tqdm` as optional dependency
  2. Show progress bar for auto-discovery
  3. Show file-by-file parsing progress
  4. Add `--quiet` flag to suppress progress output
- **Estimated effort**: 2 hours

#### UX-004: Color-Coded Validation Output
- **Priority**: MEDIUM
- **Description**: Visual severity indicators
- **Implementation**:
  1. Add `colorama` as optional dependency
  2. Red for errors, yellow for warnings, blue for info
  3. Add `--no-color` flag for CI/CD environments
- **Estimated effort**: 1 hour

### Phase 2: CLI Feature Additions

#### UX-005: New Subcommands
- **Priority**: MEDIUM
- **Description**: Add specialized commands for common tasks
- **New commands**:
  - `ambermeta validate` - Validation-only mode with detailed report
  - `ambermeta discover` - File discovery with dry-run option
  - `ambermeta init` - Create template manifest
  - `ambermeta diff` - Compare two protocols
  - `ambermeta convert` - Convert between manifest formats
- **Estimated effort**: 6 hours (1 hour per command)

#### UX-006: Interactive Mode Improvements
- **Priority**: LOW
- **Description**: Better interactive manifest creation
- **Features**:
  1. Tab completion for file paths (using `readline`)
  2. Show auto-discovered files with confirmation
  3. Allow editing previous stages before finalizing
  4. Save draft manifests and resume later
- **Estimated effort**: 4 hours

#### UX-007: Export Format Options
- **Priority**: LOW
- **Description**: Multiple output formats for different use cases
- **Formats**:
  - CSV tables for spreadsheet import
  - Markdown tables for documentation
  - HTML reports with interactive elements
  - LaTeX tables for publications
- **Estimated effort**: 5 hours

### Phase 3: Documentation and Help

#### UX-008: Enhanced Help System
- **Priority**: MEDIUM
- **Description**: Better in-CLI documentation
- **Features**:
  1. Add examples to `--help` output
  2. Create `ambermeta quickstart` wizard
  3. Add `--explain` flag for validation notes
  4. Interactive help: `ambermeta help <topic>`
- **Estimated effort**: 3 hours

#### UX-009: Example Manifest Generator
- **Priority**: LOW
- **Description**: Generate example manifests from existing files
- **Usage**: `ambermeta init --from-existing /path/to/amber_runs`
- **Estimated effort**: 2 hours

---

## Data Submission Improvements

### Phase 1: Manifest Format Enhancements

#### DS-001: Additional Manifest Formats
- **Priority**: MEDIUM
- **Description**: Support more user-friendly formats
- **Formats**:
  1. **TOML**: More readable than YAML
  2. **CSV**: Simple table format for basic workflows
  3. **INI**: Classic configuration format
- **Implementation**:
  - Add format auto-detection based on extension
  - Create parser/serializer for each format
  - Update documentation with examples
- **Estimated effort**: 4 hours

#### DS-002: Environment Variable Expansion
- **Priority**: MEDIUM
- **Description**: Allow dynamic paths in manifests
- **Example**:
  ```yaml
  - name: prod
    files:
      prmtop: ${DATA_DIR}/system.prmtop
      mdin: ${RUN_DIR}/input.mdin
  ```
- **Implementation**: Add `os.path.expandvars()` to path resolution
- **Estimated effort**: 1 hour

#### DS-003: Inline File Content
- **Priority**: LOW
- **Description**: Embed small files directly in manifest
- **Example**:
  ```yaml
  - name: equil
    files:
      mdin: |
        &cntrl
          imin=0, nstlim=50000,
          dt=0.002
        /
  ```
- **Estimated effort**: 2 hours

### Phase 2: Auto-Discovery Improvements

#### DS-004: Smart Pattern-Based Grouping
- **Priority**: HIGH
- **Description**: Better automatic file organization
- **Features**:
  1. Regex pattern detection for common naming schemes
  2. Numeric sequence detection (e.g., `prod_001`, `prod_002`)
  3. Stage type inference from file content
- **Implementation**:
  ```python
  # Auto-detect patterns like: min_01.out, equil_02.out, prod_03.out
  auto_discover(path, auto_group=True)
  ```
- **Estimated effort**: 4 hours

#### DS-005: Restart Chain Auto-Detection
- **Priority**: HIGH
- **Description**: Automatically link restart files
- **Logic**:
  1. Match by atom count and timestamp
  2. Build dependency graph
  3. Validate continuity automatically
- **Estimated effort**: 3 hours

#### DS-006: Multi-Run Support
- **Priority**: LOW
- **Description**: Handle replica exchange and ensemble runs
- **Features**:
  1. Detect REMD replica numbering
  2. Group replicas into single protocol
  3. Validate replica consistency
- **Estimated effort**: 5 hours

### Phase 3: Remote and Cloud Support

#### DS-007: Remote File Support
- **Priority**: LOW
- **Description**: Download files from URLs
- **Features**:
  1. HTTP/HTTPS support with caching
  2. S3/GCS/Azure blob storage support (optional)
  3. Local cache management
  4. Resume interrupted downloads
- **Dependencies**: `requests`, `boto3` (optional)
- **Estimated effort**: 6 hours

#### DS-008: Batch Processing
- **Priority**: MEDIUM
- **Description**: Process multiple protocols efficiently
- **Features**:
  1. Parallel parsing with multiprocessing
  2. Batch validation reports
  3. Directory watching for continuous processing
- **Implementation**: `ambermeta batch process /path/to/protocols/*.yaml`
- **Estimated effort**: 4 hours

### Phase 4: Validation Customization

#### DS-009: Custom Validation Rules
- **Priority**: LOW
- **Description**: User-defined validation logic
- **Configuration**:
  ```yaml
  validation:
    rules:
      - name: "minimum_production_time"
        condition: "stage_role == 'production'"
        check: "time_ps >= 100000"
        severity: "warning"
        message: "Production runs should be at least 100 ns"
  ```
- **Estimated effort**: 5 hours

#### DS-010: Per-Stage Tolerances
- **Priority**: MEDIUM
- **Description**: Fine-grained tolerance control
- **Example**:
  ```yaml
  - name: equil
    gaps:
      expected_ps: 0.0
      tolerance_ps: 1.0
      check_continuity: false  # Skip for this stage
  ```
- **Estimated effort**: 2 hours

### Phase 5: API Improvements

#### DS-011: Builder Pattern API
- **Priority**: MEDIUM
- **Description**: Fluent API for protocol construction
- **Example**:
  ```python
  from ambermeta import ProtocolBuilder

  protocol = (ProtocolBuilder()
      .add_stage("min")
          .with_role("minimization")
          .with_prmtop("system.prmtop")
          .with_mdin("min.in")
          .with_mdout("min.out")
      .add_stage("prod")
          .with_role("production")
          .with_mdin("prod.in")
          .with_mdout("prod.out")
      .validate()
      .build())
  ```
- **Estimated effort**: 4 hours

#### DS-012: Async Parsing Support
- **Priority**: LOW
- **Description**: Async/await for parallel operations
- **Benefits**: Better performance for large batches
- **Estimated effort**: 6 hours

#### DS-013: Lazy Parsing
- **Priority**: LOW
- **Description**: Memory-efficient streaming for large files
- **Implementation**: Generator-based parsers
- **Estimated effort**: 5 hours

### Phase 6: Output Enhancements

#### DS-014: Rich Output Formats
- **Priority**: MEDIUM
- **Description**: Publication-ready reports
- **Formats**:
  1. **HTML**: Interactive reports with charts (using Plotly/Chart.js)
  2. **PDF**: Publication-ready summaries (using ReportLab)
  3. **Jupyter Notebook**: Analysis templates
  4. **DataCite JSON**: Repository metadata
- **Estimated effort**: 8 hours (2 hours per format)

---

## Implementation Phases

### Phase 1: Critical Bug Fixes (Week 1)
**Goal**: Fix high-priority bugs that affect data integrity

- [ ] BUG-001: Bare except with silent failure
- [ ] BUG-002: Box consistency false positives
- [ ] BUG-003: Inconsistent atom count naming
- [ ] BUG-004: Zero values pruned
- [ ] BUG-005: Missing continuity check
- [ ] Add regression tests for all fixes
- [ ] Update documentation

**Deliverable**: Version 0.1.1 with critical bug fixes

### Phase 2: Medium-Priority Bugs + Core UX (Week 2)
**Goal**: Improve reliability and basic user experience

- [ ] BUG-006: Broad exception handling
- [ ] BUG-007: NaN/Inf handling
- [ ] UX-001: Structured logging
- [ ] UX-002: Enhanced error messages
- [ ] UX-003: Progress indicators
- [ ] UX-008: Enhanced help system

**Deliverable**: Version 0.2.0 with improved UX

### Phase 3: Data Submission Core Features (Week 3-4)
**Goal**: Make data submission easier and more flexible

- [ ] DS-001: Additional manifest formats (TOML)
- [ ] DS-002: Environment variable expansion
- [ ] DS-004: Smart pattern-based grouping
- [ ] DS-005: Restart chain auto-detection
- [ ] DS-010: Per-stage tolerances
- [ ] UX-005: New CLI subcommands

**Deliverable**: Version 0.3.0 with enhanced data submission

### Phase 4: Advanced Features (Week 5-6)
**Goal**: Add power-user features and advanced workflows

- [ ] DS-008: Batch processing
- [ ] DS-011: Builder pattern API
- [ ] DS-014: Rich output formats (HTML, PDF)
- [ ] UX-006: Interactive mode improvements
- [ ] UX-007: Export format options
- [ ] BUG-008: Streaming statistics

**Deliverable**: Version 0.4.0 with advanced features

### Phase 5: Cloud and Enterprise (Week 7-8)
**Goal**: Support enterprise workflows and cloud deployments

- [ ] DS-007: Remote file support
- [ ] DS-009: Custom validation rules
- [ ] DS-012: Async parsing
- [ ] DS-013: Lazy parsing
- [ ] BUG-009: Circular reference detection

**Deliverable**: Version 1.0.0 production-ready release

---

## Testing Strategy

### Unit Tests
- Add tests for every bug fix before implementing
- Maintain >90% code coverage
- Test edge cases (empty files, malformed data, missing files)

### Integration Tests
- Test full workflows with real AMBER data
- Test all manifest formats
- Test error handling paths

### Performance Tests
- Benchmark parsing speed for large files
- Memory profiling for trajectory processing
- Regression tests to detect slowdowns

### User Acceptance Tests
- Test CLI usability with real users
- Collect feedback on error messages
- Validate documentation clarity

---

## Breaking Changes

### Version 0.2.0
- Standardized `n_atoms` attribute (deprecated `natom`, `natoms`)
- Changed box validation logic (fewer false positives)

### Version 0.3.0
- Changed `to_methods_dict()` behavior (preserves zero values)

### Version 1.0.0
- Removed deprecated attribute names
- Changed default validation strictness
- Updated manifest schema version

---

## Migration Guide

### From 0.1.x to 0.2.x
```python
# Old code
natom = stage.prmtop.details.natom

# New code (both work, old triggers deprecation warning)
n_atoms = stage.prmtop.details.n_atoms
natom = stage.prmtop.details.natom  # Still works, shows warning
```

### From 0.2.x to 1.0.0
```python
# Must update to new attribute names
n_atoms = stage.prmtop.details.n_atoms  # Only this works
```

---

## Success Metrics

### Bug Fixes
- Zero silent failures in production use
- <5% false positive validation warnings
- All critical bugs resolved within 1 month

### User Experience
- 50% reduction in user-reported confusion
- 80% of users successfully create manifests on first try
- Average task completion time reduced by 30%

### Data Submission
- Support 3+ manifest formats
- 90% of common workflows require zero manual configuration
- Processing speed improved 2x for batch operations

---

## Next Steps

1. **Review and prioritize**: Get stakeholder feedback on priorities
2. **Create GitHub issues**: One issue per bug/feature
3. **Set up project board**: Track progress through implementation
4. **Begin Phase 1**: Start with critical bug fixes
5. **Iterate**: Collect user feedback and adjust plan

---

## Appendix: File Locations Summary

### Files requiring changes:

**Bug fixes:**
- `ambermeta/legacy_extractors/mdout.py` (BUG-001, BUG-007)
- `ambermeta/protocol.py` (BUG-002, BUG-003, BUG-004, BUG-005, BUG-009)
- `ambermeta/legacy_extractors/mdcrd.py` (BUG-006, BUG-008)
- `ambermeta/legacy_extractors/inpcrd.py` (BUG-006)
- `ambermeta/legacy_extractors/mdin.py` (BUG-006)
- `ambermeta/legacy_extractors/prmtop.py` (BUG-006)
- `ambermeta/utils.py` (BUG-007)

**New files needed:**
- `ambermeta/logging_config.py` (UX-001)
- `ambermeta/formats/toml_format.py` (DS-001)
- `ambermeta/formats/csv_format.py` (DS-001)
- `ambermeta/builders.py` (DS-011)
- `ambermeta/validators/custom_rules.py` (DS-009)
- `ambermeta/exporters/html_exporter.py` (DS-014)
- `ambermeta/exporters/pdf_exporter.py` (DS-014)

**Documentation updates:**
- `README.md` - All features
- `docs/manifest.md` - New formats and features
- `docs/errors.md` - New error codes and messages (create)
- `docs/migration.md` - Breaking changes guide (create)
- `docs/api.md` - New API patterns (create)

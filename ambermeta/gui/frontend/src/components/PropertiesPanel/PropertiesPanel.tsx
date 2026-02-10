import { useState, useEffect, useMemo, useRef } from 'react';
import type { StageRole, StageFiles } from '../../types';
import { useProtocolStore } from '../../stores/protocolStore';
import { FileIcon, X, Check, AlertTriangle } from '../common/Icons';
import { STAGE_ROLE_CONFIG } from '../../types';

const STAGE_ROLES: StageRole[] = ['', 'minimization', 'heating', 'equilibration', 'production'];

interface FileFieldProps {
  label: string;
  fileType: keyof StageFiles;
  value?: string;
  onChange: (value: string | undefined) => void;
  globalValue?: string;
}

function FileField({ label, fileType, value, onChange, globalValue }: FileFieldProps) {
  const isUsingGlobal = !value && globalValue;
  const displayValue = value || globalValue || '';

  return (
    <div className="mb-3">
      <label className="block text-sm font-medium text-gray-700 mb-1 flex items-center gap-2">
        <FileIcon type={fileType} className="w-4 h-4" />
        {label}
        {isUsingGlobal && (
          <span className="text-xs text-blue-500 font-normal">(using global)</span>
        )}
      </label>
      <div className="relative">
        <input
          type="text"
          value={displayValue}
          onChange={(e) => onChange(e.target.value || undefined)}
          placeholder={`Path to ${fileType} file`}
          className={`
            w-full px-3 py-2 pr-8 text-sm font-mono border rounded-lg
            focus:outline-none focus:ring-2 focus:ring-blue-500
            ${isUsingGlobal ? 'border-blue-200 bg-blue-50' : 'border-gray-300'}
          `}
        />
        {value && (
          <button
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 hover:bg-gray-100 rounded"
            onClick={() => onChange(undefined)}
          >
            <X className="w-4 h-4 text-gray-400" />
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * Multi-stage bulk edit panel: shown when multiple stages are selected.
 * Changes apply immediately to all selected stages via the bulk update API.
 */
function BulkEditPanel() {
  const {
    stages,
    selectedStageIds,
    settings,
    bulkUpdateStages,
    clearSelection,
  } = useProtocolStore();

  const selectedStages = useMemo(
    () => stages.filter(s => selectedStageIds.includes(s.id)),
    [stages, selectedStageIds]
  );

  const handleBulkRoleChange = async (role: StageRole) => {
    await bulkUpdateStages(selectedStageIds, { role });
  };

  const handleBulkPrmtopChange = async (prmtopPath: string | undefined) => {
    await bulkUpdateStages(selectedStageIds, {
      files: { prmtop: prmtopPath || '' },
    });
  };

  const handleBulkGapChange = async (field: 'expected_gap_ps' | 'gap_tolerance_ps', value: string) => {
    const numVal = value ? parseFloat(value) : undefined;
    await bulkUpdateStages(selectedStageIds, { [field]: numVal });
  };

  // Collect available prmtops for dropdown
  const availablePrmtops: { label: string; value: string }[] = [];
  if (settings.global_prmtop) {
    availablePrmtops.push({
      label: `Normal: ${settings.global_prmtop.split('/').pop()}`,
      value: settings.global_prmtop,
    });
  }
  if (settings.hmr_prmtop) {
    availablePrmtops.push({
      label: `HMR: ${settings.hmr_prmtop.split('/').pop()}`,
      value: settings.hmr_prmtop,
    });
  }

  // Determine common values across selected stages
  const commonRole = selectedStages.every(s => s.role === selectedStages[0]?.role)
    ? selectedStages[0]?.role
    : undefined;

  return (
    <div className="h-full flex flex-col bg-white border-l border-gray-200">
      <div className="p-4 border-b border-gray-200">
        <h2 className="font-semibold text-gray-800 flex items-center gap-2">
          Bulk Edit
          <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-indigo-100 text-indigo-700">
            {selectedStageIds.length} stages
          </span>
        </h2>
        <p className="text-xs text-gray-500 mt-1">
          Changes apply immediately to all selected stages
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {/* Role */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Role
          </label>
          <select
            value={commonRole ?? '__mixed__'}
            onChange={(e) => {
              if (e.target.value !== '__mixed__') {
                handleBulkRoleChange(e.target.value as StageRole);
              }
            }}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {commonRole === undefined && (
              <option value="__mixed__" disabled>(mixed)</option>
            )}
            {STAGE_ROLES.map((role) => (
              <option key={role} value={role}>
                {STAGE_ROLE_CONFIG[role].label}
              </option>
            ))}
          </select>
        </div>

        {/* Prmtop selection */}
        {availablePrmtops.length > 0 && (
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Topology (prmtop)
            </label>
            <div className="space-y-2">
              <button
                className="w-full text-left px-3 py-2 text-sm border border-gray-300 rounded-lg hover:bg-blue-50 transition-colors"
                onClick={() => handleBulkPrmtopChange(undefined)}
              >
                Use Global (default)
              </button>
              {availablePrmtops.map(p => (
                <button
                  key={p.value}
                  className="w-full text-left px-3 py-2 text-sm font-mono border border-gray-300 rounded-lg hover:bg-blue-50 transition-colors truncate"
                  onClick={() => handleBulkPrmtopChange(p.value)}
                  title={p.value}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Gap Settings */}
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-700 mb-3 border-b border-gray-200 pb-2">
            Gap Settings
          </h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-600 mb-1">
                Expected (ps)
              </label>
              <input
                type="number"
                step="0.1"
                placeholder="Set for all..."
                onBlur={(e) => handleBulkGapChange('expected_gap_ps', e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handleBulkGapChange('expected_gap_ps', (e.target as HTMLInputElement).value);
                  }
                }}
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-600 mb-1">
                Tolerance (ps)
              </label>
              <input
                type="number"
                step="0.01"
                placeholder="Set for all..."
                onBlur={(e) => handleBulkGapChange('gap_tolerance_ps', e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handleBulkGapChange('gap_tolerance_ps', (e.target as HTMLInputElement).value);
                  }
                }}
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>
        </div>

        {/* Selected stages list */}
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-700 mb-2">
            Selected Stages
          </h3>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {selectedStages.map(stage => {
              const roleConfig = STAGE_ROLE_CONFIG[stage.role] || STAGE_ROLE_CONFIG[''];
              return (
                <div key={stage.id} className="flex items-center gap-2 px-2 py-1 text-sm bg-gray-50 rounded">
                  <span className={`px-1.5 py-0.5 text-xs rounded ${roleConfig.bgColor} ${roleConfig.color}`}>
                    {roleConfig.label}
                  </span>
                  <span className="truncate">{stage.name}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="p-4 border-t border-gray-200">
        <button
          className="w-full px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors text-sm"
          onClick={clearSelection}
        >
          Clear Selection
        </button>
      </div>
    </div>
  );
}

export function PropertiesPanel() {
  const {
    stages,
    selectedStageId,
    selectedStageIds,
    settings,
    updateStage,
    updateSettings,
  } = useProtocolStore();

  // Show bulk edit panel when multiple stages are selected
  const isMultiSelect = selectedStageIds.length > 1;

  const selectedStage = useMemo(
    () => stages.find((s) => s.id === selectedStageId),
    [stages, selectedStageId]
  );

  // Build current update payload from local state
  const [localName, setLocalName] = useState('');
  const [localRole, setLocalRole] = useState<StageRole>('');
  const [localFiles, setLocalFiles] = useState<StageFiles>({});
  const [localExpectedGap, setLocalExpectedGap] = useState('');
  const [localGapTolerance, setLocalGapTolerance] = useState('');
  const [localNotes, setLocalNotes] = useState('');

  // Track whether we're syncing from store (to avoid triggering auto-save during sync)
  const isSyncing = useRef(false);

  // Sync local state when selected stage changes
  useEffect(() => {
    if (selectedStage) {
      isSyncing.current = true;
      setLocalName(selectedStage.name);
      setLocalRole(selectedStage.role);
      setLocalFiles({ ...selectedStage.files });
      setLocalExpectedGap(selectedStage.expected_gap_ps?.toString() || '');
      setLocalGapTolerance(selectedStage.gap_tolerance_ps?.toString() || '');
      setLocalNotes(selectedStage.notes.join('\n'));
      // Use requestAnimationFrame to ensure state updates have been applied
      requestAnimationFrame(() => {
        isSyncing.current = false;
      });
    }
  }, [selectedStage?.id]);

  // Handlers that update local state AND trigger immediate save
  const handleRoleChange = (role: StageRole) => {
    setLocalRole(role);
    if (selectedStage) {
      updateStage(selectedStage.id, { role });
    }
  };

  const handleFileChange = (fileType: keyof StageFiles, value: string | undefined) => {
    const newFiles = {
      ...localFiles,
      [fileType]: value === undefined ? '' : value,
    };
    setLocalFiles(newFiles);
    if (selectedStage) {
      updateStage(selectedStage.id, { files: newFiles });
    }
  };

  const handleNameBlur = () => {
    if (selectedStage && localName !== selectedStage.name) {
      updateStage(selectedStage.id, { name: localName });
    }
  };

  const handleGapBlur = () => {
    if (!selectedStage) return;
    const expected = localExpectedGap ? parseFloat(localExpectedGap) : undefined;
    const tolerance = localGapTolerance ? parseFloat(localGapTolerance) : undefined;
    if (
      expected !== selectedStage.expected_gap_ps ||
      tolerance !== selectedStage.gap_tolerance_ps
    ) {
      updateStage(selectedStage.id, {
        expected_gap_ps: expected,
        gap_tolerance_ps: tolerance,
      });
    }
  };

  const handleNotesBlur = () => {
    if (!selectedStage) return;
    const newNotes = localNotes.split('\n').filter(Boolean);
    if (JSON.stringify(newNotes) !== JSON.stringify(selectedStage.notes)) {
      updateStage(selectedStage.id, { notes: newNotes });
    }
  };

  // Collect available prmtops for dropdown selection
  const availablePrmtops: { label: string; value: string | undefined }[] = [];
  if (settings.global_prmtop) {
    availablePrmtops.push({
      label: `Normal: ${settings.global_prmtop.split('/').pop()}`,
      value: undefined, // undefined = use global
    });
  }
  if (settings.hmr_prmtop) {
    availablePrmtops.push({
      label: `HMR: ${settings.hmr_prmtop.split('/').pop()}`,
      value: settings.hmr_prmtop,
    });
  }

  // Show bulk edit panel when multiple stages are selected
  if (isMultiSelect) {
    return <BulkEditPanel />;
  }

  // Show global settings when no stage is selected
  if (!selectedStage) {
    return (
      <div className="h-full flex flex-col bg-white border-l border-gray-200">
        <div className="p-4 border-b border-gray-200">
          <h2 className="font-semibold text-gray-800">Global Settings</h2>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Global Prmtop
            </label>
            <p className="text-xs text-gray-500 mb-2">
              Used by stages without their own topology file
            </p>
            <input
              type="text"
              value={settings.global_prmtop || ''}
              onChange={(e) =>
                updateSettings({
                  ...settings,
                  global_prmtop: e.target.value || undefined,
                })
              }
              placeholder="Path to global prmtop file"
              className="w-full px-3 py-2 text-sm font-mono border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              HMR Prmtop (Optional)
            </label>
            <p className="text-xs text-gray-500 mb-2">
              For hydrogen mass repartitioning
            </p>
            <input
              type="text"
              value={settings.hmr_prmtop || ''}
              onChange={(e) =>
                updateSettings({
                  ...settings,
                  hmr_prmtop: e.target.value || undefined,
                })
              }
              placeholder="Path to HMR prmtop file"
              className="w-full px-3 py-2 text-sm font-mono border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Initial Coordinates (Optional)
            </label>
            <p className="text-xs text-gray-500 mb-2">
              Input coordinate file for the very first step (e.g., system.inpcrd, complex.rst7).
              If set, this overrides auto-detection for the first stage.
            </p>
            <input
              type="text"
              value={settings.initial_coordinates || ''}
              onChange={(e) =>
                updateSettings({
                  ...settings,
                  initial_coordinates: e.target.value || undefined,
                })
              }
              placeholder="Path to initial coordinate file"
              className="w-full px-3 py-2 text-sm font-mono border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div className="border-t border-gray-200 pt-4 mt-4">
            <h3 className="text-sm font-medium text-gray-700 mb-3">Options</h3>
            <label
              className="flex items-center gap-2 mb-2 cursor-help"
              title="Automatically chain restart files between stages: first stage uses initial coordinates, subsequent stages use the restart output from the previous stage"
            >
              <input
                type="checkbox"
                checked={settings.auto_link_restarts}
                onChange={(e) =>
                  updateSettings({
                    ...settings,
                    auto_link_restarts: e.target.checked,
                  })
                }
                className="rounded border-gray-300 text-blue-500 focus:ring-blue-500"
              />
              <span className="text-sm text-gray-600">
                Auto-link restart files
              </span>
            </label>
            <label className="flex items-center gap-2 mb-2">
              <input
                type="checkbox"
                checked={settings.validate_on_export}
                onChange={(e) =>
                  updateSettings({
                    ...settings,
                    validate_on_export: e.target.checked,
                  })
                }
                className="rounded border-gray-300 text-blue-500 focus:ring-blue-500"
              />
              <span className="text-sm text-gray-600">Validate on export</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={settings.use_relative_paths}
                onChange={(e) =>
                  updateSettings({
                    ...settings,
                    use_relative_paths: e.target.checked,
                  })
                }
                className="rounded border-gray-300 text-blue-500 focus:ring-blue-500"
              />
              <span className="text-sm text-gray-600">Use relative paths</span>
            </label>
          </div>
        </div>
        <div className="p-3 border-t border-gray-200 text-xs text-gray-500 text-center">
          Select a stage to edit its properties
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-white border-l border-gray-200">
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <h2 className="font-semibold text-gray-800 flex items-center gap-2">
          Stage Properties
          {selectedStage.validation.is_valid ? (
            <Check className="w-4 h-4 text-green-500" />
          ) : selectedStage.validation.missing_files.length > 0 ? (
            <X className="w-4 h-4 text-red-500" />
          ) : (
            <AlertTriangle className="w-4 h-4 text-yellow-500" />
          )}
        </h2>
        <p className="text-xs text-gray-400 mt-1">Changes are saved automatically</p>
      </div>

      {/* Form */}
      <div className="flex-1 overflow-y-auto p-4">
        {/* Name */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Name
          </label>
          <input
            type="text"
            value={localName}
            onChange={(e) => setLocalName(e.target.value)}
            onBlur={handleNameBlur}
            onKeyDown={(e) => { if (e.key === 'Enter') handleNameBlur(); }}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* Role */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Role
          </label>
          <select
            value={localRole}
            onChange={(e) => handleRoleChange(e.target.value as StageRole)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {STAGE_ROLES.map((role) => (
              <option key={role} value={role}>
                {STAGE_ROLE_CONFIG[role].label}
              </option>
            ))}
          </select>
        </div>

        {/* Topology Selection */}
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-700 mb-3 border-b border-gray-200 pb-2">
            Topology
          </h3>

          {/* Dropdown for selecting from pre-loaded prmtops */}
          {availablePrmtops.length > 0 && (
            <div className="mb-3 p-3 bg-gray-50 border border-gray-200 rounded-lg">
              <label className="block text-xs font-medium text-gray-600 mb-2">
                Use Topology
              </label>
              <select
                value={
                  localFiles.prmtop === settings.hmr_prmtop ? 'hmr' :
                  !localFiles.prmtop ? 'global' :
                  'custom'
                }
                onChange={(e) => {
                  if (e.target.value === 'global') {
                    handleFileChange('prmtop', undefined);
                  } else if (e.target.value === 'hmr' && settings.hmr_prmtop) {
                    handleFileChange('prmtop', settings.hmr_prmtop);
                  }
                }}
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="global">
                  Normal (Global): {settings.global_prmtop?.split('/').pop() || 'not set'}
                </option>
                {settings.hmr_prmtop && (
                  <option value="hmr">
                    HMR: {settings.hmr_prmtop.split('/').pop()}
                  </option>
                )}
                {localFiles.prmtop &&
                  localFiles.prmtop !== settings.global_prmtop &&
                  localFiles.prmtop !== settings.hmr_prmtop && (
                  <option value="custom">
                    Custom: {localFiles.prmtop.split('/').pop()}
                  </option>
                )}
              </select>
              <p className="text-xs text-gray-500 mt-1">
                Tip: Use HMR prmtop for stages with dt &ge; 0.004 ps
              </p>
            </div>
          )}

          <FileField
            label="Custom Topology (prmtop)"
            fileType="prmtop"
            value={localFiles.prmtop}
            onChange={(v) => handleFileChange('prmtop', v)}
            globalValue={settings.global_prmtop}
          />

          {/* Show warning if no prmtop is set and no global exists */}
          {!localFiles.prmtop && !settings.global_prmtop && (
            <p className="text-xs text-amber-600 mt-1">
              No topology file set. Set a global prmtop in Global Settings or add one here.
            </p>
          )}
        </div>

        {/* Files */}
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-700 mb-3 border-b border-gray-200 pb-2">
            Simulation Files
          </h3>

          <FileField
            label="Input (mdin)"
            fileType="mdin"
            value={localFiles.mdin}
            onChange={(v) => handleFileChange('mdin', v)}
          />

          <FileField
            label="Output (mdout)"
            fileType="mdout"
            value={localFiles.mdout}
            onChange={(v) => handleFileChange('mdout', v)}
          />

          <FileField
            label="Trajectory (mdcrd)"
            fileType="mdcrd"
            value={localFiles.mdcrd}
            onChange={(v) => handleFileChange('mdcrd', v)}
          />

          <FileField
            label="Coordinates (inpcrd)"
            fileType="inpcrd"
            value={localFiles.inpcrd}
            onChange={(v) => handleFileChange('inpcrd', v)}
          />
        </div>

        {/* Gap Settings */}
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-700 mb-3 border-b border-gray-200 pb-2">
            Gap Settings
          </h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-600 mb-1">
                Expected (ps)
              </label>
              <input
                type="number"
                step="0.1"
                value={localExpectedGap}
                onChange={(e) => setLocalExpectedGap(e.target.value)}
                onBlur={handleGapBlur}
                onKeyDown={(e) => { if (e.key === 'Enter') handleGapBlur(); }}
                placeholder="0.0"
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-600 mb-1">
                Tolerance (ps)
              </label>
              <input
                type="number"
                step="0.01"
                value={localGapTolerance}
                onChange={(e) => setLocalGapTolerance(e.target.value)}
                onBlur={handleGapBlur}
                onKeyDown={(e) => { if (e.key === 'Enter') handleGapBlur(); }}
                placeholder="0.1"
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        </div>

        {/* Notes */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Notes
          </label>
          <textarea
            value={localNotes}
            onChange={(e) => setLocalNotes(e.target.value)}
            onBlur={handleNotesBlur}
            placeholder="Add notes about this stage..."
            rows={3}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>

        {/* Validation messages */}
        {selectedStage.validation.messages.length > 0 && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <h4 className="text-sm font-medium text-red-700 mb-1">Issues</h4>
            {selectedStage.validation.messages.map((msg, i) => (
              <p key={i} className="text-xs text-red-600">
                {msg}
              </p>
            ))}
          </div>
        )}

        {selectedStage.validation.warnings.length > 0 && (
          <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
            <h4 className="text-sm font-medium text-yellow-700 mb-1">
              Warnings
            </h4>
            {selectedStage.validation.warnings.map((msg, i) => (
              <p key={i} className="text-xs text-yellow-600">
                {msg}
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

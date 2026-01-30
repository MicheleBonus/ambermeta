import { useState, useEffect, useMemo } from 'react';
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

export function PropertiesPanel() {
  const { stages, selectedStageId, settings, updateStage, updateSettings } =
    useProtocolStore();

  const selectedStage = useMemo(
    () => stages.find((s) => s.id === selectedStageId),
    [stages, selectedStageId]
  );

  const [localName, setLocalName] = useState('');
  const [localRole, setLocalRole] = useState<StageRole>('');
  const [localFiles, setLocalFiles] = useState<StageFiles>({});
  const [localExpectedGap, setLocalExpectedGap] = useState('');
  const [localGapTolerance, setLocalGapTolerance] = useState('');
  const [localNotes, setLocalNotes] = useState('');
  const [hasChanges, setHasChanges] = useState(false);

  // Sync local state when selected stage changes
  useEffect(() => {
    if (selectedStage) {
      setLocalName(selectedStage.name);
      setLocalRole(selectedStage.role);
      setLocalFiles({ ...selectedStage.files });
      setLocalExpectedGap(selectedStage.expected_gap_ps?.toString() || '');
      setLocalGapTolerance(selectedStage.gap_tolerance_ps?.toString() || '');
      setLocalNotes(selectedStage.notes.join('\n'));
      setHasChanges(false);
    }
  }, [selectedStage]);

  // Mark as changed when any field changes
  useEffect(() => {
    if (!selectedStage) return;

    const filesChanged =
      JSON.stringify(localFiles) !== JSON.stringify(selectedStage.files);
    const hasChange =
      localName !== selectedStage.name ||
      localRole !== selectedStage.role ||
      filesChanged ||
      localExpectedGap !== (selectedStage.expected_gap_ps?.toString() || '') ||
      localGapTolerance !== (selectedStage.gap_tolerance_ps?.toString() || '') ||
      localNotes !== selectedStage.notes.join('\n');

    setHasChanges(hasChange);
  }, [
    selectedStage,
    localName,
    localRole,
    localFiles,
    localExpectedGap,
    localGapTolerance,
    localNotes,
  ]);

  const handleApply = async () => {
    if (!selectedStage || !hasChanges) return;

    await updateStage(selectedStage.id, {
      name: localName,
      role: localRole,
      files: localFiles,
      expected_gap_ps: localExpectedGap ? parseFloat(localExpectedGap) : undefined,
      gap_tolerance_ps: localGapTolerance
        ? parseFloat(localGapTolerance)
        : undefined,
      notes: localNotes.split('\n').filter(Boolean),
    });
  };

  const handleReset = () => {
    if (selectedStage) {
      setLocalName(selectedStage.name);
      setLocalRole(selectedStage.role);
      setLocalFiles({ ...selectedStage.files });
      setLocalExpectedGap(selectedStage.expected_gap_ps?.toString() || '');
      setLocalGapTolerance(selectedStage.gap_tolerance_ps?.toString() || '');
      setLocalNotes(selectedStage.notes.join('\n'));
      setHasChanges(false);
    }
  };

  const handleFileChange = (
    fileType: keyof StageFiles,
    value: string | undefined
  ) => {
    setLocalFiles((prev) => ({
      ...prev,
      [fileType]: value,
    }));
  };

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

          <div className="border-t border-gray-200 pt-4 mt-4">
            <h3 className="text-sm font-medium text-gray-700 mb-3">Options</h3>
            <label className="flex items-center gap-2 mb-2">
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
            onChange={(e) => setLocalRole(e.target.value as StageRole)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {STAGE_ROLES.map((role) => (
              <option key={role} value={role}>
                {STAGE_ROLE_CONFIG[role].label}
              </option>
            ))}
          </select>
        </div>

        {/* Files */}
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-700 mb-3 border-b border-gray-200 pb-2">
            Files
          </h3>

          <FileField
            label="Topology (prmtop)"
            fileType="prmtop"
            value={localFiles.prmtop}
            onChange={(v) => handleFileChange('prmtop', v)}
            globalValue={settings.global_prmtop}
          />

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

      {/* Actions */}
      <div className="p-4 border-t border-gray-200 flex gap-2">
        <button
          className="flex-1 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          onClick={handleApply}
          disabled={!hasChanges}
        >
          <Check className="w-4 h-4" />
          Apply
        </button>
        <button
          className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          onClick={handleReset}
          disabled={!hasChanges}
        >
          Reset
        </button>
      </div>
    </div>
  );
}

import { useState } from 'react';
import { useDroppable } from '@dnd-kit/core';
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { Stage } from '../../types';
import { useProtocolStore } from '../../stores/protocolStore';
import {
  Plus,
  Trash2,
  GripVertical,
  Check,
  AlertTriangle,
  X,
  ChevronDown,
  ChevronRight,
} from '../common/Icons';
import { FileIcon } from '../common/Icons';
import { STAGE_ROLE_CONFIG } from '../../types';

interface StageCardProps {
  stage: Stage;
  isSelected: boolean;
  onSelect: () => void;
  onDelete: () => void;
}

function StageCard({ stage, isSelected, onSelect, onDelete }: StageCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: stage.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const roleConfig = STAGE_ROLE_CONFIG[stage.role] || STAGE_ROLE_CONFIG[''];
  const fileCount = Object.values(stage.files).filter(Boolean).length;
  const totalFiles = 5; // prmtop, mdin, mdout, mdcrd, inpcrd

  const validationStatus = stage.validation.is_valid
    ? 'valid'
    : stage.validation.missing_files.length > 0
    ? 'error'
    : 'warning';

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`
        bg-white rounded-lg border-2 transition-all cursor-pointer
        ${isSelected ? 'border-blue-500 ring-2 ring-blue-200' : 'border-gray-200'}
        ${isDragging ? 'shadow-lg' : 'shadow-sm hover:shadow-md'}
      `}
      onClick={onSelect}
    >
      {/* Header */}
      <div className="flex items-center p-3 gap-2">
        {/* Drag handle */}
        <div
          {...attributes}
          {...listeners}
          className="p-1 cursor-grab hover:bg-gray-100 rounded"
          onClick={(e) => e.stopPropagation()}
        >
          <GripVertical className="w-4 h-4 text-gray-400" />
        </div>

        {/* Stage number and name */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-lg font-semibold text-gray-800 truncate">
              {stage.name}
            </span>
            <span
              className={`px-2 py-0.5 text-xs font-medium rounded-full ${roleConfig.bgColor} ${roleConfig.color}`}
            >
              {roleConfig.label}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-1 text-sm text-gray-500">
            <span>
              {fileCount}/{totalFiles} files
            </span>
            {validationStatus === 'valid' && (
              <Check className="w-4 h-4 text-green-500" />
            )}
            {validationStatus === 'error' && (
              <X className="w-4 h-4 text-red-500" />
            )}
            {validationStatus === 'warning' && (
              <AlertTriangle className="w-4 h-4 text-yellow-500" />
            )}
          </div>
        </div>

        {/* Expand/collapse */}
        <button
          className="p-1 hover:bg-gray-100 rounded"
          onClick={(e) => {
            e.stopPropagation();
            setIsExpanded(!isExpanded);
          }}
        >
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-gray-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-gray-400" />
          )}
        </button>

        {/* Delete */}
        <button
          className="p-1 hover:bg-red-100 rounded text-gray-400 hover:text-red-500"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-3 pb-3 border-t border-gray-100 pt-2">
          <div className="grid grid-cols-5 gap-2">
            {(['prmtop', 'mdin', 'mdout', 'mdcrd', 'inpcrd'] as const).map(
              (fileType) => {
                const filePath = stage.files[fileType];
                const hasFile = Boolean(filePath);

                return (
                  <FileDropZone
                    key={fileType}
                    stageId={stage.id}
                    fileType={fileType}
                    hasFile={hasFile}
                    fileName={filePath ? filePath.split('/').pop() : undefined}
                  />
                );
              }
            )}
          </div>

          {/* Validation messages */}
          {stage.validation.messages.length > 0 && (
            <div className="mt-2 text-xs text-red-600">
              {stage.validation.messages.map((msg, i) => (
                <p key={i}>{msg}</p>
              ))}
            </div>
          )}
          {stage.validation.warnings.length > 0 && (
            <div className="mt-2 text-xs text-yellow-600">
              {stage.validation.warnings.map((msg, i) => (
                <p key={i}>{msg}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface FileDropZoneProps {
  stageId: string;
  fileType: 'prmtop' | 'mdin' | 'mdout' | 'mdcrd' | 'inpcrd';
  hasFile: boolean;
  fileName?: string;
}

function FileDropZone({
  stageId,
  fileType,
  hasFile,
  fileName,
}: FileDropZoneProps) {
  const { isOver, setNodeRef } = useDroppable({
    id: `drop-${stageId}-${fileType}`,
    data: { stageId, fileType },
  });

  return (
    <div
      ref={setNodeRef}
      className={`
        flex flex-col items-center justify-center p-2 rounded border-2 border-dashed
        transition-all text-center min-h-[60px]
        ${isOver ? 'border-blue-400 bg-blue-50' : 'border-gray-200'}
        ${hasFile ? 'bg-gray-50' : ''}
      `}
    >
      <FileIcon type={fileType} className="w-5 h-5 mb-1" />
      <span className="text-xs font-medium text-gray-600">{fileType}</span>
      {hasFile ? (
        <span className="text-xs text-gray-500 truncate max-w-full" title={fileName}>
          {fileName}
        </span>
      ) : (
        <span className="text-xs text-gray-400">Drop here</span>
      )}
    </div>
  );
}

export function StageBuilder() {
  const {
    stages,
    selectedStageId,
    setSelectedStage,
    addStage,
    deleteStage,
    isLoading,
  } = useProtocolStore();

  const [showNewStageDialog, setShowNewStageDialog] = useState(false);
  const [newStageName, setNewStageName] = useState('');

  const handleAddStage = async () => {
    if (newStageName.trim()) {
      await addStage({ name: newStageName.trim() });
      setNewStageName('');
      setShowNewStageDialog(false);
    }
  };

  const handleDeleteStage = async (id: string) => {
    if (confirm('Delete this stage?')) {
      await deleteStage(id);
    }
  };

  const { setNodeRef, isOver } = useDroppable({
    id: 'stage-builder',
    data: { type: 'new-stage' },
  });

  return (
    <div className="h-full flex flex-col bg-gray-50" ref={setNodeRef}>
      {/* Header */}
      <div className="p-4 bg-white border-b border-gray-200 flex items-center justify-between">
        <h2 className="font-semibold text-gray-800 text-lg">Protocol Stages</h2>
        <button
          className="flex items-center gap-1 px-3 py-1.5 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors text-sm font-medium"
          onClick={() => setShowNewStageDialog(true)}
        >
          <Plus className="w-4 h-4" />
          Add Stage
        </button>
      </div>

      {/* Stage list */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {stages.length === 0 ? (
          <div
            className={`
              flex flex-col items-center justify-center h-48 border-2 border-dashed rounded-lg
              ${isOver ? 'border-blue-400 bg-blue-50' : 'border-gray-300'}
            `}
          >
            <p className="text-gray-500 mb-2">No stages yet</p>
            <p className="text-gray-400 text-sm">
              Click "Add Stage" or drag a file here to create a stage
            </p>
          </div>
        ) : (
          <SortableContext
            items={stages.map((s) => s.id)}
            strategy={verticalListSortingStrategy}
          >
            {stages.map((stage, index) => (
              <div key={stage.id}>
                <StageCard
                  stage={stage}
                  isSelected={selectedStageId === stage.id}
                  onSelect={() => setSelectedStage(stage.id)}
                  onDelete={() => handleDeleteStage(stage.id)}
                />
                {index < stages.length - 1 && (
                  <div className="flex justify-center py-1">
                    <div className="w-0.5 h-4 bg-gray-300" />
                  </div>
                )}
              </div>
            ))}
          </SortableContext>
        )}
      </div>

      {/* New stage dialog */}
      {showNewStageDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-96 shadow-xl">
            <h3 className="text-lg font-semibold mb-4">Add New Stage</h3>
            <input
              type="text"
              placeholder="Stage name (e.g., minimize, heat, prod_001)"
              value={newStageName}
              onChange={(e) => setNewStageName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAddStage()}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              autoFocus
            />
            <div className="flex justify-end gap-2 mt-4">
              <button
                className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                onClick={() => setShowNewStageDialog(false)}
              >
                Cancel
              </button>
              <button
                className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors disabled:opacity-50"
                onClick={handleAddStage}
                disabled={!newStageName.trim() || isLoading}
              >
                Add
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

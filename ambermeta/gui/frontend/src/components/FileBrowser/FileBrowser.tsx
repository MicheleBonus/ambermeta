import { useState, useEffect, useCallback } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import type { FileInfo } from '../../types';
import { useProtocolStore } from '../../stores/protocolStore';
import { FileIcon, Search, ChevronRight, ChevronDown } from '../common/Icons';

interface FileTreeItemProps {
  file: FileInfo;
  level: number;
  onContextMenu?: (e: React.MouseEvent, file: FileInfo) => void;
}

function DraggableFileItem({ file, onContextMenu }: Omit<FileTreeItemProps, 'level'>) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `file-${file.path}`,
    data: { type: 'file', file },
  });

  const style = transform
    ? {
        transform: CSS.Translate.toString(transform),
        opacity: isDragging ? 0.5 : 1,
      }
    : undefined;

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className={`
        flex items-center gap-2 px-2 py-1 cursor-grab rounded
        hover:bg-gray-100 transition-colors
        ${isDragging ? 'bg-blue-50 ring-2 ring-blue-200' : ''}
      `}
      onContextMenu={(e) => onContextMenu?.(e, file)}
      title={file.path}
    >
      <FileIcon type={file.file_type} className="w-4 h-4 flex-shrink-0" />
      <span className="text-sm truncate font-mono" title={file.name}>{file.name}</span>
      {file.size && (
        <span className="text-xs text-gray-400 ml-auto flex-shrink-0">
          {formatFileSize(file.size)}
        </span>
      )}
    </div>
  );
}

function FileTreeItem({ file, level, onContextMenu }: FileTreeItemProps) {
  const [isExpanded, setIsExpanded] = useState(level < 2);

  if (file.is_directory) {
    const hasChildren = file.children && file.children.length > 0;

    return (
      <div>
        <div
          className="flex items-center gap-1 px-2 py-1 cursor-pointer hover:bg-gray-100 rounded transition-colors"
          onClick={() => setIsExpanded(!isExpanded)}
          style={{ paddingLeft: `${level * 12 + 8}px` }}
          title={file.path}
        >
          {hasChildren ? (
            isExpanded ? (
              <ChevronDown className="w-4 h-4 text-gray-400" />
            ) : (
              <ChevronRight className="w-4 h-4 text-gray-400" />
            )
          ) : (
            <span className="w-4" />
          )}
          <FileIcon type="folder" className="w-4 h-4" isOpen={isExpanded} />
          <span className="text-sm truncate" title={file.name}>{file.name}</span>
        </div>
        {isExpanded && hasChildren && (
          <div>
            {file.children!.map((child) => (
              <FileTreeItem
                key={child.path}
                file={child}
                level={level + 1}
                onContextMenu={onContextMenu}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{ paddingLeft: `${level * 12 + 28}px` }}>
      <DraggableFileItem file={file} onContextMenu={onContextMenu} />
    </div>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export function FileBrowser() {
  const { files, loadFiles, isLoading, addStage, settings, updateSettings } = useProtocolStore();
  const [searchTerm, setSearchTerm] = useState('');
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    file: FileInfo;
  } | null>(null);

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  const handleContextMenu = useCallback((e: React.MouseEvent, file: FileInfo) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, file });
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(null);
  }, []);

  // Filter files based on search term
  const filterFiles = useCallback(
    (fileList: FileInfo[]): FileInfo[] => {
      if (!searchTerm) return fileList;

      const term = searchTerm.toLowerCase();

      return fileList
        .map((file) => {
          if (file.is_directory && file.children) {
            const filteredChildren = filterFiles(file.children);
            if (filteredChildren.length > 0) {
              return { ...file, children: filteredChildren };
            }
          }
          if (file.name.toLowerCase().includes(term)) {
            return file;
          }
          return null;
        })
        .filter((f): f is FileInfo => f !== null);
    },
    [searchTerm]
  );

  const filteredFiles = filterFiles(files);

  return (
    <div
      className="h-full flex flex-col bg-white border-r border-gray-200"
      onClick={closeContextMenu}
    >
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <h2 className="font-semibold text-gray-800 mb-3 flex items-center gap-2">
          <span className="text-lg">Simulation Files</span>
        </h2>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search files..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
      </div>

      {/* File tree */}
      <div className="flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <div className="flex items-center justify-center h-32">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
          </div>
        ) : filteredFiles.length === 0 ? (
          <div className="text-center text-gray-500 py-8">
            <p className="text-sm">No simulation files found</p>
            <p className="text-xs mt-1">
              Supported: .prmtop, .mdin, .mdout, .nc, .rst7
            </p>
          </div>
        ) : (
          filteredFiles.map((file) => (
            <FileTreeItem
              key={file.path}
              file={file}
              level={0}
              onContextMenu={handleContextMenu}
            />
          ))
        )}
      </div>

      {/* Context menu */}
      {contextMenu && (
        <div
          className="fixed bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-50"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          {contextMenu.file.file_type === 'prmtop' && (
            <>
              <button
                className="w-full px-4 py-2 text-sm text-left hover:bg-gray-100"
                onClick={() => {
                  updateSettings({
                    ...settings,
                    global_prmtop: contextMenu.file.path,
                  });
                  closeContextMenu();
                }}
              >
                Set as Global Prmtop
              </button>
              <button
                className="w-full px-4 py-2 text-sm text-left hover:bg-gray-100"
                onClick={() => {
                  updateSettings({
                    ...settings,
                    hmr_prmtop: contextMenu.file.path,
                  });
                  closeContextMenu();
                }}
              >
                Set as Global HMR Prmtop
              </button>
            </>
          )}
          {!contextMenu.file.is_directory && contextMenu.file.file_type !== 'prmtop' && (
            <button
              className="w-full px-4 py-2 text-sm text-left hover:bg-gray-100"
              onClick={async () => {
                const file = contextMenu.file;
                const stageName = file.name.replace(/\.[^/.]+$/, '');
                await addStage({
                  name: stageName,
                  files: { [file.file_type]: file.path },
                });
                closeContextMenu();
              }}
            >
              Create Stage from This File
            </button>
          )}
          {contextMenu.file.is_directory && (
            <button
              className="w-full px-4 py-2 text-sm text-left hover:bg-gray-100"
              onClick={() => {
                // This will be enhanced with auto-discovery modal later
                closeContextMenu();
              }}
            >
              Auto-Discover Stages...
            </button>
          )}
        </div>
      )}

      {/* Footer with file count */}
      <div className="p-2 border-t border-gray-200 text-xs text-gray-500">
        {files.length} files found
      </div>
    </div>
  );
}

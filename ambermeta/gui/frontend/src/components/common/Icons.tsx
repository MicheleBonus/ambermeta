import {
  Folder,
  FolderOpen,
  File,
  Settings,
  BarChart3,
  Film,
  RefreshCw,
  Dna,
  Search,
  ChevronRight,
  ChevronDown,
  ChevronsUpDown,
  Plus,
  Trash2,
  GripVertical,
  Download,
  Upload,
  Save,
  Undo2,
  Redo2,
  Check,
  AlertTriangle,
  X,
  Menu,
  MoreVertical,
  Wand2,
  Layers,
  type LucideIcon,
} from 'lucide-react';
import type { FileType } from '../../types';

export {
  Folder,
  FolderOpen,
  File,
  Settings,
  BarChart3,
  Film,
  RefreshCw,
  Dna,
  Search,
  ChevronRight,
  ChevronDown,
  ChevronsUpDown,
  Plus,
  Trash2,
  GripVertical,
  Download,
  Upload,
  Save,
  Undo2,
  Redo2,
  Check,
  AlertTriangle,
  X,
  Menu,
  MoreVertical,
  Wand2,
  Layers,
};

const FILE_TYPE_ICONS: Record<FileType, LucideIcon> = {
  prmtop: Dna,
  mdin: Settings,
  mdout: BarChart3,
  mdcrd: Film,
  inpcrd: RefreshCw,
  folder: Folder,
  other: File,
};

interface FileIconProps {
  type: FileType;
  className?: string;
  isOpen?: boolean;
}

export function FileIcon({ type, className = '', isOpen }: FileIconProps) {
  if (type === 'folder') {
    const Icon = isOpen ? FolderOpen : Folder;
    return <Icon className={`text-gray-500 ${className}`} />;
  }

  const Icon = FILE_TYPE_ICONS[type] || File;
  const colorClass = {
    prmtop: 'text-green-500',
    mdin: 'text-yellow-500',
    mdout: 'text-cyan-500',
    mdcrd: 'text-purple-500',
    inpcrd: 'text-blue-500',
    other: 'text-gray-400',
  }[type];

  return <Icon className={`${colorClass} ${className}`} />;
}

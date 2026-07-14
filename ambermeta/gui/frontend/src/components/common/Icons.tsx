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
  ArrowDown,
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
  ArrowDown,
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
    return <Icon className={`text-ink-muted ${className}`} />;
  }

  const Icon = FILE_TYPE_ICONS[type] || File;
  const colorClass = {
    prmtop: 'text-ink',
    mdin: 'text-ink',
    mdout: 'text-ink',
    mdcrd: 'text-ink',
    inpcrd: 'text-ink',
    other: 'text-ink-muted',
  }[type];

  return <Icon className={`${colorClass} ${className}`} />;
}

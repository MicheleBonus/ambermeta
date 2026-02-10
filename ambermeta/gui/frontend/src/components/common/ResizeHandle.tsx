import { useState, useCallback, useEffect, useRef } from 'react';

interface ResizeHandleProps {
  /** Direction the handle resizes: 'left' means the panel to the left resizes */
  direction: 'left' | 'right';
  /** Current width of the panel being resized */
  currentWidth: number;
  /** Callback when width changes */
  onResize: (newWidth: number) => void;
  /** Minimum width constraint */
  minWidth?: number;
  /** Maximum width constraint */
  maxWidth?: number;
}

export function ResizeHandle({
  direction,
  currentWidth,
  onResize,
  minWidth = 180,
  maxWidth = 600,
}: ResizeHandleProps) {
  const [isDragging, setIsDragging] = useState(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setIsDragging(true);
      startXRef.current = e.clientX;
      startWidthRef.current = currentWidth;
    },
    [currentWidth]
  );

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - startXRef.current;
      const multiplier = direction === 'left' ? 1 : -1;
      const newWidth = Math.max(
        minWidth,
        Math.min(maxWidth, startWidthRef.current + delta * multiplier)
      );
      onResize(newWidth);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    // Prevent text selection while dragging
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    };
  }, [isDragging, direction, minWidth, maxWidth, onResize]);

  return (
    <div
      className={`
        flex-shrink-0 w-1.5 cursor-col-resize group relative
        ${isDragging ? 'bg-blue-400' : 'bg-gray-200 hover:bg-blue-300'}
        transition-colors duration-150
      `}
      onMouseDown={handleMouseDown}
      title="Drag to resize"
    >
      {/* Wider invisible hit target for easier grabbing */}
      <div className="absolute inset-y-0 -left-1 -right-1 z-10" />
      {/* Visual grip indicator */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <div className="w-0.5 h-0.5 bg-gray-500 rounded-full" />
        <div className="w-0.5 h-0.5 bg-gray-500 rounded-full" />
        <div className="w-0.5 h-0.5 bg-gray-500 rounded-full" />
      </div>
    </div>
  );
}

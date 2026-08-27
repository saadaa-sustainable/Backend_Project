"use client";

import { useState, type ReactNode } from "react";

export interface GridItem {
  id: string;
  span?: 1 | 2 | 3;
  content: ReactNode;
}

interface Props {
  items: GridItem[];
  order: string[];
  onReorder: (order: string[]) => void;
}

/** Drag-to-reorder grid -- native HTML5 DnD, no library. Each tile is
 * `draggable`; dropping on another tile swaps them into the dragged
 * tile's position. Order is controlled (parent owns/persists it) so
 * callers can save it to localStorage or a backend without this
 * component knowing about either. */
export function DraggableGrid({ items, order, onReorder }: Props) {
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  const byId = new Map(items.map((i) => [i.id, i]));
  const ordered = order.map((id) => byId.get(id)).filter((i): i is GridItem => Boolean(i));

  function handleDrop(targetId: string) {
    if (!draggingId || draggingId === targetId) {
      setDraggingId(null);
      setDragOverId(null);
      return;
    }
    const next = [...order];
    const fromIdx = next.indexOf(draggingId);
    const toIdx = next.indexOf(targetId);
    next.splice(fromIdx, 1);
    next.splice(toIdx, 0, draggingId);
    onReorder(next);
    setDraggingId(null);
    setDragOverId(null);
  }

  const spanClass = { 1: "md:col-span-1", 2: "md:col-span-2", 3: "md:col-span-3" } as const;

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {ordered.map((item) => (
        <div
          key={item.id}
          draggable
          onDragStart={() => setDraggingId(item.id)}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOverId(item.id);
          }}
          onDragLeave={() => setDragOverId((prev) => (prev === item.id ? null : prev))}
          onDrop={() => handleDrop(item.id)}
          onDragEnd={() => {
            setDraggingId(null);
            setDragOverId(null);
          }}
          className={`${spanClass[item.span ?? 1]} cursor-grab rounded-lg border bg-white p-4 shadow-sm transition-all active:cursor-grabbing ${
            draggingId === item.id
              ? "border-accent-yellow opacity-40"
              : dragOverId === item.id
                ? "border-accent-yellow"
                : "border-border-primary"
          }`}
        >
          {item.content}
        </div>
      ))}
    </div>
  );
}

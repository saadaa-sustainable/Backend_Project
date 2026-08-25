"use client";

// Shared "which metrics did the admin check in the schema browser" state,
// so the table builder (/build) can pick up exactly what was selected on
// /schema without round-tripping through localStorage or the URL. Plain
// column selections and JSONB-discovered inner keys live in the same Set,
// the latter namespaced as "{column}.{key}" (see JsonbColumnExplorer).

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

export type Selection = Record<string, Set<string>>; // table name -> selected field names

interface SelectionContextValue {
  selection: Selection;
  toggle: (table: string, field: string) => void;
  clear: (table?: string) => void;
  count: number;
}

const SelectionContext = createContext<SelectionContextValue | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [selection, setSelection] = useState<Selection>({});

  const toggle = (table: string, field: string) => {
    setSelection((prev) => {
      const next = { ...prev };
      const set = new Set(next[table] ?? []);
      if (set.has(field)) {
        set.delete(field);
      } else {
        set.add(field);
      }
      if (set.size === 0) {
        delete next[table];
      } else {
        next[table] = set;
      }
      return next;
    });
  };

  const clear = (table?: string) => {
    setSelection((prev) => {
      if (!table) return {};
      const next = { ...prev };
      delete next[table];
      return next;
    });
  };

  const count = useMemo(
    () => Object.values(selection).reduce((sum, set) => sum + set.size, 0),
    [selection],
  );

  return (
    <SelectionContext.Provider value={{ selection, toggle, clear, count }}>
      {children}
    </SelectionContext.Provider>
  );
}

export function useSelection(): SelectionContextValue {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error("useSelection must be used within a SelectionProvider");
  return ctx;
}

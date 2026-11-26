"use client";

import { useId, useMemo, useState } from "react";

export type PickerOption = { id: string; name: string; hint: string };

/** Every word typed must appear somewhere in the name, in any order. */
export function matchesWords(name: string, query: string): boolean {
  const n = name.toLowerCase();
  return query.toLowerCase().split(/\s+/).filter(Boolean).every((w) => n.includes(w));
}

const MAX_SHOWN = 50;

/** A search box with a dropdown of matching campaigns and a ▾ to open the full list. */
export function CampaignPicker({
  label,
  placeholder,
  text,
  onText,
  options,
  onPick,
  disabled,
}: {
  label: string;
  placeholder: string;
  text: string;
  onText: (t: string) => void;
  options: PickerOption[];
  onPick: (o: PickerOption) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const matches = useMemo(() => options.filter((o) => matchesWords(o.name, text)), [options, text]);
  const shown = matches.slice(0, MAX_SHOWN);

  const pick = (o: PickerOption) => {
    onPick(o);
    setOpen(false);
  };

  return (
    <div className="relative min-w-[260px] flex-1">
      <div
        className={`flex items-center gap-2 rounded-md border bg-bg-white px-3 py-1.5 ${
          open ? "border-accent-yellow ring-1 ring-accent-yellow" : "border-border-primary"
        } ${disabled ? "opacity-60" : ""}`}
      >
        <label htmlFor={id} className="shrink-0 text-[12px] text-text-tertiary">
          {label}
        </label>
        <input
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          autoComplete="off"
          value={text}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(e) => {
            onText(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          // Closing on blur waits a tick so a click on an option lands first.
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setOpen(true);
              setActive((a) => Math.min(a + 1, shown.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter" && open && shown[active]) {
              e.preventDefault();
              pick(shown[active]);
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          // The box around it carries the focus ring, so the global one would be a second ring.
          style={{ outline: "none" }}
          className="min-w-0 flex-1 border-0 bg-transparent p-0 text-[13px] text-text-primary shadow-none outline-none ring-0 placeholder:text-text-tertiary focus:outline-none focus:ring-0"
        />
        <button
          type="button"
          tabIndex={-1}
          disabled={disabled}
          aria-label={open ? "Close list" : "Show all campaigns"}
          onMouseDown={(e) => {
            e.preventDefault();
            setOpen((o) => !o);
          }}
          className="shrink-0 px-1 text-[12px] text-text-secondary hover:text-text-primary"
        >
          <span className={`inline-block transition-transform ${open ? "rotate-180" : ""}`}>▼</span>
        </button>
      </div>

      {open && !disabled && (
        <ul
          id={`${id}-list`}
          role="listbox"
          className="absolute left-0 right-0 z-30 mt-1 max-h-80 overflow-y-auto rounded-md border border-border-primary bg-bg-white py-1 shadow-lg"
        >
          {shown.length === 0 && <li className="px-3 py-2 text-[12.5px] text-text-tertiary">No campaign matches every word.</li>}
          {shown.map((o, i) => (
            <li
              key={o.id}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(o);
              }}
              onMouseEnter={() => setActive(i)}
              className={`flex cursor-pointer items-baseline justify-between gap-3 px-3 py-1.5 ${i === active ? "bg-bg-muted" : ""}`}
            >
              <span className="truncate text-[12.5px] text-text-primary" title={o.name}>
                {o.name}
              </span>
              <span className="shrink-0 text-[11px] text-text-tertiary">{o.hint}</span>
            </li>
          ))}
          {matches.length > MAX_SHOWN && (
            <li className="px-3 py-1.5 text-[11px] text-text-tertiary">
              {matches.length - MAX_SHOWN} more — type another word to narrow down
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

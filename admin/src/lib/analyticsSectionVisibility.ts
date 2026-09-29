"use client";

import { createContext, useContext } from "react";

// A retained section stays mounted when hidden. Portalled dialogs need this
// signal because document.body is outside the section's hidden DOM subtree.
export const AnalyticsSectionVisibility = createContext(true);

export function useAnalyticsSectionVisible(): boolean {
  return useContext(AnalyticsSectionVisibility);
}

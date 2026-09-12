'use client';

import { create } from 'zustand';

/**
 * Which employee is using the app. Stands in for authentication, which is deliberately out of
 * scope - see docs/NOTE.md. Switching clears cached queries so no data crosses between roles.
 */
interface RoleState {
  empCode: string | null;
  setEmpCode: (code: string) => void;
}

export const useRole = create<RoleState>(set => ({
  empCode: null,
  setEmpCode: code => set({ empCode: code }),
}));

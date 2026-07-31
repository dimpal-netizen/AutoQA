/** Auth session state, persisted to localStorage.
 *
 *  `skipHydration` is deliberate: with SSR, reading localStorage during the
 *  first render causes a hydration mismatch. The AuthProvider rehydrates on
 *  mount instead, and `hydrated` tells guards when it is safe to redirect.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { TokenPair, User } from "@/lib/types";

interface AuthState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  hydrated: boolean;

  setSession: (tokens: TokenPair) => void;
  setUser: (user: User) => void;
  setHydrated: (value: boolean) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      hydrated: false,

      setSession: (tokens) =>
        set({
          user: tokens.user,
          accessToken: tokens.access_token,
          refreshToken: tokens.refresh_token,
        }),

      setUser: (user) => set({ user }),

      setHydrated: (value) => set({ hydrated: value }),

      logout: () =>
        set({ user: null, accessToken: null, refreshToken: null }),
    }),
    {
      name: "autoqa-auth",
      skipHydration: true,
      // `hydrated` is runtime-only — persisting it would defeat the purpose.
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
      }),
    },
  ),
);

export const useIsAuthenticated = () =>
  useAuthStore((s) => Boolean(s.accessToken));

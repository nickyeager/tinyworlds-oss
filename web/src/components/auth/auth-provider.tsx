"use client";

import {
  createContext,
  useReducer,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import {
  getToken,
  saveToken,
  clearAllAuthData,
  saveUser,
  getUser,
  type StoredUser,
} from "@/lib/token-storage";
import {
  getAnonymousToken,
  getCurrentUser,
  login as apiLogin,
  register as apiRegister,
  logout as apiLogout,
  upgradeAccount as apiUpgradeAccount,
  type User,
} from "@/lib/auth";

// State types
interface AuthState {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isAnonymous: boolean;
  sessionExpired: boolean;
}

type AuthAction =
  | { type: "INIT_START" }
  | { type: "INIT_COMPLETE"; user: User | null; token: string | null }
  | { type: "LOGIN_SUCCESS"; user: User; token: string }
  | { type: "LOGOUT" }
  | { type: "SESSION_EXPIRED" }
  | { type: "DISMISS_SESSION_EXPIRED" }
  | { type: "UPGRADE_SUCCESS"; user: User };

// Context type
export interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    username: string,
    password: string,
    inviteToken?: string
  ) => Promise<void>;
  logout: () => Promise<void>;
  upgradeAccount: (email: string, username: string, password: string) => Promise<void>;
  ensureToken: () => Promise<string>;
  dismissSessionExpired: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

// Reducer
function authReducer(state: AuthState, action: AuthAction): AuthState {
  switch (action.type) {
    case "INIT_START":
      return { ...state, isLoading: true };

    case "INIT_COMPLETE":
      return {
        ...state,
        isLoading: false,
        user: action.user,
        token: action.token,
        isAuthenticated: !!action.token,
        isAnonymous: action.user?.is_anonymous ?? false,
      };

    case "LOGIN_SUCCESS":
      return {
        ...state,
        user: action.user,
        token: action.token,
        isAuthenticated: true,
        isAnonymous: action.user.is_anonymous,
        sessionExpired: false,
      };

    case "LOGOUT":
      return {
        ...state,
        user: null,
        token: null,
        isAuthenticated: false,
        isAnonymous: false,
        sessionExpired: false,
      };

    case "SESSION_EXPIRED":
      return {
        ...state,
        user: null,
        token: null,
        isAuthenticated: false,
        isAnonymous: false,
        sessionExpired: true,
      };

    case "DISMISS_SESSION_EXPIRED":
      return { ...state, sessionExpired: false };

    case "UPGRADE_SUCCESS":
      return {
        ...state,
        user: action.user,
        isAnonymous: false,
      };

    default:
      return state;
  }
}

const initialState: AuthState = {
  user: null,
  token: null,
  isLoading: true,
  isAuthenticated: false,
  isAnonymous: false,
  sessionExpired: false,
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// Endpoints whose 401 means "bad credentials", not "session expired".
const SESSION_EXPIRY_EXEMPT = [
  "/api/v1/auth/login",
  "/api/v1/auth/register",
  "/api/v1/auth/anonymous",
  "/api/v1/auth/forgot-password",
  "/api/v1/auth/reset-password",
  "/api/v1/auth/invitation/",
];

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(authReducer, initialState);

  // Global fetch interceptor: any 401 from our API on an authed request flips
  // the session into the expired state so the nav can react immediately.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const originalFetch = window.fetch.bind(window);

    window.fetch = async (input, init) => {
      const response = await originalFetch(input, init);
      if (response.status !== 401) return response;

      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      if (!url.startsWith(API_BASE)) return response;
      if (SESSION_EXPIRY_EXEMPT.some((p) => url.includes(p))) return response;

      // Only treat as expiry when the caller sent an Authorization header.
      const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
      if (!headers.has("Authorization")) return response;

      clearAllAuthData();
      dispatch({ type: "SESSION_EXPIRED" });
      return response;
    };

    return () => {
      window.fetch = originalFetch;
    };
  }, []);

  // Initialize auth state from localStorage
  useEffect(() => {
    async function init() {
      dispatch({ type: "INIT_START" });

      const token = getToken();
      if (!token) {
        dispatch({ type: "INIT_COMPLETE", user: null, token: null });
        return;
      }

      try {
        const user = await getCurrentUser(token);
        // Update stored user
        saveUser({
          id: user.id,
          email: user.is_anonymous ? null : user.email,
          username: user.username,
          isAnonymous: user.is_anonymous,
        });
        dispatch({ type: "INIT_COMPLETE", user, token });
      } catch {
        // Token invalid, clear it
        clearAllAuthData();
        dispatch({ type: "INIT_COMPLETE", user: null, token: null });
      }
    }

    init();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const authResponse = await apiLogin(email, password);
    saveToken(authResponse.access_token, authResponse.expires_in);

    // Fetch full user data
    const user = await getCurrentUser(authResponse.access_token);
    saveUser({
      id: user.id,
      email: user.email,
      username: user.username,
      isAnonymous: user.is_anonymous,
    });

    dispatch({ type: "LOGIN_SUCCESS", user, token: authResponse.access_token });
  }, []);

  const register = useCallback(
    async (
      email: string,
      username: string,
      password: string,
      inviteToken?: string
    ) => {
      const authResponse = await apiRegister(
        email,
        username,
        password,
        inviteToken
      );
      saveToken(authResponse.access_token, authResponse.expires_in);

      // Fetch full user data
      const user = await getCurrentUser(authResponse.access_token);
      saveUser({
        id: user.id,
        email: user.email,
        username: user.username,
        isAnonymous: user.is_anonymous,
      });

      dispatch({ type: "LOGIN_SUCCESS", user, token: authResponse.access_token });
    },
    []
  );

  const logout = useCallback(async () => {
    try {
      if (state.token) {
        await apiLogout(state.token);
      }
    } finally {
      clearAllAuthData();
      dispatch({ type: "LOGOUT" });
    }
  }, [state.token]);

  const upgradeAccount = useCallback(
    async (email: string, username: string, password: string) => {
      if (!state.token) {
        throw new Error("No active session");
      }

      const authResponse = await apiUpgradeAccount(
        state.token,
        email,
        username,
        password
      );
      saveToken(authResponse.access_token, authResponse.expires_in);

      // Fetch updated user data
      const user = await getCurrentUser(authResponse.access_token);
      saveUser({
        id: user.id,
        email: user.email,
        username: user.username,
        isAnonymous: false,
      });

      dispatch({ type: "UPGRADE_SUCCESS", user });
    },
    [state.token]
  );

  // Get existing token or create anonymous one
  const ensureToken = useCallback(async (): Promise<string> => {
    // Return existing valid token
    if (state.token) {
      return state.token;
    }

    // Check localStorage
    const storedToken = getToken();
    if (storedToken) {
      return storedToken;
    }

    // Get new anonymous token
    const authResponse = await getAnonymousToken();
    saveToken(authResponse.access_token, authResponse.expires_in);

    // Fetch user data for anonymous user
    const user = await getCurrentUser(authResponse.access_token);
    saveUser({
      id: user.id,
      email: null,
      username: user.username,
      isAnonymous: true,
    });

    dispatch({
      type: "INIT_COMPLETE",
      user,
      token: authResponse.access_token,
    });

    return authResponse.access_token;
  }, [state.token]);

  const dismissSessionExpired = useCallback(() => {
    dispatch({ type: "DISMISS_SESSION_EXPIRED" });
  }, []);

  return (
    <AuthContext.Provider
      value={{
        ...state,
        login,
        register,
        logout,
        upgradeAccount,
        ensureToken,
        dismissSessionExpired,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

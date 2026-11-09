import { create } from "zustand";

interface AuthState {
  token: string | null;
  email: string | null;
  role: string | null;
  login: (token: string, email: string, role: string) => void;
  logout: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  token: localStorage.getItem("nx_token"),
  email: localStorage.getItem("nx_email"),
  role: localStorage.getItem("nx_role"),
  login: (token, email, role) => {
    localStorage.setItem("nx_token", token);
    localStorage.setItem("nx_email", email);
    localStorage.setItem("nx_role", role || "editor");
    set({ token, email, role: role || "editor" });
  },
  logout: () => {
    localStorage.removeItem("nx_token");
    localStorage.removeItem("nx_email");
    localStorage.removeItem("nx_role");
    set({ token: null, email: null, role: null });
  },
}));

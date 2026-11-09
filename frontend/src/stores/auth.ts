import { create } from "zustand";

interface AuthState {
  token: string | null;
  email: string | null;
  login: (token: string, email: string) => void;
  logout: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  token: localStorage.getItem("nx_token"),
  email: localStorage.getItem("nx_email"),
  login: (token, email) => {
    localStorage.setItem("nx_token", token);
    localStorage.setItem("nx_email", email);
    set({ token, email });
  },
  logout: () => {
    localStorage.removeItem("nx_token");
    localStorage.removeItem("nx_email");
    set({ token: null, email: null });
  },
}));

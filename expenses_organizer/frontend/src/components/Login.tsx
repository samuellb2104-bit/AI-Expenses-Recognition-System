import { useState } from "react";
import type { FormEvent } from "react";
import { isSupabaseConfigured, supabase } from "../lib/supabaseClient";
import { BrandLogo } from "./Brand";
import { ThemeToggle } from "./ThemeToggle";

export function Login({ leaving = false }: { leaving?: boolean }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
      if (signInError) {
        setError("Email o password incorrectos.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-screen">
      <div className="login-theme">
        <ThemeToggle />
      </div>
      <form className={leaving ? "login-card leaving" : "login-card"} onSubmit={handleSubmit}>
        <h1 className="brand-heading">
          <BrandLogo height={40} />
          <span className="visually-hidden">Organizador de Egresos</span>
        </h1>
        <p className="subtitle">Inicia sesion para continuar.</p>

        {!isSupabaseConfigured && (
          <p className="error-text">
            Falta configurar VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY en frontend/.env.
          </p>
        )}

        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            required
          />
        </label>

        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {error && <p className="error-text">{error}</p>}

        <button type="submit" disabled={submitting || leaving || !isSupabaseConfigured}>
          {submitting ? "Ingresando..." : "Ingresar"}
        </button>
      </form>
    </div>
  );
}

import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { DocumentsTable } from "./components/DocumentsTable";
import { Login } from "./components/Login";
import { Reports } from "./components/Reports";
import { UploadDocument } from "./components/UploadDocument";
import { supabase } from "./lib/supabaseClient";
import "./App.css";

type View = "documents" | "reports";

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [sessionLoaded, setSessionLoaded] = useState(false);
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [view, setView] = useState<View>("documents");

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setSessionLoaded(true);
    });

    const { data: subscription } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
    });

    return () => subscription.subscription.unsubscribe();
  }, []);

  if (!sessionLoaded) {
    return null;
  }

  if (!session) {
    return <Login />;
  }

  return (
    <div className="app">
      <header>
        <div className="header-row">
          <h1>Organizador de Egresos</h1>
          <button className="logout-button" onClick={() => supabase.auth.signOut()}>
            Cerrar sesion
          </button>
        </div>
        <p className="subtitle">Sube tus facturas y recibos; el OCR y Claude se encargan del resto.</p>
      </header>

      <nav className="view-tabs">
        <button className={view === "documents" ? "active" : ""} onClick={() => setView("documents")}>
          Documentos
        </button>
        <button className={view === "reports" ? "active" : ""} onClick={() => setView("reports")}>
          Reportes
        </button>
      </nav>

      {view === "documents" && (
        <>
          <section>
            <UploadDocument onProcessed={() => setRefreshSignal((n) => n + 1)} />
          </section>

          <section>
            <h2>Documentos</h2>
            <DocumentsTable refreshSignal={refreshSignal} />
          </section>
        </>
      )}

      {view === "reports" && (
        <section>
          <Reports refreshSignal={refreshSignal} />
        </section>
      )}
    </div>
  );
}

export default App;

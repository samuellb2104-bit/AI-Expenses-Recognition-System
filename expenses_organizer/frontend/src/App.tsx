import { useEffect, useRef, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { DocumentsTable } from "./components/DocumentsTable";
import { DuplicatesView } from "./components/DuplicatesView";
import { BrandLogo, Loader, Splash } from "./components/Brand";
import { ThemeToggle } from "./components/ThemeToggle";
import { resetSplash } from "./lib/splash";
import { Login } from "./components/Login";
import { Reports } from "./components/Reports";
import { UploadDocument } from "./components/UploadDocument";
import { VendorsView } from "./components/VendorsView";
import { supabase } from "./lib/supabaseClient";
import "./App.css";

const LOGIN_EXIT_MS = 320;

type View = "documents" | "vendors" | "duplicates" | "reports";

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [sessionLoaded, setSessionLoaded] = useState(false);
  const [splashDone, setSplashDone] = useState(false);
  const [loginLeaving, setLoginLeaving] = useState(false);
  const sessionRef = useRef<Session | null>(null);
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [view, setView] = useState<View>("documents");
  const [selectedVendorId, setSelectedVendorId] = useState<string | undefined>(undefined);

  useEffect(() => {
    function applySession(next: Session | null) {
      sessionRef.current = next;
      setSession(next);
    }

    let exitTimer: number | undefined;

    supabase.auth.getSession().then(({ data }) => {
      applySession(data.session);
      setSessionLoaded(true);
    });

    const { data: subscription } = supabase.auth.onAuthStateChange((event, newSession) => {
      // A fresh sign-in from the login form: let the card fade out before the splash
      // takes over, instead of cutting straight to it.
      if (event === "SIGNED_IN" && newSession && !sessionRef.current) {
        sessionRef.current = newSession;
        setLoginLeaving(true);
        exitTimer = window.setTimeout(() => {
          setSession(newSession);
          setLoginLeaving(false);
        }, LOGIN_EXIT_MS);
        return;
      }
      window.clearTimeout(exitTimer);
      setLoginLeaving(false);
      applySession(newSession);
    });

    return () => {
      window.clearTimeout(exitTimer);
      subscription.subscription.unsubscribe();
    };
  }, []);

  if (!sessionLoaded) {
    return (
      <div className="login-screen">
        <Loader />
      </div>
    );
  }

  if (!session) {
    return <Login leaving={loginLeaving} />;
  }

  return (
    <div className="app">
      {!splashDone && <Splash onDone={() => setSplashDone(true)} />}
      <header>
        <div className="header-row">
          <h1>
            <BrandLogo height={34} />
            <span className="visually-hidden">Organizador de Egresos</span>
          </h1>
          <div className="header-actions">
            <ThemeToggle />
            <button
              className="logout-button"
              onClick={() => {
                resetSplash();
                setSplashDone(false);
                supabase.auth.signOut();
              }}
            >
              Cerrar sesion
            </button>
          </div>
        </div>
        <p className="subtitle">Sube tus facturas y recibos; la IA extrae proveedor, valor y fecha por ti.</p>
      </header>

      <nav className="view-tabs">
        <button className={view === "documents" ? "active" : ""} onClick={() => setView("documents")}>
          Documentos
        </button>
        <button className={view === "vendors" ? "active" : ""} onClick={() => setView("vendors")}>
          Proveedores
        </button>
        <button className={view === "duplicates" ? "active" : ""} onClick={() => setView("duplicates")}>
          Duplicados
        </button>
        <button className={view === "reports" ? "active" : ""} onClick={() => setView("reports")}>
          Reportes
        </button>
      </nav>

      <div key={view} className="view">
      {view === "documents" && (
        <>
          <section>
            <UploadDocument onProcessed={() => setRefreshSignal((n) => n + 1)} />
          </section>

          <section>
            <h2>Documentos</h2>
            <DocumentsTable refreshSignal={refreshSignal} presetVendorId={selectedVendorId} />
          </section>
        </>
      )}

      {view === "vendors" && (
        <section>
          <h2>Proveedores</h2>
          <VendorsView
            refreshSignal={refreshSignal}
            onSelectVendor={(vendorId) => {
              setSelectedVendorId(vendorId);
              setView("documents");
            }}
          />
        </section>
      )}

      {view === "duplicates" && (
        <section>
          <h2>Egresos duplicados</h2>
          <DuplicatesView onChanged={() => setRefreshSignal((n) => n + 1)} />
        </section>
      )}

      {view === "reports" && (
        <section>
          <Reports refreshSignal={refreshSignal} />
        </section>
      )}
      </div>
    </div>
  );
}

export default App;

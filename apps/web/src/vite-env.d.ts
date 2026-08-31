/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute origin+prefix for services/project when it's hosted separately
   * from this frontend (e.g. Render, where each service gets its own
   * subdomain) — e.g. "https://connplex-project.onrender.com/api/pm".
   * Unset in local dev, where the Vite proxy handles the relative path. */
  readonly VITE_PM_API_BASE?: string;
  /** Same idea for services/zoning-engine, e.g.
   * "https://connplex-zoning-engine.onrender.com/api". */
  readonly VITE_ZONING_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

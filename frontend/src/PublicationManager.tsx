import {useEffect, useState, type FormEvent} from "react";
import {api, downloadFile} from "./api";

type Account = {id: string; nickname: string};
type PublicationRow = {
  publication_id: string;
  item_id: string | null;
  status: string;
  sku: string;
  product_id: string;
  title: string;
  account_id: string;
  account_nickname: string;
  published_at: string | null;
};
type JobRow = {
  id: string;
  status: string;
  total: number;
  processed: number;
  succeeded: number;
  failed: number;
  created_at: string;
  requested_by_user_id: string | null;
};
type AuditRow = {id: string; event_type: string; entity_type: string; entity_id: string; actor_name: string | null; created_at: string};
type Page<T> = {total: number; limit: number; offset: number; items: T[]};
const PAGE_SIZE = 25;

function formattedDate(value: string | null): string {
  return value ? new Date(value).toLocaleString("es-AR") : "—";
}

function failureMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Error inesperado";
}

/** Read-only lookup. Mutations must go through independently authorized preview/apply workflows. */
export function PublicationManager({canAudit}: {canAudit: boolean}) {
  const [tab, setTab] = useState<"publications" | "jobs" | "audit">("publications");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [accountId, setAccountId] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [publications, setPublications] = useState<Page<PublicationRow> | null>(null);
  const [jobs, setJobs] = useState<Page<JobRow> | null>(null);
  const [events, setEvents] = useState<Page<AuditRow> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let alive = true;
    void api<Account[]>("/api/accounts").then(data => {
      if (alive) setAccounts(data);
    }).catch(problem => {
      if (alive) setError(failureMessage(problem));
    });
    return () => {alive = false;};
  }, []);

  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    const params = new URLSearchParams({limit: String(PAGE_SIZE), offset: String(offset)});
    if (status) params.set(tab === "audit" ? "event_type" : "status", status);
    if (tab === "publications") {
      if (query) params.set("q", query);
      if (accountId) params.set("account_id", accountId);
    }
    setLoading(true);
    setError("");
    const path = `/api/manager/${tab}?${params.toString()}`;
    const request = tab === "publications"
      ? api<Page<PublicationRow>>(path, {signal: controller.signal}).then(result => {
          if (alive) setPublications(result);
        })
      : tab === "jobs"
        ? api<Page<JobRow>>(path, {signal: controller.signal}).then(result => {
            if (alive) setJobs(result);
          })
        : api<Page<AuditRow>>(path, {signal: controller.signal}).then(result => {
            if (alive) setEvents(result);
          });
    void request.catch(problem => {
      if (alive) setError(failureMessage(problem));
    }).finally(() => {
      if (alive) setLoading(false);
    });
    return () => {alive = false; controller.abort();};
  }, [tab, query, accountId, status, offset, revision]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setOffset(0);
    setQuery(search.trim());
  }

  async function exportJob(jobId: string) {
    if (exporting) return;
    setExporting(jobId);
    setError("");
    try {
      await downloadFile(`/api/publication/jobs/${encodeURIComponent(jobId)}/export.xlsx`, `publicador_${jobId}.xlsx`);
    } catch (problem) {
      setError(failureMessage(problem));
    } finally {
      setExporting(null);
    }
  }

  const dataset = tab === "publications" ? publications : tab === "jobs" ? jobs : events;
  const total = dataset?.total ?? 0;
  const last = Math.min(total, offset + PAGE_SIZE);
  return <section className="managerPanel">
    <header className="managerHeader">
      <div>
        <h1>Gestor e historial</h1>
        <p>Consultá publicaciones creadas en el Publicador y los trabajos persistidos. La edición se habilitará únicamente mediante operaciones con vista previa y confirmación.</p>
      </div>
      <button type="button" className="secondary" onClick={() => setRevision(value => value + 1)} disabled={loading}>Actualizar</button>
    </header>
    <div className="managerTabs" role="tablist" aria-label="Tipo de historial">
      <button role="tab" type="button" aria-selected={tab === "publications"} className={tab === "publications" ? "active" : ""} onClick={() => {setTab("publications"); setOffset(0); setStatus("");}}>Publicaciones</button>
      <button role="tab" type="button" aria-selected={tab === "jobs"} className={tab === "jobs" ? "active" : ""} onClick={() => {setTab("jobs"); setOffset(0); setStatus("");}}>Trabajos</button>
      {canAudit && <button role="tab" type="button" aria-selected={tab === "audit"} className={tab === "audit" ? "active" : ""} onClick={() => {setTab("audit"); setOffset(0); setStatus("");}}>Auditoría</button>}
    </div>
    <form onSubmit={submitSearch} className="managerFilters">
      {tab === "publications" && <>
        <label>SKU, MLA o título
          <input value={search} maxLength={120} onChange={event => setSearch(event.target.value)} placeholder="Buscar publicación"/>
        </label>
        <label>Cuenta ML
          <select value={accountId} onChange={event => {setAccountId(event.target.value); setOffset(0);}}>
            <option value="">Todas las autorizadas</option>
            {accounts.map(account => <option key={account.id} value={account.id}>{account.nickname}</option>)}
          </select>
        </label>
      </>}
      <label>{tab === "audit" ? "Tipo de evento" : "Estado"}
        <input value={status} onChange={event => {setStatus(event.target.value.toUpperCase()); setOffset(0);}} maxLength={tab === "audit" ? 100 : 40} placeholder="Todos"/>
      </label>
      {tab === "publications" && <button type="submit" className="primary">Buscar</button>}
    </form>
    {error && <p className="managerError" role="alert">{error}</p>}
    <p className="managerCount" role="status">{loading ? "Consultando…" : `Mostrando ${total ? offset + 1 : 0}–${last} de ${total}`}</p>
    <div className="managerTableWrap">
      {tab === "publications" ? <table className="managerTable">
        <thead><tr><th>SKU</th><th>MLA</th><th>Título</th><th>Cuenta</th><th>Estado</th><th>Publicado</th></tr></thead>
        <tbody>{publications?.items.map(item => <tr key={item.publication_id}>
          <td>{item.sku}</td><td>{item.item_id || "Pendiente"}</td><td>{item.title}</td><td>{item.account_nickname}</td><td>{item.status}</td><td>{formattedDate(item.published_at)}</td>
        </tr>)}
          {!loading && publications?.items.length === 0 && <tr><td colSpan={6}>No se encontraron publicaciones para los filtros seleccionados.</td></tr>}
        </tbody>
      </table> : tab === "jobs" ? <table className="managerTable">
        <thead><tr><th>Job ID</th><th>Estado</th><th>Procesadas</th><th>Exitosas</th><th>Fallidas</th><th>Creado</th><th>Resultado</th></tr></thead>
        <tbody>{jobs?.items.map(job => <tr key={job.id}>
          <td><code title={job.id}>{job.id.slice(0, 8)}…</code></td>
          <td>{job.status}</td><td>{job.processed}/{job.total}</td><td>{job.succeeded}</td><td>{job.failed}</td><td>{formattedDate(job.created_at)}</td>
          <td><button type="button" className="secondary tiny" disabled={Boolean(exporting) || !["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"].includes(job.status)} onClick={() => {void exportJob(job.id);}}>Exportar XLSX</button></td>
        </tr>)}
          {!loading && jobs?.items.length === 0 && <tr><td colSpan={7}>No se encontraron trabajos para los filtros seleccionados.</td></tr>}
        </tbody>
      </table> : <table className="managerTable">
        <thead><tr><th>Fecha</th><th>Operador</th><th>Evento</th><th>Entidad</th><th>ID</th></tr></thead>
        <tbody>{events?.items.map(event => <tr key={event.id}>
          <td>{formattedDate(event.created_at)}</td><td>{event.actor_name || "Histórico / desconocido"}</td><td>{event.event_type}</td><td>{event.entity_type}</td><td><code>{event.entity_id}</code></td>
        </tr>)}
          {!loading && events?.items.length === 0 && <tr><td colSpan={5}>No se encontraron eventos.</td></tr>}
        </tbody>
      </table>}
    </div>
    <div className="managerPager">
      <button type="button" className="secondary" disabled={loading || offset === 0} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))}>Anterior</button>
      <button type="button" className="secondary" disabled={loading || offset + PAGE_SIZE >= total} onClick={() => setOffset(value => value + PAGE_SIZE)}>Siguiente</button>
    </div>
  </section>;
}

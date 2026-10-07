import {useEffect, useMemo, useState, type FormEvent} from "react";
import {api, downloadFile} from "./api";

type Account = {id: string; nickname: string};
type PublicationRow = {
  publication_id: string;
  item_id: string | null;
  user_product_id?: string | null;
  status: string;
  sku: string;
  product_id: string;
  title: string;
  account_id: string;
  account_nickname: string;
  internal_price?: number;
  b2b_sync?: {status?: string; detail?: string; [key: string]: unknown};
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
type UpdateChanges = {price?: number; available_quantity?: number; status?: string};
type UpdatePreview = {
  publication_id: string;
  item_id: string;
  expected: Record<string, unknown>;
  changes: {field: string; old: unknown; new: unknown}[];
  has_changes: boolean;
};
const PAGE_SIZE = 25;

function formattedDate(value: string | null): string {
  return value ? new Date(value).toLocaleString("es-AR") : "—";
}

function failureMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Error inesperado";
}

function buildChanges(price: string, stock: string, status: string): UpdateChanges {
  const changes: UpdateChanges = {};
  if (price.trim()) {
    const value = Number(price.replace(",", "."));
    if (!Number.isFinite(value) || value <= 0) throw new Error("El precio debe ser mayor a cero.");
    changes.price = value;
  }
  if (stock.trim()) {
    const value = Number(stock);
    if (!Number.isInteger(value) || value < 0) throw new Error("El stock debe ser un entero mayor o igual a cero.");
    changes.available_quantity = value;
  }
  if (status.trim()) changes.status = status.trim().toLowerCase();
  if (!Object.keys(changes).length) throw new Error("Indicá al menos un campo a modificar.");
  return changes;
}

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
  const [notice, setNotice] = useState("");
  const [exporting, setExporting] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [editing, setEditing] = useState<PublicationRow | null>(null);
  const [editPrice, setEditPrice] = useState("");
  const [editStock, setEditStock] = useState("");
  const [editStatus, setEditStatus] = useState("");
  const [preview, setPreview] = useState<UpdatePreview | null>(null);
  const [bulkPrice, setBulkPrice] = useState("");
  const [bulkStock, setBulkStock] = useState("");
  const [bulkStatus, setBulkStatus] = useState("");

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
          if (alive) {
            setPublications(result);
            setSelectedIds(current => current.filter(id => result.items.some(item => item.publication_id === id)));
          }
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

  function openEditor(item: PublicationRow) {
    setEditing(item);
    setEditPrice("");
    setEditStock("");
    setEditStatus("");
    setPreview(null);
    setError("");
    setNotice("");
  }

  async function previewUpdate() {
    if (!editing) return;
    const changes = buildChanges(editPrice, editStock, editStatus);
    const result = await api<UpdatePreview>(`/api/manager/publications/${editing.publication_id}/preview-update`, {
      method: "POST", body: JSON.stringify(changes),
    });
    setPreview(result);
    setNotice(result.has_changes ? "Vista previa lista. Confirmá para aplicar sobre Mercado Libre." : "No hay diferencias para aplicar.");
  }

  async function applyUpdate() {
    if (!editing || !preview) return;
    const changes = buildChanges(editPrice, editStock, editStatus);
    await api(`/api/manager/publications/${editing.publication_id}/apply-update`, {
      method: "POST", body: JSON.stringify({expected: preview.expected, changes}),
    });
    setNotice("Actualización aplicada y verificada en Mercado Libre.");
    setPreview(null);
    setEditing(null);
    setRevision(value => value + 1);
  }

  async function retryB2B(item: PublicationRow) {
    await api(`/api/publication/publications/${item.publication_id}/retry-b2b`, {method: "POST"});
    setNotice(`Mayoristas verificados para ${item.item_id || item.sku}.`);
    setRevision(value => value + 1);
  }

  async function bulkUpdate() {
    if (!selectedIds.length) throw new Error("Seleccioná al menos una publicación.");
    const changes = buildChanges(bulkPrice, bulkStock, bulkStatus);
    const selected = (publications?.items || []).filter(item => selectedIds.includes(item.publication_id));
    const previews = await Promise.all(selected.map(item =>
      api<UpdatePreview>(`/api/manager/publications/${item.publication_id}/preview-update`, {
        method: "POST", body: JSON.stringify(changes),
      })
    ));
    const actionable = previews.filter(item => item.has_changes);
    if (!actionable.length) {
      setNotice("Las publicaciones seleccionadas ya tienen esos valores.");
      return;
    }
    const summary = actionable.map(item => `${item.item_id}: ${item.changes.map(change => `${change.field} ${String(change.old)} → ${String(change.new)}`).join(", ")}`).join("\n");
    if (!window.confirm(`Se aplicarán ${actionable.length} actualizaciones verificadas:\n\n${summary}\n\n¿Confirmar?`)) return;
    const result = await api<any>("/api/manager/bulk/publications/update", {
      method: "POST",
      body: JSON.stringify({items: actionable.map(item => ({publication_id:item.publication_id, expected:item.expected, changes}))}),
    });
    setNotice(`Actualización masiva ${result.status}: ${result.succeeded}/${result.total} correctas, ${result.failed} fallidas.`);
    setRevision(value => value + 1);
  }

  const selectedAllVisible = useMemo(() => {
    const visible = publications?.items || [];
    return Boolean(visible.length) && visible.every(item => selectedIds.includes(item.publication_id));
  }, [publications, selectedIds]);

  async function run(action: () => Promise<void>) {
    setLoading(true); setError(""); setNotice("");
    try { await action(); } catch (problem) { setError(failureMessage(problem)); }
    finally { setLoading(false); }
  }

  const dataset = tab === "publications" ? publications : tab === "jobs" ? jobs : events;
  const total = dataset?.total ?? 0;
  const last = Math.min(total, offset + PAGE_SIZE);
  return <section className="managerPanel">
    <header className="managerHeader">
      <div>
        <h1>Gestor e historial</h1>
        <p>Buscá por SKU, MLA, variación/User Product ID o título. Las modificaciones usan vista previa, control de concurrencia y verificación posterior en Mercado Libre.</p>
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
        <label>SKU, MLA, variación o título
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
    {tab === "publications" && <div className="managerBulkPanel">
      <b>Actualización masiva ({selectedIds.length})</b>
      <input placeholder="Nuevo precio" inputMode="decimal" value={bulkPrice} onChange={event=>setBulkPrice(event.target.value)}/>
      <input placeholder="Nuevo stock" inputMode="numeric" value={bulkStock} onChange={event=>setBulkStock(event.target.value)}/>
      <select value={bulkStatus} onChange={event=>setBulkStatus(event.target.value)}><option value="">Estado sin cambio</option><option value="active">Activa</option><option value="paused">Pausada</option><option value="closed">Cerrada</option></select>
      <button type="button" disabled={loading || !selectedIds.length} onClick={()=>void run(bulkUpdate)}>Previsualizar y aplicar</button>
    </div>}
    {error && <p className="managerError" role="alert">{error}</p>}
    {notice && <p className="managerNotice" role="status">{notice}</p>}
    <p className="managerCount" role="status">{loading ? "Consultando…" : `Mostrando ${total ? offset + 1 : 0}–${last} de ${total}`}</p>
    <div className="managerTableWrap">
      {tab === "publications" ? <table className="managerTable">
        <thead><tr><th><input type="checkbox" checked={selectedAllVisible} onChange={()=>setSelectedIds(selectedAllVisible ? [] : (publications?.items || []).map(item=>item.publication_id))}/></th><th>SKU</th><th>MLA / Variación</th><th>Título</th><th>Cuenta</th><th>Estado</th><th>B2B</th><th>Publicado</th><th>Acciones</th></tr></thead>
        <tbody>{publications?.items.map(item => <tr key={item.publication_id}>
          <td><input type="checkbox" checked={selectedIds.includes(item.publication_id)} onChange={()=>setSelectedIds(current=>current.includes(item.publication_id) ? current.filter(id=>id!==item.publication_id) : [...current,item.publication_id])}/></td>
          <td>{item.sku}</td><td>{item.item_id || "Pendiente"}<small className="managerSubId">{item.user_product_id || ""}</small></td><td>{item.title}</td><td>{item.account_nickname}</td><td>{item.status}</td><td><span className={`pill ${String(item.b2b_sync?.status || "SIN_CONFIGURAR").toLowerCase()}`}>{item.b2b_sync?.status || "SIN_CONFIGURAR"}</span></td><td>{formattedDate(item.published_at)}</td>
          <td className="rowActions"><button type="button" className="secondary tiny" disabled={!item.item_id} onClick={()=>openEditor(item)}>Editar</button>{item.item_id && item.b2b_sync?.status && !["SIN_CONFIGURAR","PUBLISHED"].includes(String(item.b2b_sync.status)) && <button type="button" className="secondary tiny" onClick={()=>void run(()=>retryB2B(item))}>Reintentar mayorista</button>}</td>
        </tr>)}
          {!loading && publications?.items.length === 0 && <tr><td colSpan={9}>No se encontraron publicaciones para los filtros seleccionados.</td></tr>}
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
    {editing && <div className="managerEditPanel">
      <div className="managerEditHeader"><div><b>Actualizar {editing.item_id}</b><small>{editing.account_nickname} · {editing.title}</small></div><button type="button" className="secondary tiny" onClick={()=>{setEditing(null);setPreview(null);}}>Cerrar</button></div>
      <div className="managerEditFields"><label>Precio<input value={editPrice} onChange={event=>{setEditPrice(event.target.value);setPreview(null);}} placeholder="Sin cambio"/></label><label>Stock<input value={editStock} onChange={event=>{setEditStock(event.target.value);setPreview(null);}} placeholder="Sin cambio"/></label><label>Estado<select value={editStatus} onChange={event=>{setEditStatus(event.target.value);setPreview(null);}}><option value="">Sin cambio</option><option value="active">Activa</option><option value="paused">Pausada</option><option value="closed">Cerrada</option></select></label></div>
      <div className="rowActions"><button type="button" className="secondary" disabled={loading} onClick={()=>void run(previewUpdate)}>Generar vista previa</button>{preview?.has_changes && <button type="button" disabled={loading} onClick={()=>void run(applyUpdate)}>Confirmar actualización</button>}</div>
      {preview && <div className="managerDiffs">{preview.changes.length ? preview.changes.map(change=><div key={change.field}><b>{change.field}</b><span>{String(change.old ?? "—")} → {String(change.new ?? "—")}</span></div>) : <span>Sin cambios.</span>}</div>}
    </div>}
    <div className="managerPager">
      <button type="button" className="secondary" disabled={loading || offset === 0} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))}>Anterior</button>
      <button type="button" className="secondary" disabled={loading || offset + PAGE_SIZE >= total} onClick={() => setOffset(value => value + PAGE_SIZE)}>Siguiente</button>
    </div>
  </section>;
}

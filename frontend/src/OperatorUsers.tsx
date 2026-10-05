import {useCallback, useEffect, useState, type FormEvent} from "react";
import {api} from "./api";

export type OperatorRole = "ADMIN" | "SUPERVISOR" | "OPERATOR";
export type OperatorIdentity = {id: string; username: string; display_name: string; role: OperatorRole};
type ManagedUser = OperatorIdentity & {active: boolean; created_at: string};
type MlAccount = {id: string; nickname: string; active: boolean};
type AccountGrants = {user_id: string; account_ids: string[]};
const ROLE_LABELS: Record<OperatorRole, string> = {ADMIN: "Administrador", SUPERVISOR: "Supervisor", OPERATOR: "Operador"};
const EMPTY_CREATE = {username: "", display_name: "", password: "", role: "OPERATOR" as OperatorRole};

function message(error: unknown): string {
  return error instanceof Error ? error.message : "Ocurrió un error inesperado";
}

export function OperatorUsers({actor, onBack}: {actor: OperatorIdentity; onBack: () => void}) {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [create, setCreate] = useState(EMPTY_CREATE);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editRole, setEditRole] = useState<OperatorRole>("OPERATOR");
  const [editActive, setEditActive] = useState(true);
  const [editPassword, setEditPassword] = useState("");
  const [accounts, setAccounts] = useState<MlAccount[]>([]);
  const [grantedAccounts, setGrantedAccounts] = useState<string[]>([]);
  const [grantsLoading, setGrantsLoading] = useState(false);
  const [grantError, setGrantError] = useState("");
  const selected = users.find(user => user.id === selectedId) ?? null;
  const permittedRoles: OperatorRole[] = actor.role === "ADMIN" ? ["OPERATOR", "SUPERVISOR", "ADMIN"] : ["OPERATOR", "SUPERVISOR"];

  const refresh = useCallback(async () => {
    setError("");
    try {
      setUsers(await api<ManagedUser[]>("/api/operator-users"));
    } catch (failure) {
      setError(message(failure));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {void refresh();}, [refresh]);
  useEffect(() => {
    void api<MlAccount[]>("/api/operator-account-grants/accounts")
      .then(setAccounts)
      .catch(failure => setGrantError(message(failure)));
  }, []);
  useEffect(() => {
    if (!selectedId) {setGrantedAccounts([]); return;}
    let cancelled = false;
    setGrantsLoading(true);
    setGrantError("");
    void api<AccountGrants>(`/api/operator-account-grants/${encodeURIComponent(selectedId)}`)
      .then(data => {if (!cancelled) setGrantedAccounts(data.account_ids);})
      .catch(failure => {if (!cancelled) setGrantError(message(failure));})
      .finally(() => {if (!cancelled) setGrantsLoading(false);});
    return () => {cancelled = true;};
  }, [selectedId]);

  function select(user: ManagedUser) {
    setSelectedId(user.id);
    setEditName(user.display_name);
    setEditRole(user.role);
    setEditActive(user.active);
    setEditPassword("");
    setError("");
    setNotice("");
  }

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    setError("");
    setNotice("");
    setSaving(true);
    try {
      const created = await api<ManagedUser>("/api/operator-users", {method: "POST", body: JSON.stringify(create)});
      setCreate(EMPTY_CREATE);
      setNotice(`Usuario «${created.username}» creado correctamente.`);
      await refresh();
    } catch (failure) {
      setError(message(failure));
    } finally {
      setSaving(false);
    }
  }

  async function updateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || saving) return;
    const changes: {display_name?: string; role?: OperatorRole; active?: boolean; password?: string} = {};
    const name = editName.trim();
    if (!name) {setError("El nombre para mostrar no puede estar vacío."); return;}
    if (name !== selected.display_name) changes.display_name = name;
    if (editRole !== selected.role) changes.role = editRole;
    if (editActive !== selected.active) changes.active = editActive;
    if (editPassword) {
      if (editPassword.length < 12) {setError("La contraseña debe tener al menos 12 caracteres."); return;}
      changes.password = editPassword;
    }
    if (Object.keys(changes).length === 0) {setNotice("No hay cambios para guardar."); return;}
    if ((changes.active === false || changes.role || changes.password) &&
        !window.confirm(`¿Confirmás la modificación de «${selected.username}»? Los cambios de rol, contraseña o desactivación revocarán sus sesiones.`)) return;
    setError("");
    setNotice("");
    setSaving(true);
    try {
      const updated = await api<ManagedUser>(`/api/operator-users/${encodeURIComponent(selected.id)}`, {method: "PATCH", body: JSON.stringify(changes)});
      setEditPassword("");
      setNotice(`Usuario «${updated.username}» actualizado correctamente.`);
      await refresh();
    } catch (failure) {
      setError(message(failure));
    } finally {
      setSaving(false);
    }
  }

  async function saveAccountGrants(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || saving || grantsLoading) return;
    if (!window.confirm(`¿Guardar la asignación de cuentas de «${selected.username}»?`)) return;
    setSaving(true);
    setGrantError("");
    setNotice("");
    try {
      const result = await api<AccountGrants>(`/api/operator-account-grants/${encodeURIComponent(selected.id)}`, {
        method: "PUT", body: JSON.stringify({account_ids: grantedAccounts}),
      });
      setGrantedAccounts(result.account_ids);
      setNotice(`Asignación de cuentas de «${selected.username}» guardada.`);
    } catch (failure) {
      setGrantError(message(failure));
    } finally {
      setSaving(false);
    }
  }

  return <main className="operatorAdminPage">
    <header className="operatorAdminHeader">
      <div><span className="operatorAdminEyebrow">Administración interna</span><h1>Usuarios y permisos</h1><p>Gestioná las identidades del equipo. Las autorizaciones comerciales se validan desde el backend.</p></div>
      <button className="secondary" type="button" onClick={onBack}>Volver al Publicador</button>
    </header>
    {error && <div className="operatorAdminFeedback operatorAdminError" role="alert">{error}</div>}
    {notice && <div className="operatorAdminFeedback operatorAdminSuccess" role="status">{notice}</div>}
    <div className="operatorAdminGrid">
      <section className="operatorAdminPanel">
        <div className="operatorAdminPanelTitle"><h2>Personal</h2><button className="secondary tiny" type="button" onClick={() => void refresh()} disabled={loading || saving}>Actualizar</button></div>
        {loading ? <p>Cargando usuarios…</p> : <div className="operatorAdminUserList">
          {users.map(user => <button key={user.id} type="button" className={`operatorAdminUser ${selectedId === user.id ? "selected" : ""}`} disabled={saving} onClick={() => select(user)}>
            <span><strong>{user.display_name}</strong><small>@{user.username} · {ROLE_LABELS[user.role]}</small></span>
            <span className={`operatorAdminStatus ${user.active ? "active" : "inactive"}`}>{user.active ? "Activo" : "Inactivo"}</span>
          </button>)}
          {users.length === 0 && <p>No hay usuarios para mostrar.</p>}
        </div>}
      </section>
      <div className="operatorAdminForms">
        <section className="operatorAdminPanel">
          <h2>Crear usuario</h2>
          <form className="operatorAdminForm" onSubmit={createUser}>
            <label>Usuario<input required minLength={3} maxLength={120} autoComplete="off" value={create.username} onChange={event => setCreate({...create, username: event.target.value})} placeholder="nombre.apellido"/></label>
            <label>Nombre para mostrar<input required maxLength={160} value={create.display_name} onChange={event => setCreate({...create, display_name: event.target.value})}/></label>
            <label>Rol<select value={create.role} onChange={event => setCreate({...create, role: event.target.value as OperatorRole})}>{permittedRoles.map(role => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}</select></label>
            <label>Contraseña inicial<input required minLength={12} maxLength={1024} type="password" autoComplete="new-password" value={create.password} onChange={event => setCreate({...create, password: event.target.value})}/><small>Mínimo 12 caracteres. No compartas contraseñas por mensajería.</small></label>
            <button disabled={saving} type="submit">{saving ? "Guardando…" : "Crear usuario"}</button>
          </form>
        </section>
        {selected && <section className="operatorAdminPanel">
          <h2>Editar: @{selected.username}</h2>
          <form className="operatorAdminForm" onSubmit={updateUser}>
            <label>Nombre para mostrar<input required maxLength={160} value={editName} onChange={event => setEditName(event.target.value)}/></label>
            <label>Rol<select value={editRole} disabled={selected.id === actor.id} onChange={event => setEditRole(event.target.value as OperatorRole)}>{permittedRoles.map(role => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}</select></label>
            <label className="operatorAdminCheck"><input type="checkbox" disabled={selected.id === actor.id} checked={editActive} onChange={event => setEditActive(event.target.checked)}/> Usuario activo</label>
            <label>Reemplazar contraseña (opcional)<input type="password" minLength={12} maxLength={1024} autoComplete="new-password" value={editPassword} onChange={event => setEditPassword(event.target.value)} placeholder="Dejar vacío para conservarla"/></label>
            <small>Un cambio de contraseña o rol, o una desactivación, revoca las sesiones del usuario.</small>
            <button disabled={saving} type="submit">{saving ? "Guardando…" : "Guardar cambios"}</button>
          </form>
        </section>}
        {selected && <section className="operatorAdminPanel">
          <h2>Cuentas Mercado Libre · @{selected.username}</h2>
          <p>Prepará las asignaciones del usuario. Hasta activar los controles de alcance en todas las rutas comerciales, esto no limita todavía el acceso a esas cuentas.</p>
          {grantError && <div className="operatorAdminFeedback operatorAdminError" role="alert">{grantError}</div>}
          <form className="operatorAdminForm" onSubmit={saveAccountGrants}>
            {grantsLoading ? <p>Cargando asignaciones…</p> : accounts.map(account => <label key={account.id} className="operatorAdminCheck">
              <input type="checkbox" checked={grantedAccounts.includes(account.id)} disabled={saving || grantsLoading}
                onChange={event => setGrantedAccounts(current => event.target.checked ? [...current, account.id] : current.filter(id => id !== account.id))}/>
              {account.nickname}{account.active ? "" : " (inactiva)"}
            </label>)}
            {accounts.length === 0 && !grantsLoading && <small>No hay cuentas Mercado Libre conectadas.</small>}
            <button type="submit" disabled={saving || grantsLoading}>{saving ? "Guardando…" : "Guardar asignaciones"}</button>
          </form>
        </section>}
      </div>
    </div>
    <p className="operatorAdminScope">Las asignaciones se pueden guardar, pero todavía no restringen las operaciones comerciales. Los controles efectivos por cuenta y los bloqueos exclusivos de fichas se implementarán y validarán antes de habilitar operadores.</p>
  </main>;
}

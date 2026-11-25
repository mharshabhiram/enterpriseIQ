import { useApi } from "../api/hooks";
import type { Role, User, Visibility } from "../api/types";

export interface PermissionValue { visibility: Visibility; roles: Role[]; user_ids: string[] }

const ROLES: Role[] = ["MANAGER", "EMPLOYEE"];
const toggle = <T,>(list: T[], item: T) => (list.includes(item) ? list.filter((x) => x !== item) : [...list, item]);

export function PermissionsEditor({ value, onChange }: { value: PermissionValue; onChange: (v: PermissionValue) => void }) {
  const { data: users } = useApi<User[]>(value.visibility === "RESTRICTED" ? "/api/users/directory" : null);
  return (
    <div className="stack">
      <div>
        <label htmlFor="visibility">Who can read this document?</label>
        <select id="visibility" value={value.visibility} onChange={(e) => onChange({ ...value, visibility: e.target.value as Visibility })}>
          <option value="PUBLIC">Everyone in the organisation</option>
          <option value="RESTRICTED">Only selected roles and people</option>
        </select>
      </div>
      {value.visibility === "RESTRICTED" && (
        <>
          <div>
            <label>Roles</label>
            <div className="row">
              {ROLES.map((r) => (
                <label key={r} className="check">
                  <input type="checkbox" checked={value.roles.includes(r)} onChange={() => onChange({ ...value, roles: toggle(value.roles, r) })} />{r}
                </label>
              ))}
            </div>
            <p className="muted mono">Admins and the uploader always have access.</p>
          </div>
          <div>
            <label>People</label>
            <div className="stack scroll-list">
              {users?.map((u) => (
                <label key={u.id} className="check">
                  <input type="checkbox" checked={value.user_ids.includes(u.id)} onChange={() => onChange({ ...value, user_ids: toggle(value.user_ids, u.id) })} />
                  {u.name} <span className="mono muted">{u.role}</span>
                </label>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

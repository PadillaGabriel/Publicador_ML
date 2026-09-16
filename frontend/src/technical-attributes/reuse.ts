import type {TechnicalAttributeRecord} from "./types";

function hasValue(value: unknown): boolean {
  if (value === undefined || value === null) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    return Boolean(
      String(record.value_id ?? "").trim()
      || String(record.value_name ?? "").trim()
      || String(record.name ?? "").trim()
      || (record.value_struct && typeof record.value_struct === "object")
    );
  }
  return String(value).trim().length > 0;
}

export function applyReusableAttributes(
  current: Record<string, unknown>,
  reusable: TechnicalAttributeRecord[],
): {attributes: Record<string, unknown>; appliedIds: string[]} {
  const attributes = {...current};
  const appliedIds: string[] = [];

  for (const item of reusable) {
    const id = String(item.attribute_id || "").trim();
    if (!id || hasValue(attributes[id]) || item.value === undefined || item.value === null) {
      continue;
    }
    attributes[id] = item.value;
    appliedIds.push(id);
  }

  return {attributes, appliedIds};
}

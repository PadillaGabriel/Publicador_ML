import type {MlaPublicationSnapshot, TechnicalAttributeRecord} from "./types";

function valueText(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string" || typeof value === "number") return String(value).trim();
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    return String(record.value_name ?? record.name ?? record.value_id ?? "").trim();
  }
  return "";
}

function attributeText(records: TechnicalAttributeRecord[], attributeId: string): string {
  const record = records.find(item => String(item.attribute_id || "").toUpperCase() === attributeId);
  return record ? valueText(record.value) : "";
}

export function buildImportedProductSeed(snapshot: MlaPublicationSnapshot) {
  const title = String(snapshot.title || "").trim();
  return {
    sku: String(snapshot.seller_sku || "").trim(),
    name: title,
    title,
    description: String(snapshot.description || "").trim(),
    brand: attributeText(snapshot.attributes, "BRAND"),
    model: attributeText(snapshot.attributes, "MODEL"),
    categoryId: String(snapshot.category_id || "").trim(),
  };
}

export function recordsToAttributeMap(records: TechnicalAttributeRecord[]): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const record of records) {
    const id = String(record.attribute_id || "").trim().toUpperCase();
    if (id && record.value !== undefined && record.value !== null) result[id] = record.value;
  }
  return result;
}

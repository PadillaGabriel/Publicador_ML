export type TechnicalAttributeRecord = {
  attribute_id: string;
  label: string;
  value: unknown;
  source_category_id?: string | null;
  source_kind?: "MLA_IMPORT" | "PRODUCT_VERSION" | string | null;
  source_reference?: string | null;
  status: string;
};

export type ImportTechnicalAttributesResult = {
  item_id: string;
  category_id?: string | null;
  imported_count: number;
  skipped_count: number;
  imported: TechnicalAttributeRecord[];
  skipped: TechnicalAttributeRecord[];
};

export type ReuseTechnicalAttributesResult = {
  product_id: string;
  category_id: string;
  reusable: TechnicalAttributeRecord[];
  pending: TechnicalAttributeRecord[];
  incompatible: TechnicalAttributeRecord[];
};

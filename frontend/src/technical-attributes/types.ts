export type TechnicalAttributeRecord = {
  attribute_id: string;
  label: string;
  value: unknown;
  source_category_id?: string | null;
  source_kind?: "MLA_IMPORT" | "PRODUCT_VERSION" | string | null;
  source_reference?: string | null;
  status: string;
};

export type ReuseTechnicalAttributesResult = {
  product_id: string;
  category_id: string;
  reusable: TechnicalAttributeRecord[];
  pending: TechnicalAttributeRecord[];
  incompatible: TechnicalAttributeRecord[];
};


export type MlaPublicationSnapshot = {
  item_id: string;
  title: string;
  category_id?: string | null;
  condition?: string | null;
  seller_sku?: string | null;
  attributes: TechnicalAttributeRecord[];
  skipped: TechnicalAttributeRecord[];
};

export type MlaReusePreviewResult = {
  item_id: string;
  category_id: string;
  reusable: TechnicalAttributeRecord[];
  pending: TechnicalAttributeRecord[];
  incompatible: TechnicalAttributeRecord[];
};

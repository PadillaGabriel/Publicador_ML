import {buildImportedProductSeed, recordsToAttributeMap} from "./publication-import";

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(message);
}

const snapshot = {
  item_id: "MLA123",
  title: "Organizador transparente",
  category_id: "MLA1000",
  condition: "new",
  seller_sku: "SKU-123",
  description: "Descripción original del producto",
  attributes: [
    {attribute_id: "BRAND", label: "Marca", value: {value_name: "Silmar"}, status: "IMPORTADO"},
    {attribute_id: "MODEL", label: "Modelo", value: {value_name: "ORG-30"}, status: "IMPORTADO"},
  ],
  skipped: [],
};

const seed = buildImportedProductSeed(snapshot);
assert(seed.sku === "SKU-123", "seller SKU must seed the form");
assert(seed.title === snapshot.title, "MLA title must seed title");
assert(seed.name === snapshot.title, "MLA title must seed internal name");
assert(seed.brand === "Silmar", "BRAND must seed basic product data");
assert(seed.model === "ORG-30", "MODEL must seed basic product data");
assert(seed.categoryId === "MLA1000", "MLA category must seed the category");
assert(seed.description === snapshot.description, "MLA description must seed the description");

const attributes = recordsToAttributeMap(snapshot.attributes);
assert((attributes.BRAND as any).value_name === "Silmar", "technical attributes must become field values");

import {applyReusableAttributes} from "./reuse";

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(message);
}

const reusable = [
  {attribute_id: "BRAND", label: "Marca", value: {value_name: "Marca X"}, status: "REUTILIZABLE"},
  {attribute_id: "COLOR", label: "Color", value: {value_name: "Azul"}, status: "REUTILIZABLE"},
];

const merged = applyReusableAttributes({BRAND: "", COLOR: {value_name: "Rojo"}}, reusable);
assert((merged.attributes.BRAND as any).value_name === "Marca X", "empty field must be reused");
assert((merged.attributes.COLOR as any).value_name === "Rojo", "manual value must not be overwritten");
assert(merged.appliedIds.includes("BRAND"), "reused field must be marked");
assert(!merged.appliedIds.includes("COLOR"), "manual field must not be marked reused");

const nullable = applyReusableAttributes({BRAND: null}, reusable);
assert((nullable.attributes.BRAND as any).value_name === "Marca X", "null must be reusable");

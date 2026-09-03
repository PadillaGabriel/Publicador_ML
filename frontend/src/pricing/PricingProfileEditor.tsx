import type { PricingCostComponent, PricingProfile } from "./types";

type Props = {
  profile: PricingProfile;
  busy: boolean;
  onChange: (profile: PricingProfile) => void;
  onSave: () => void;
};

const BASES: { value: PricingCostComponent["basis"]; label: string }[] = [
  { value: "GROSS_SALE", label: "Venta bruta" }, { value: "NET_SALE_EX_VAT", label: "Venta neta sin IVA" },
  { value: "TAXABLE_REVENUE", label: "Ingreso imponible" }, { value: "PRODUCT_COST", label: "Costo del producto" },
  { value: "FIXED_PER_UNIT", label: "Fijo por unidad" }, { value: "FIXED_PER_ORDER", label: "Fijo por pedido" },
];

function numberOrZero(value: string) { return Number(value) || 0; }

export function PricingProfileEditor({ profile, busy, onChange, onSave }: Props) {
  const update = (patch: Partial<PricingProfile>) => onChange({ ...profile, ...patch });
  const updateComponent = (index: number, patch: Partial<PricingCostComponent>) => update({ components: profile.components.map((component, position) => position === index ? { ...component, ...patch } : component) });
  const addComponent = () => update({ components: [...profile.components, { name: "", kind: "PERCENTAGE_OF_PRICE", value: 0, basis: "GROSS_SALE", active: true }] });
  const removeComponent = (index: number) => update({ components: profile.components.filter((_, position) => position !== index) });

  return <>
    <header><div><h1>Costos y rentabilidad</h1><p>Configurá los valores globales del canal. Los ajustes cargados en una simulación sólo se aplican a ese cálculo.</p></div></header>
    <section className="card">
      <div className="sectionTitle"><span>1</span> Perfil económico del canal</div>
      <div className="grid3">
        <label>Nombre del perfil<input value={profile.name} onChange={event => update({ name: event.target.value })} /></label>
        <label>Margen objetivo %<input type="number" min="0" max="99" step="0.1" value={profile.target_margin_pct} onChange={event => update({ target_margin_pct: numberOrZero(event.target.value) })} /></label>
        <label>Margen mínimo %<input type="number" min="0" max="99" step="0.1" value={profile.minimum_margin_pct} onChange={event => update({ minimum_margin_pct: numberOrZero(event.target.value) })} /></label>
      </div>
      <div className="grid4">
        <label>IVA %<input type="number" min="0" max="99" step="0.01" value={profile.vat_rate_pct} onChange={event => update({ vat_rate_pct: numberOrZero(event.target.value) })} /></label>
        <label>IIBB %<input type="number" min="0" max="99" step="0.01" value={profile.iibb_rate_pct} onChange={event => update({ iibb_rate_pct: numberOrZero(event.target.value) })} /></label>
        <label>Publicidad %<input type="number" min="0" max="99" step="0.01" value={profile.ads_rate_pct} onChange={event => update({ ads_rate_pct: numberOrZero(event.target.value) })} /></label>
        <label>Reintegros %<input type="number" min="0" max="99" step="0.01" value={profile.refund_rate_pct} onChange={event => update({ refund_rate_pct: numberOrZero(event.target.value) })} /></label>
      </div>
      <div className="grid3">
        <label>Unidades proyectadas por mes<input type="number" min="1" value={profile.monthly_units_projection ?? ""} onChange={event => update({ monthly_units_projection: event.target.value ? Number(event.target.value) : null })} /><small>Requeridas para asignar costos fijos mensuales por unidad.</small></label>
        <label>Redondeo de precio sugerido<input type="number" min="0.01" step="0.01" value={profile.rounding_step} onChange={event => update({ rounding_step: numberOrZero(event.target.value) })} /></label>
        <label>Canal<input disabled value="Mercado Libre" /></label>
      </div>
    </section>
    <section className="card">
      <div className="toolbar pricingToolbar"><div><div className="sectionTitle"><span>2</span> Variables de costo</div><p className="helper blockHelper">Cada componente conserva explícitamente su base de cálculo.</p></div><button className="secondary" type="button" onClick={addComponent}>+ Agregar variable</button></div>
      {profile.components.length === 0 && <div className="optionalNotice">Todavía no configuraste componentes adicionales.</div>}
      <div className="pricingComponents">{profile.components.map((component, index) => <div className="pricingComponent" key={`${component.name}-${index}`}>
        <label>Concepto<input value={component.name} onChange={event => updateComponent(index, { name: event.target.value })} /></label>
        <label>Tipo<select value={component.kind} onChange={event => updateComponent(index, { kind: event.target.value as PricingCostComponent["kind"] })}><option value="PERCENTAGE_OF_PRICE">% sobre precio</option><option value="PERCENTAGE_OF_COST">% sobre costo</option><option value="FIXED_PER_UNIT">Fijo por unidad</option><option value="FIXED_PER_ORDER">Fijo por pedido</option><option value="FIXED_MONTHLY">Fijo mensual</option></select></label>
        <label>Base<select value={component.basis} onChange={event => updateComponent(index, { basis: event.target.value as PricingCostComponent["basis"] })}>{BASES.map(base => <option key={base.value} value={base.value}>{base.label}</option>)}</select></label>
        <label>{component.kind.startsWith("PERCENTAGE") ? "Porcentaje %" : "Importe ARS"}<input type="number" min="0" step="0.01" value={component.value} onChange={event => updateComponent(index, { value: numberOrZero(event.target.value) })} /></label>
        <label className="checkboxLabel pricingActive"><input type="checkbox" checked={component.active} onChange={event => updateComponent(index, { active: event.target.checked })} />Activo</label><button className="tiny dangerButton" type="button" onClick={() => removeComponent(index)}>Quitar</button>
      </div>)}</div>
      <button disabled={busy || !profile.name.trim()} type="button" onClick={onSave}>Guardar configuración económica</button>
    </section>
    <section className="card pricingMethod">
      <div className="sectionTitle"><span>3</span> Criterio del motor</div>
      <div className="pricingFormulaGrid"><div><b>Costo marginal operativo</b><span>Costos incrementales de vender una unidad adicional.</span></div><div><b>Margen de contribución</b><span>Contribución disponible para cubrir costos fijos y utilidad.</span></div><div><b>Precio de equilibrio</b><span>Precio donde la contribución llega a cero.</span></div><div><b>Precio objetivo</b><span>Precio necesario para alcanzar el margen solicitado.</span></div></div>
    </section>
  </>;
}

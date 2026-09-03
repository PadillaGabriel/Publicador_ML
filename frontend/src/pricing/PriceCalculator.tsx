import { useEffect, useState } from "react";
import { api } from "../api";
import { PricingBreakdown } from "./PricingBreakdown";
import { PricingTargets } from "./PricingTargets";
import { LOGISTIC_OPTIONS, normalizeCalculation, SHIPPING_MODE_OPTIONS, type PricingCalculation, type PricingCalculatorApiResponse } from "./types";

type AccountOption = { id: string; nickname: string };
type CategorySuggestion = { category_id: string; category_name: string; domain_name?: string };
type PublicationType = { listing_type_id: string; label: string };
type Props = { accountId?: string; accounts: readonly AccountOption[]; onLoadPublicationTypes: (accountId: string, categoryId: string) => Promise<PublicationType[]>; onSearchCategories: (accountId: string, query: string) => Promise<CategorySuggestion[]>; onUseRecommendedPrice: (price: number, calculation: PricingCalculation) => void };
type Mode = "existing" | "new";

const initialForm = { accountId: "", categoryId: "", categoryQuery: "", grossCmv: "", height: "", itemId: "", length: "", listingTypeId: "", logisticType: "", refundRatePct: "", shippingMode: "", sku: "", targetMarginPct: "", adsRatePct: "", iibbRatePct: "", weight: "", width: "" };
function optionalNumber(value: string) { return value.trim() ? Number(value) : undefined; }
function packageDimensions(form: typeof initialForm) { return form.height && form.width && form.length ? `${form.length}x${form.width}x${form.height}` : null; }

export function PriceCalculator({ accountId = "", accounts, onLoadPublicationTypes, onSearchCategories, onUseRecommendedPrice }: Props) {
  const [mode, setMode] = useState<Mode>("new");
  const [form, setForm] = useState({ ...initialForm, accountId });
  const [categories, setCategories] = useState<CategorySuggestion[]>([]);
  const [publicationTypes, setPublicationTypes] = useState<PublicationType[]>([]);
  const [result, setResult] = useState<PricingCalculation | null>(null);
  const [busy, setBusy] = useState(false);
  const [searchingCategories, setSearchingCategories] = useState(false);
  const [error, setError] = useState("");
  const update = (name: keyof typeof form, value: string) => setForm(current => ({ ...current, [name]: value }));

  useEffect(() => { setForm(current => current.accountId === accountId ? current : { ...current, accountId }); }, [accountId]);

  async function selectCategory(category: CategorySuggestion) {
    setError(""); update("categoryId", category.category_id); update("categoryQuery", category.category_name); update("listingTypeId", ""); setPublicationTypes([]);
    try { const options = await onLoadPublicationTypes(form.accountId, category.category_id); setPublicationTypes(options); if (options.length === 1) update("listingTypeId", options[0].listing_type_id); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "No fue posible cargar las modalidades disponibles."); }
  }

  async function searchCategories() {
    if (!form.accountId) { setError("Elegí una cuenta de Mercado Libre antes de buscar una categoría."); return; }
    if (!form.categoryQuery.trim()) { setError("Escribí qué producto querés publicar para buscar una categoría."); return; }
    setSearchingCategories(true); setError(""); setCategories([]); update("categoryId", ""); update("listingTypeId", ""); setPublicationTypes([]);
    try { setCategories(await onSearchCategories(form.accountId, form.categoryQuery.trim())); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "No fue posible buscar categorías."); }
    finally { setSearchingCategories(false); }
  }

  async function calculate() {
    setBusy(true); setError(""); setResult(null);
    try {
      const overrides = { ads_rate_pct: optionalNumber(form.adsRatePct), iibb_rate_pct: optionalNumber(form.iibbRatePct), refund_rate_pct: optionalNumber(form.refundRatePct) };
      const base = { account_id: form.accountId || null, sku: form.sku || null, gross_cmv: optionalNumber(form.grossCmv), target_margin_pct: optionalNumber(form.targetMarginPct), overrides };
      const payload = mode === "existing" ? { ...base, item_id: form.itemId || null } : { ...base, category_id: form.categoryId || null, listing_type_id: form.listingTypeId || null, package: { dimensions: packageDimensions(form), weight: optionalNumber(form.weight), logistic_type: form.logisticType || null, shipping_mode: form.shippingMode || null } };
      const response = await api<PricingCalculatorApiResponse>(mode === "existing" ? "/api/pricing/calculator/existing" : "/api/pricing/calculator/new", { method: "POST", body: JSON.stringify(payload) });
      setResult(normalizeCalculation(response));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No fue posible calcular el precio."); }
    finally { setBusy(false); }
  }

  return <>
    <header><div><h1>Calculadora de precio</h1><p>Estimá un precio con tus costos y las condiciones actuales de Mercado Libre. Esta herramienta no crea publicaciones.</p></div></header>
    <section className="card priceCalculator">
      <div className="pricingModeTabs" role="tablist" aria-label="Tipo de cálculo"><button type="button" role="tab" aria-selected={mode === "existing"} className={mode === "existing" ? "active" : ""} onClick={() => { setMode("existing"); setResult(null); }}>Publicación existente</button><button type="button" role="tab" aria-selected={mode === "new"} className={mode === "new" ? "active" : ""} onClick={() => { setMode("new"); setResult(null); }}>Producto nuevo</button></div>
      <p className="pricingScenario"><b>Escenario base: 1 unidad.</b> La simulación calcula el resultado para una unidad vendida.</p>
      <div className="pricingFormSection"><div><h2>Producto</h2><p>Elegí la cuenta y el producto que querés analizar.</p></div><div className="grid3"><label>Cuenta de Mercado Libre<select value={form.accountId} onChange={event => update("accountId", event.target.value)}><option value="">Elegí una cuenta</option>{accounts.map(account => <option key={account.id} value={account.id}>{account.nickname}</option>)}</select></label><label>SKU <span className="fieldOptional">opcional</span><input value={form.sku} onChange={event => update("sku", event.target.value)} placeholder="Tu código interno" /></label>{mode === "existing" && <label>Código de publicación<input value={form.itemId} onChange={event => update("itemId", event.target.value)} placeholder="Ej. MLA123456789" /><small>Ingresá el código de la publicación que ya existe.</small></label>}</div>
      {mode === "new" && <><label className="pricingSearchField">Categoría<input value={form.categoryQuery} onChange={event => update("categoryQuery", event.target.value)} placeholder="Ej. botella, frasco, mate" /><small>Buscá y seleccioná la categoría más adecuada para el producto.</small></label><button type="button" className="secondary pricingSearchButton" disabled={searchingCategories} onClick={searchCategories}>{searchingCategories ? "Buscando categorías…" : "Buscar categoría"}</button>{categories.length > 0 && <div className="pricingCategoryList" aria-label="Categorías sugeridas">{categories.map(category => <button key={category.category_id} type="button" className={form.categoryId === category.category_id ? "selected" : ""} onClick={() => selectCategory(category)}><b>{category.category_name}</b>{category.domain_name && <small>{category.domain_name}</small>}</button>)}</div>}<div className="grid3"><label>Tipo de publicación<select disabled={!publicationTypes.length} value={form.listingTypeId} onChange={event => update("listingTypeId", event.target.value)}><option value="">{publicationTypes.length ? "Elegí una modalidad" : "Elegí primero una categoría"}</option>{publicationTypes.map(option => <option key={option.listing_type_id} value={option.listing_type_id}>{option.label}</option>)}</select></label></div></>}</div>
      <div className="pricingFormSection"><div><h2>Costos y objetivo</h2><p>Los porcentajes son opcionales: si los dejás vacíos, se usan los valores guardados en la configuración.</p></div><div className="grid3"><label>Costo del producto (con IVA)<input type="number" min="0" step="0.01" value={form.grossCmv} onChange={event => update("grossCmv", event.target.value)} /><small>Ingresá el costo bruto de compra, incluyendo IVA.</small></label><label>Publicidad estimada (%)<input type="number" min="0" max="99" step="0.01" value={form.adsRatePct} onChange={event => update("adsRatePct", event.target.value)} /></label><label>Ingresos Brutos (%)<input type="number" min="0" max="99" step="0.01" value={form.iibbRatePct} onChange={event => update("iibbRatePct", event.target.value)} /></label></div><div className="grid2"><label>Reintegros estimados (%)<input type="number" min="0" max="99" step="0.01" value={form.refundRatePct} onChange={event => update("refundRatePct", event.target.value)} /></label><label>Margen objetivo personalizado (%)<input type="number" min="0" max="99" step="0.01" value={form.targetMarginPct} onChange={event => update("targetMarginPct", event.target.value)} /></label></div></div>
      {mode === "new" && <div className="pricingFormSection"><div><h2>Paquete de despacho</h2><p>Estas medidas deben corresponder al paquete real de envío, no sólo al producto.</p></div><div className="grid4"><label>Alto (cm)<input type="number" min="0" step="0.1" value={form.height} onChange={event => update("height", event.target.value)} /></label><label>Ancho (cm)<input type="number" min="0" step="0.1" value={form.width} onChange={event => update("width", event.target.value)} /></label><label>Largo (cm)<input type="number" min="0" step="0.1" value={form.length} onChange={event => update("length", event.target.value)} /></label><label>Peso (kg)<input type="number" min="0" step="0.01" value={form.weight} onChange={event => update("weight", event.target.value)} /></label></div><div className="grid2"><label>Tipo de logística<select value={form.logisticType} onChange={event => update("logisticType", event.target.value)}><option value="">Elegí una opción</option>{LOGISTIC_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label><label>Modo de envío<select value={form.shippingMode} onChange={event => update("shippingMode", event.target.value)}><option value="">Elegí una opción</option>{SHIPPING_MODE_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label></div></div>}
      <button type="button" className="pricingPrimaryButton" disabled={busy || !form.accountId || !form.grossCmv} onClick={calculate}>{busy ? "Calculando precio…" : "Calcular precio"}</button>{error && <div className="notice pricingError">{error}</div>}
    </section>
    {result && <><PricingBreakdown breakdown={result.analyzed} /><PricingTargets calculation={result} onUseRecommendedPrice={price => onUseRecommendedPrice(price, result)} /></>}
  </>;
}

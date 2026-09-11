import { useEffect, useState } from "react";
import { api, loadShippingCapabilities } from "../api";
import { PricingBreakdown } from "./PricingBreakdown";
import { PricingTargets } from "./PricingTargets";
import { normalizeCalculation, type PricingCalculation, type PricingCalculatorApiResponse, type PricingCalculatorPrefill, type ShippingCapabilities } from "./types";

type AccountOption = { id: string; nickname: string };
type CategorySuggestion = { category_id: string; category_name: string; domain_name?: string };
type PublicationType = { listing_type_id: string; label: string };
type Props = {
  accountId?: string;
  accounts: readonly AccountOption[];
  prefill?: PricingCalculatorPrefill | null;
  onLoadPublicationTypes: (accountId: string, categoryId: string) => Promise<PublicationType[]>;
  onSearchCategories: (accountId: string, query: string) => Promise<CategorySuggestion[]>;
  onUseRecommendedPrice: (price: number, calculation: PricingCalculation) => void;
};
type Mode = "existing" | "new";

const initialForm = {
  accountId: "",
  categoryId: "",
  categoryQuery: "",
  freeShipping: "",
  grossCmv: "",
  height: "",
  itemId: "",
  length: "",
  listingTypeId: "",
  logisticType: "",
  salePrice: "",
  shippingMode: "",
  weight: "",
  width: "",
};

function optionalNumber(value: string) {
  return value.trim() ? Number(value) : undefined;
}

function packageDimensions(form: typeof initialForm) {
  return form.height && form.width && form.length
    ? `${form.length}x${form.width}x${form.height}`
    : null;
}

function dimensionParts(dimensions: string) {
  const [length = "", width = "", height = ""] = dimensions
    .split("x")
    .map(value => value.trim());
  return { length, width, height };
}

export function PriceCalculator({
  accountId = "",
  accounts,
  prefill = null,
  onLoadPublicationTypes,
  onSearchCategories,
  onUseRecommendedPrice,
}: Props) {
  const [mode, setMode] = useState<Mode>("new");
  const [form, setForm] = useState({ ...initialForm, accountId });
  const [categories, setCategories] = useState<CategorySuggestion[]>([]);
  const [publicationTypes, setPublicationTypes] = useState<PublicationType[]>([]);
  const [result, setResult] = useState<PricingCalculation | null>(null);
  const [busy, setBusy] = useState(false);
  const [searchingCategories, setSearchingCategories] = useState(false);
  const [shippingCapabilities, setShippingCapabilities] = useState<ShippingCapabilities | null>(null);
  const [shippingCapabilitiesLoading, setShippingCapabilitiesLoading] = useState(false);
  const [shippingCapabilitiesError, setShippingCapabilitiesError] = useState("");
  const [error, setError] = useState("");

  const shippingReady = mode === "existing" || Boolean(
    shippingCapabilities
    && form.shippingMode === shippingCapabilities.mode
    && (
      form.logisticType === shippingCapabilities.base_logistic_type
      || (shippingCapabilities.flex_available && form.logisticType === shippingCapabilities.flex_logistic_type)
    )
    && form.freeShipping !== ""
  );

  const update = (name: keyof typeof form, value: string) => {
    setForm(current => ({ ...current, [name]: value }));
    setResult(null);
  };

  useEffect(() => {
    setForm(current => current.accountId === accountId ? current : { ...current, accountId });
  }, [accountId]);

  useEffect(() => {
    let cancelled = false;
    if (mode !== "new" || !form.accountId || !form.categoryId) {
      setShippingCapabilities(null);
      setShippingCapabilitiesError("");
      setShippingCapabilitiesLoading(false);
      return () => { cancelled = true; };
    }

    setShippingCapabilitiesLoading(true);
    setShippingCapabilitiesError("");
    loadShippingCapabilities(form.accountId, form.categoryId)
      .then(capabilities => {
        if (cancelled) return;
        setShippingCapabilities(capabilities);
        setForm(current => {
          const keepFlex = current.logisticType === capabilities.flex_logistic_type && capabilities.flex_available;
          return {
            ...current,
            shippingMode: capabilities.mode,
            logisticType: keepFlex ? capabilities.flex_logistic_type : capabilities.base_logistic_type,
          };
        });
      })
      .catch(reason => {
        if (cancelled) return;
        setShippingCapabilities(null);
        setShippingCapabilitiesError(
          reason instanceof Error ? reason.message : "No fue posible resolver Mercado Envíos."
        );
      })
      .finally(() => { if (!cancelled) setShippingCapabilitiesLoading(false); });

    return () => { cancelled = true; };
  }, [mode, form.accountId, form.categoryId]);

  useEffect(() => {
    if (!prefill) return;
    const dimensions = dimensionParts(prefill.dimensions);
    setMode("new");
    setResult(null);
    setError("");
    setCategories([]);
    setForm(current => ({
      ...current,
      accountId: prefill.accountId,
      categoryId: prefill.categoryId,
      categoryQuery: prefill.categoryLabel || prefill.categoryId,
      listingTypeId: prefill.listingTypeId,
      grossCmv: prefill.grossCmv,
      salePrice: prefill.salePrice,
      length: dimensions.length,
      width: dimensions.width,
      height: dimensions.height,
      weight: prefill.weight,
      logisticType: prefill.logisticType,
      shippingMode: prefill.shippingMode,
      freeShipping: prefill.freeShipping,
    }));

    if (!prefill.accountId || !prefill.categoryId) {
      setPublicationTypes([]);
      return;
    }

    let cancelled = false;
    onLoadPublicationTypes(prefill.accountId, prefill.categoryId)
      .then(options => { if (!cancelled) setPublicationTypes(options); })
      .catch(reason => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "No fue posible cargar las modalidades disponibles.");
        }
      });
    return () => { cancelled = true; };
  }, [prefill?.requestId]);

  async function selectCategory(category: CategorySuggestion) {
    setError("");
    update("categoryId", category.category_id);
    update("categoryQuery", category.category_name);
    update("listingTypeId", "");
    setPublicationTypes([]);
    try {
      const options = await onLoadPublicationTypes(form.accountId, category.category_id);
      setPublicationTypes(options);
      if (options.length === 1) update("listingTypeId", options[0].listing_type_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible cargar las modalidades disponibles.");
    }
  }

  async function searchCategories() {
    if (!form.accountId) {
      setError("Elegí una cuenta de Mercado Libre antes de buscar una categoría.");
      return;
    }
    if (!form.categoryQuery.trim()) {
      setError("Escribí qué producto querés publicar para buscar una categoría.");
      return;
    }

    setSearchingCategories(true);
    setError("");
    setCategories([]);
    update("categoryId", "");
    update("listingTypeId", "");
    setPublicationTypes([]);
    try {
      setCategories(await onSearchCategories(form.accountId, form.categoryQuery.trim()));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible buscar categorías.");
    } finally {
      setSearchingCategories(false);
    }
  }

  async function calculate() {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const base = {
        account_id: form.accountId || null,
        gross_cmv: optionalNumber(form.grossCmv),
      };
      const payload = mode === "existing"
        ? { ...base, item_id: form.itemId || null }
        : {
          ...base,
          sale_price: optionalNumber(form.salePrice),
          category_id: form.categoryId || null,
          listing_type_id: form.listingTypeId || null,
          package: {
            dimensions: packageDimensions(form),
            weight: optionalNumber(form.weight),
            logistic_type: form.logisticType || null,
            shipping_mode: form.shippingMode || null,
            free_shipping: form.freeShipping === "" ? null : form.freeShipping === "true",
          },
        };
      const response = await api<PricingCalculatorApiResponse>(
        mode === "existing" ? "/api/pricing/calculator/existing" : "/api/pricing/calculator/new",
        { method: "POST", body: JSON.stringify(payload) }
      );
      setResult(normalizeCalculation(response));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible calcular el precio.");
    } finally {
      setBusy(false);
    }
  }

  const showCurrentPrice = mode === "existing" || Boolean(form.salePrice.trim());

  return <>
    <header>
      <div>
        <h1>Calculadora de precio</h1>
        <p>Ingresá el costo del producto. La configuración económica y los costos de Mercado Libre se aplican automáticamente.</p>
      </div>
    </header>

    <section className="card priceCalculator">
      <div className="pricingModeTabs" role="tablist" aria-label="Tipo de cálculo">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "existing"}
          className={mode === "existing" ? "active" : ""}
          onClick={() => { setMode("existing"); setResult(null); setError(""); }}
        >Publicación existente</button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "new"}
          className={mode === "new" ? "active" : ""}
          onClick={() => { setMode("new"); setResult(null); setError(""); }}
        >Producto nuevo</button>
      </div>

      <div className="pricingConfigurationNotice">
        <div>
          <b>La política económica viene de Configuración</b>
          <span>Margen objetivo, margen mínimo, IVA, IIBB, publicidad, reintegros, redondeo y costos adicionales se aplican sin volver a pedirlos acá.</span>
        </div>
      </div>

      <div className="pricingFormSection pricingContextSection">
        <div>
          <h2>Contexto del producto</h2>
          <p>Mercado Libre necesita este contexto para resolver comisión, cargos y logística. No son parámetros económicos manuales.</p>
        </div>
        <div className="grid2">
          <label>Cuenta de Mercado Libre
            <select value={form.accountId} onChange={event => update("accountId", event.target.value)}>
              <option value="">Elegí una cuenta</option>
              {accounts.map(account => <option key={account.id} value={account.id}>{account.nickname}</option>)}
            </select>
          </label>
          {mode === "existing" && <label>Código de publicación
            <input value={form.itemId} onChange={event => update("itemId", event.target.value)} placeholder="Ej. MLA123456789" />
            <small>La categoría, modalidad, precio actual y logística se recuperan desde Mercado Libre.</small>
          </label>}
        </div>

        {mode === "new" && <>
          <div className="pricingCategorySearch">
            <label className="pricingSearchField">Categoría
              <input value={form.categoryQuery} onChange={event => update("categoryQuery", event.target.value)} placeholder="Ej. botella, frasco, mate" />
              <small>La categoría determina parte de los costos variables de Mercado Libre.</small>
            </label>
            <button type="button" className="secondary pricingSearchButton" disabled={searchingCategories} onClick={searchCategories}>
              {searchingCategories ? "Buscando…" : "Buscar categoría"}
            </button>
          </div>
          {categories.length > 0 && <div className="pricingCategoryList" aria-label="Categorías sugeridas">
            {categories.map(category => <button
              key={category.category_id}
              type="button"
              className={form.categoryId === category.category_id ? "selected" : ""}
              onClick={() => selectCategory(category)}
            >
              <b>{category.category_name}</b>
              {category.domain_name && <small>{category.domain_name}</small>}
            </button>)}
          </div>}
          <div className="grid2">
            <label>Tipo de publicación
              <select disabled={!publicationTypes.length} value={form.listingTypeId} onChange={event => update("listingTypeId", event.target.value)}>
                <option value="">{publicationTypes.length ? "Elegí una modalidad" : "Elegí primero una categoría"}</option>
                {publicationTypes.map(option => <option key={option.listing_type_id} value={option.listing_type_id}>{option.label}</option>)}
              </select>
            </label>
          </div>
        </>}
      </div>

      <div className="pricingFormSection pricingCostSection">
        <div>
          <h2>Costo del producto</h2>
          <p>Este es el único dato económico que necesitás ingresar para obtener las propuestas.</p>
        </div>
        <div className="pricingCostInputRow">
          <label>Costo de compra con IVA
            <input type="number" min="0" step="0.01" value={form.grossCmv} onChange={event => update("grossCmv", event.target.value)} placeholder="0,00" />
          </label>
          {mode === "new" && <label>Precio que querés analizar <span className="fieldOptional">opcional</span>
            <input type="number" min="0.01" step="0.01" value={form.salePrice} onChange={event => update("salePrice", event.target.value)} placeholder="Si ya tenés un precio" />
            <small>Si lo dejás vacío, calculamos directamente las propuestas de margen.</small>
          </label>}
        </div>
      </div>

      {mode === "new" && <div className="pricingFormSection pricingShippingContext">
        <div>
          <h2>Datos de envío</h2>
          <p>Se usan para consultar el costo logístico real. Si venís desde el Publicador, estos datos se completan automáticamente.</p>
        </div>
        <div className="grid4">
          <label>Alto (cm)<input type="number" min="0" step="0.1" value={form.height} onChange={event => update("height", event.target.value)} /></label>
          <label>Ancho (cm)<input type="number" min="0" step="0.1" value={form.width} onChange={event => update("width", event.target.value)} /></label>
          <label>Largo (cm)<input type="number" min="0" step="0.1" value={form.length} onChange={event => update("length", event.target.value)} /></label>
          <label>Peso del paquete (kg)<input type="number" min="0.01" step="0.01" value={form.weight} onChange={event => update("weight", event.target.value)} /></label>
        </div>
        <div className="shippingPanel">
          <div className="shippingPanelHeader">
            <div>
              <span className="shippingEyebrow">Envío</span>
              <b>Mercado Envíos</b>
              <small>La modalidad técnica se resuelve automáticamente con tu cuenta y la categoría.</small>
            </div>
            <span className={`shippingStatus ${shippingCapabilities ? "ready" : "pending"}`}>
              {shippingCapabilitiesLoading ? "Consultando…" : shippingCapabilities ? "Activo" : "Pendiente"}
            </span>
          </div>
          {shippingCapabilitiesError && <div className="shippingCapabilityError">{shippingCapabilitiesError}</div>}
          {shippingCapabilities && <div className="shippingDecisionGrid">
            <div className="shippingDecision">
              <span>¿Ofrecer Mercado Envíos Flex?</span>
              <div className="segmentedChoice" role="group" aria-label="Ofrecer Mercado Envíos Flex">
                <button type="button" className={form.logisticType !== shippingCapabilities.flex_logistic_type ? "active" : ""} onClick={() => {
                  update("shippingMode", shippingCapabilities.mode);
                  update("logisticType", shippingCapabilities.base_logistic_type);
                }}>No</button>
                <button type="button" disabled={!shippingCapabilities.flex_available} className={form.logisticType === shippingCapabilities.flex_logistic_type ? "active" : ""} onClick={() => {
                  update("shippingMode", shippingCapabilities.mode);
                  update("logisticType", shippingCapabilities.flex_logistic_type);
                }}>Sí</button>
              </div>
              <small>{shippingCapabilities.flex_available ? "Flex está habilitado para esta cuenta y categoría." : "Mercado Libre no habilita Flex para este contexto."}</small>
            </div>
            <label>Quién paga el envío
              <select value={form.freeShipping} onChange={event => update("freeShipping", event.target.value)}>
                <option value="">Elegí una opción</option>
                <option value="false">El comprador paga el envío</option>
                <option value="true">Ofrecer envío gratis</option>
              </select>
            </label>
          </div>}
        </div>
      </div>}

      <div className="pricingCalculateBar">
        <div>
          <b>Listo para calcular</b>
          <span>Las propuestas usan tu configuración guardada y los costos actuales de Mercado Libre.</span>
        </div>
        <button
          type="button"
          className="pricingPrimaryButton"
          disabled={busy || !form.accountId || !form.grossCmv || (mode === "existing" ? !form.itemId : (!form.categoryId || !form.listingTypeId || !shippingReady || !packageDimensions(form) || !form.weight))}
          onClick={calculate}
        >{busy ? "Calculando…" : "Calcular propuestas"}</button>
      </div>
      {error && <div className="notice pricingError">{error}</div>}
    </section>

    {result && <>
      <PricingTargets calculation={result} onUseRecommendedPrice={price => onUseRecommendedPrice(price, result)} />
      <PricingBreakdown calculation={result} showCurrentPrice={showCurrentPrice} />
    </>}
  </>;
}

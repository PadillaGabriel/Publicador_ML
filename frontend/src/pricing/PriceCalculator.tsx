import { useEffect, useMemo, useRef, useState } from "react";
import { api, loadShippingCapabilities } from "../api";
import {
  normalizeCalculation,
  type PricingBreakdown,
  type PricingCalculation,
  type PricingCalculatorApiResponse,
  type PricingCalculatorPrefill,
  type PricingProfile,
  type ShippingCapabilities,
} from "./types";

type AccountOption = { id: string; nickname: string };
type CategorySuggestion = { category_id: string; category_name: string; domain_name?: string };
type PublicationType = { listing_type_id: string; label: string };
type Props = {
  accountId?: string;
  accounts: readonly AccountOption[];
  pricingProfile: PricingProfile;
  prefill?: PricingCalculatorPrefill | null;
  onLoadPublicationTypes: (accountId: string, categoryId: string) => Promise<PublicationType[]>;
  onSearchCategories: (accountId: string, query: string) => Promise<CategorySuggestion[]>;
  onUseRecommendedPrice: (price: number, calculation: PricingCalculation) => void;
};
type Mode = "existing" | "new";
type MarginScenario = "mc0" | "mc15" | "mc20" | "mc25" | "mc35" | "custom";
type PriceVariant = "base" | "3" | "6";

type LogisticResults = {
  base?: PricingCalculation;
  flex?: PricingCalculation;
};

const initialForm = {
  accountId: "",
  categoryId: "",
  categoryQuery: "",
  freeShipping: "false",
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

const marginScenarioValue: Record<Exclude<MarginScenario, "custom">, number> = {
  mc0: 0,
  mc15: 15,
  mc20: 20,
  mc25: 25,
  mc35: 35,
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

function normalizeMlaInput(value: string) {
  const raw = value.trim();
  if (/^\d{1,20}$/.test(raw)) return `MLA${raw}`;

  const match = raw.match(/(?:^|[^A-Z0-9])MLA[-_ ]?(\d{1,20})(?!\d)/i);
  if (match) return `MLA${match[1]}`;

  throw new Error(
    "Ingresá un MLA válido, por ejemplo MLA123456789, el número del MLA o su URL de Mercado Libre."
  );
}

function money(value: number, currencyId = "ARS") {
  return new Intl.NumberFormat("es-AR", {
    style: "currency",
    currency: currencyId,
    maximumFractionDigits: 2,
  }).format(Number(value) || 0);
}

function roundToStep(value: number, step: number) {
  const safeStep = Number(step) > 0 ? Number(step) : 1;
  return Math.ceil(value / safeStep) * safeStep;
}

function installmentPrice(base: number, markupPct: number, roundingStep: number) {
  if (!Number.isFinite(base) || base <= 0) return 0;
  return roundToStep(base * (1 + Number(markupPct || 0) / 100), roundingStep);
}

function selectedTarget(calculation: PricingCalculation | null, scenario: MarginScenario) {
  if (!calculation) return null;
  if (scenario === "custom") return null;
  if (scenario === "mc0") return calculation.mc0;
  if (scenario === "mc15") return calculation.mc15;
  if (scenario === "mc20") return calculation.mc20;
  return calculation.custom ?? calculation.target;
}

function selectedBreakdown(
  calculation: PricingCalculation | null,
  scenario: MarginScenario,
  variant: PriceVariant = "base",
): PricingBreakdown | null {
  if (!calculation) return null;
  if (variant !== "base" || scenario === "custom") return calculation.analyzed;
  if (scenario === "mc0") return calculation.breakdowns.mc0 ?? null;
  if (scenario === "mc15") return calculation.breakdowns.mc15 ?? null;
  if (scenario === "mc20") return calculation.breakdowns.mc20 ?? null;
  return calculation.breakdowns.custom ?? calculation.breakdowns.target ?? null;
}

export function PriceCalculator({
  accountId = "",
  accounts,
  pricingProfile,
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
  const [logisticResults, setLogisticResults] = useState<LogisticResults>({});
  const [scenario, setScenario] = useState<MarginScenario>("mc20");
  const [priceVariant, setPriceVariant] = useState<PriceVariant>("base");
  const [basePrincipalPrice, setBasePrincipalPrice] = useState(0);
  const [busy, setBusy] = useState(false);
  const [recalculating, setRecalculating] = useState(false);
  const [searchingCategories, setSearchingCategories] = useState(false);
  const [shippingCapabilities, setShippingCapabilities] = useState<ShippingCapabilities | null>(null);
  const [shippingCapabilitiesLoading, setShippingCapabilitiesLoading] = useState(false);
  const [shippingCapabilitiesError, setShippingCapabilitiesError] = useState("");
  const [error, setError] = useState("");
  const customPriceTimerRef = useRef<number | null>(null);

  const shippingReady = mode === "existing" || Boolean(
    shippingCapabilities
    && form.shippingMode === shippingCapabilities.mode
    && (
      form.logisticType === shippingCapabilities.base_logistic_type
      || (shippingCapabilities.flex_available && form.logisticType === shippingCapabilities.flex_logistic_type)
    )
  );

  const update = (name: keyof typeof form, value: string, clearResult = true) => {
    setForm(current => ({ ...current, [name]: value }));
    if (clearResult) {
      setResult(null);
      setLogisticResults({});
      setBasePrincipalPrice(0);
      setPriceVariant("base");
    }
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
            freeShipping: current.freeShipping || "false",
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
    setLogisticResults({});
    setBasePrincipalPrice(0);
    setPriceVariant("base");
    setScenario(prefill.salePrice ? "custom" : "mc20");
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
      freeShipping: prefill.freeShipping || "false",
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

  useEffect(() => () => {
    if (customPriceTimerRef.current !== null) window.clearTimeout(customPriceTimerRef.current);
  }, []);

  async function selectCategory(category: CategorySuggestion) {
    setError("");
    setForm(current => ({
      ...current,
      categoryId: category.category_id,
      categoryQuery: category.category_name,
      listingTypeId: "",
    }));
    setResult(null);
    setLogisticResults({});
    setPublicationTypes([]);
    try {
      const options = await onLoadPublicationTypes(form.accountId, category.category_id);
      setPublicationTypes(options);
      if (options.length === 1) {
        setForm(current => ({ ...current, listingTypeId: options[0].listing_type_id }));
      }
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
    setForm(current => ({ ...current, categoryId: "", listingTypeId: "" }));
    setPublicationTypes([]);
    setResult(null);
    setLogisticResults({});
    try {
      setCategories(await onSearchCategories(form.accountId, form.categoryQuery.trim()));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible buscar categorías.");
    } finally {
      setSearchingCategories(false);
    }
  }

  function buildPayload(options?: { logisticType?: string; targetMarginPct?: number; salePrice?: number | null }) {
    const base = {
      account_id: form.accountId || null,
      gross_cmv: optionalNumber(form.grossCmv),
      ...(options?.targetMarginPct !== undefined ? { target_margin_pct: options.targetMarginPct } : {}),
    };
    if (mode === "existing") {
      const explicitSalePrice = options && "salePrice" in options ? options.salePrice : optionalNumber(form.salePrice);
      return { ...base, item_id: normalizeMlaInput(form.itemId), sale_price: explicitSalePrice || null };
    }
    const explicitSalePrice = options && "salePrice" in options ? options.salePrice : optionalNumber(form.salePrice);
    return {
      ...base,
      sale_price: explicitSalePrice || null,
      category_id: form.categoryId || null,
      listing_type_id: form.listingTypeId || null,
      package: {
        dimensions: packageDimensions(form),
        weight: optionalNumber(form.weight),
        logistic_type: options?.logisticType || form.logisticType || null,
        shipping_mode: form.shippingMode || null,
        free_shipping: form.freeShipping === "true",
      },
    };
  }

  async function requestCalculation(options?: { logisticType?: string; targetMarginPct?: number; salePrice?: number | null }) {
    const response = await api<PricingCalculatorApiResponse>(
      mode === "existing" ? "/api/pricing/calculator/existing" : "/api/pricing/calculator/new",
      { method: "POST", body: JSON.stringify(buildPayload(options)) }
    );
    return normalizeCalculation(response);
  }

  function currentScenarioOptions(nextScenario = scenario) {
    if (nextScenario === "custom") {
      const price = Number(form.salePrice);
      if (!Number.isFinite(price) || price <= 0) {
        throw new Error("Ingresá un precio personalizado mayor a cero.");
      }
      return { salePrice: price };
    }
    return { targetMarginPct: marginScenarioValue[nextScenario] };
  }

  async function calculateForSelectedContext(nextScenario = scenario) {
    const options = currentScenarioOptions(nextScenario);
    const primary = await requestCalculation({ ...options, logisticType: form.logisticType || undefined });
    setResult(primary);

    const target = selectedTarget(primary, nextScenario);
    const principal = nextScenario === "custom"
      ? primary.analyzed.grossPrice
      : Number(target?.grossPrice || primary.recommendedPrice || 0);
    setBasePrincipalPrice(principal);
    setPriceVariant("base");

    if (mode === "new" && shippingCapabilities) {
      const pairs: Array<Promise<["base" | "flex", PricingCalculation]>> = [];
      pairs.push(
        requestCalculation({ ...options, logisticType: shippingCapabilities.base_logistic_type })
          .then(value => ["base", value] as ["base", PricingCalculation])
      );
      if (shippingCapabilities.flex_available) {
        pairs.push(
          requestCalculation({ ...options, logisticType: shippingCapabilities.flex_logistic_type })
            .then(value => ["flex", value] as ["flex", PricingCalculation])
        );
      }
      const resolved = await Promise.all(pairs);
      const next: LogisticResults = {};
      resolved.forEach(([key, value]) => { next[key] = value; });
      setLogisticResults(next);
      if (form.logisticType === shippingCapabilities.flex_logistic_type && next.flex) setResult(next.flex);
      if (form.logisticType === shippingCapabilities.base_logistic_type && next.base) setResult(next.base);
    }

    return primary;
  }

  async function calculate() {
    setBusy(true);
    setError("");
    try {
      await calculateForSelectedContext();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible calcular el precio.");
    } finally {
      setBusy(false);
    }
  }

  async function selectMarginScenario(nextScenario: MarginScenario) {
    setScenario(nextScenario);
    setPriceVariant("base");
    if (!result) return;
    if (nextScenario === "custom" && !(Number(form.salePrice) > 0)) {
      setResult(null);
      setLogisticResults({});
      setBasePrincipalPrice(0);
      return;
    }
    setRecalculating(true);
    setError("");
    try {
      await calculateForSelectedContext(nextScenario);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible recalcular el precio.");
    } finally {
      setRecalculating(false);
    }
  }

  function scheduleCustomPriceRecalculation(raw: string) {
    setForm(current => ({ ...current, salePrice: raw }));
    setScenario("custom");
    setPriceVariant("base");
    if (customPriceTimerRef.current !== null) window.clearTimeout(customPriceTimerRef.current);
    const price = Number(raw);
    if (!result || !Number.isFinite(price) || price <= 0) return;
    customPriceTimerRef.current = window.setTimeout(() => {
      setRecalculating(true);
      setError("");
      void calculateForSelectedContext("custom")
        .catch(reason => setError(reason instanceof Error ? reason.message : "No fue posible recalcular el precio."))
        .finally(() => setRecalculating(false));
    }, 450);
  }

  async function selectLogisticType(logisticType: string) {
    if (!shippingCapabilities) return;
    setForm(current => ({ ...current, shippingMode: shippingCapabilities.mode, logisticType }));
    setPriceVariant("base");
    const cached = logisticType === shippingCapabilities.flex_logistic_type
      ? logisticResults.flex
      : logisticResults.base;
    if (cached) {
      setResult(cached);
      const target = selectedTarget(cached, scenario);
      setBasePrincipalPrice(scenario === "custom" ? cached.analyzed.grossPrice : Number(target?.grossPrice || cached.recommendedPrice || 0));
      return;
    }
    if (!result) return;
    setRecalculating(true);
    setError("");
    try {
      const next = await requestCalculation({ ...currentScenarioOptions(), logisticType });
      setResult(next);
      setLogisticResults(current => ({
        ...current,
        ...(logisticType === shippingCapabilities.flex_logistic_type ? { flex: next } : { base: next }),
      }));
      const target = selectedTarget(next, scenario);
      setBasePrincipalPrice(scenario === "custom" ? next.analyzed.grossPrice : Number(target?.grossPrice || next.recommendedPrice || 0));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible recalcular la logística.");
    } finally {
      setRecalculating(false);
    }
  }

  async function activateInstallmentVariant(term: 3 | 6) {
    const base = basePrincipalPrice;
    if (!base) return;
    const variant: PriceVariant = term === 3 ? "3" : "6";
    const markup = term === 3
      ? pricingProfile.installment_3_markup_pct
      : pricingProfile.installment_6_markup_pct;
    const financedPrice = installmentPrice(base, markup, pricingProfile.rounding_step);
    if (!(financedPrice > 0)) return;

    setRecalculating(true);
    setError("");
    try {
      const primary = await requestCalculation({
        salePrice: financedPrice,
        logisticType: form.logisticType || undefined,
      });
      setResult(primary);
      setPriceVariant(variant);

      if (mode === "new" && shippingCapabilities) {
        const pairs: Array<Promise<["base" | "flex", PricingCalculation]>> = [
          requestCalculation({
            salePrice: financedPrice,
            logisticType: shippingCapabilities.base_logistic_type,
          }).then(value => ["base", value] as ["base", PricingCalculation]),
        ];
        if (shippingCapabilities.flex_available) {
          pairs.push(
            requestCalculation({
              salePrice: financedPrice,
              logisticType: shippingCapabilities.flex_logistic_type,
            }).then(value => ["flex", value] as ["flex", PricingCalculation]),
          );
        }
        const resolved = await Promise.all(pairs);
        const next: LogisticResults = {};
        resolved.forEach(([key, value]) => { next[key] = value; });
        setLogisticResults(next);
        if (form.logisticType === shippingCapabilities.flex_logistic_type && next.flex) setResult(next.flex);
        if (form.logisticType === shippingCapabilities.base_logistic_type && next.base) setResult(next.base);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `No fue posible calcular el precio de ${term} cuotas.`);
    } finally {
      setRecalculating(false);
    }
  }

  const breakdown = selectedBreakdown(result, scenario, priceVariant);
  const basePrice = basePrincipalPrice || (scenario === "custom" ? Number(form.salePrice) : Number(selectedTarget(result, scenario)?.grossPrice || result?.recommendedPrice || 0));
  const installment3Price = installmentPrice(basePrice, pricingProfile.installment_3_markup_pct, pricingProfile.rounding_step);
  const installment6Price = installmentPrice(basePrice, pricingProfile.installment_6_markup_pct, pricingProfile.rounding_step);
  const displayedPrincipalPrice = priceVariant === "3" ? installment3Price : priceVariant === "6" ? installment6Price : basePrice;
  const selectedMarginLabel = scenario === "custom" ? "Precio personalizado" : `Precio sugerido con MC ${marginScenarioValue[scenario]}%`;

  const baseLogistics = useMemo(() => {
    const calculation = logisticResults.base;
    const selected = selectedBreakdown(calculation ?? null, scenario, priceVariant);
    return selected?.netLogisticCost ?? calculation?.analyzed.netLogisticCost ?? null;
  }, [logisticResults.base, scenario, priceVariant]);
  const flexLogistics = useMemo(() => {
    const calculation = logisticResults.flex;
    const selected = selectedBreakdown(calculation ?? null, scenario, priceVariant);
    return selected?.netLogisticCost ?? calculation?.analyzed.netLogisticCost ?? null;
  }, [logisticResults.flex, scenario, priceVariant]);

  const calculatorReady = Boolean(
    form.accountId
    && form.grossCmv
    && (mode === "existing"
      ? form.itemId
      : form.categoryId && form.listingTypeId && shippingReady && packageDimensions(form) && form.weight)
  );

  return <>
    <header>
      <div>
        <h1>Calculadora de precio</h1>
        <p>Simulá el precio final con la misma lógica económica y visual que usás al preparar una publicación.</p>
      </div>
    </header>

    <section className="card calculatorUnifiedShell">
      <div className="pricingModeTabs" role="tablist" aria-label="Tipo de cálculo">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "existing"}
          className={mode === "existing" ? "active" : ""}
          onClick={() => { setMode("existing"); setResult(null); setLogisticResults({}); setBasePrincipalPrice(0); setError(""); }}
        >Publicación existente</button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "new"}
          className={mode === "new" ? "active" : ""}
          onClick={() => { setMode("new"); setResult(null); setLogisticResults({}); setBasePrincipalPrice(0); setError(""); }}
        >Producto nuevo</button>
      </div>

      <section className="calculatorContextPanel">
        <div className="pricingSectionHeader">
          <h2>Contexto</h2>
          <p>Estos datos permiten a Mercado Libre resolver comisión, cargos y logística. La política económica sigue viniendo de Configuración.</p>
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
      </section>

      <div className="publisherPricingUnified calculatorPricingUnified">
        <div className="publisherPricingHeader">
          <div>
            <div className="publisherPricingTitleRow">
              <h2>Precios</h2>
              <span className="pricingConfigPill">ⓘ 3 y 6 cuotas se configuran en Configuración</span>
            </div>
            <p>Calculá tus costos, compará logística y definí el precio de venta.</p>
          </div>
        </div>

        <div className={`publisherPricingTopGrid ${mode === "existing" ? "calculatorExistingTopGrid" : ""}`}>
          <label className="publisherPricingField">
            <span>Costo del producto (con IVA)</span>
            <div className="moneyInput"><span>$</span><input type="number" min="0" step="0.01" value={form.grossCmv} onChange={event => update("grossCmv", event.target.value)} placeholder="0,00" /></div>
            <small>Es el único costo que cargás por producto.</small>
          </label>
          {mode === "new" && <label className="publisherPricingField">
            <span>Precio de venta (opcional)</span>
            <div className="moneyInput"><span>$</span><input type="number" min="0.01" step="0.01" value={form.salePrice} onChange={event => scheduleCustomPriceRecalculation(event.target.value)} placeholder="Ej. 18.990" /></div>
            <small>Si lo dejás vacío, se calculará automáticamente.</small>
          </label>}
          {mode === "new" && <div className="publisherPackageFields">
            <div className="publisherPackageHeader">
              <b>Medidas del paquete</b>
              {prefill?.dimensions && <span className="technicalAutofillPill">▣ Autocompletado desde ficha técnica</span>}
            </div>
            <div className="publisherPackageGrid">
              <label>Largo (cm)<input type="number" min="0" step="0.1" value={form.length} onChange={event => update("length", event.target.value)} /></label>
              <label>Ancho (cm)<input type="number" min="0" step="0.1" value={form.width} onChange={event => update("width", event.target.value)} /></label>
              <label>Alto (cm)<input type="number" min="0" step="0.1" value={form.height} onChange={event => update("height", event.target.value)} /></label>
              <label>Peso (kg)<input type="number" min="0.01" step="0.01" value={form.weight} onChange={event => update("weight", event.target.value)} /></label>
            </div>
            <small>Si falta algún dato, podés completarlo manualmente.</small>
          </div>}
        </div>

        <div className="publisherPricingWorkspace">
          <div className="publisherPricingWorkbench">
            {mode === "new" && <section className="publisherLogisticsSection">
              <div className="publisherPricingSubheader">
                <div><h3>Logística</h3><p>Compará las opciones y elegí cuál usar en el cálculo principal.</p></div>
                <span>{shippingCapabilitiesLoading ? "Consultando Mercado Libre…" : shippingCapabilities?.flex_available ? "Flex se ofrece siempre." : "Flex no está habilitado para este contexto."}</span>
              </div>
              {shippingCapabilitiesError && <div className="shippingCapabilityError">{shippingCapabilitiesError}</div>}
              <div className="publisherLogisticsCards">
                <button
                  type="button"
                  disabled={!shippingCapabilities || recalculating}
                  className={`publisherLogisticsCard ${shippingCapabilities && form.logisticType === shippingCapabilities.base_logistic_type ? "selected" : ""}`}
                  onClick={() => shippingCapabilities && void selectLogisticType(shippingCapabilities.base_logistic_type)}
                >
                  <div className="publisherLogisticsCardTitle"><span className="radioDot"/><b>Mercado Envíos / Colecta</b>{shippingCapabilities && form.logisticType === shippingCapabilities.base_logistic_type && <em>Seleccionada</em>}</div>
                  <div className="publisherLogisticsCardBody">
                    <div><strong>{baseLogistics !== null ? money(baseLogistics) : "—"}</strong><small>Costo logístico neto</small></div>
                    <div className="publisherLogisticsMeta"><span>Modalidad resuelta por Mercado Libre</span><span>{result ? "Cálculo disponible" : "Se completa al calcular"}</span></div>
                  </div>
                </button>
                <button
                  type="button"
                  disabled={!shippingCapabilities?.flex_available || recalculating}
                  className={`publisherLogisticsCard ${shippingCapabilities && form.logisticType === shippingCapabilities.flex_logistic_type ? "selected" : ""}`}
                  onClick={() => shippingCapabilities && void selectLogisticType(shippingCapabilities.flex_logistic_type)}
                >
                  <div className="publisherLogisticsCardTitle"><span className="radioDot"/><b>Flex</b>{shippingCapabilities && form.logisticType === shippingCapabilities.flex_logistic_type && <em>Seleccionada</em>}</div>
                  <div className="publisherLogisticsCardBody">
                    <div><strong>{flexLogistics !== null ? money(flexLogistics) : "—"}</strong><small>Costo logístico neto</small></div>
                    <div className="publisherLogisticsMeta"><span>{shippingCapabilities?.flex_available ? "Disponible para esta cuenta" : "No disponible"}</span><span>{logisticResults.flex ? "Cálculo disponible" : "Se completa al calcular"}</span></div>
                  </div>
                </button>
              </div>
              <div className="publisherLogisticsFooter calculatorLogisticsFooter">
                <label>Quién paga el envío
                  <select value={form.freeShipping} onChange={event => update("freeShipping", event.target.value)}>
                    <option value="">Elegí una opción</option>
                    <option value="false">El comprador paga el envío</option>
                    <option value="true">Ofrecer envío gratis</option>
                  </select>
                </label>
                <div className="pricingResolvedContext compact"><span>Modalidad usada para pricing</span><b>{shippingCapabilities && form.logisticType === shippingCapabilities.flex_logistic_type ? "Flex" : "Mercado Envíos / Colecta"}</b><small>Podés alternarla sin ocultar el otro cálculo.</small></div>
              </div>
            </section>}

            <section className="publisherMarginSection">
              <div className="publisherPricingSubheader">
                <div><h3>Cálculo por Mercado Libre</h3><p>Elegí el margen deseado o personalizá el precio. Se calculan todos los costos automáticamente.</p></div>
              </div>
              <div className="publisherMarginControls">
                <div className="publisherMarginSelector" role="group" aria-label="Margen de contribución objetivo">
                  {(["mc0", "mc15", "mc20", "mc25", "mc35"] as MarginScenario[]).map(option => <button key={option} type="button" disabled={recalculating} className={scenario === option ? "active" : ""} onClick={() => void selectMarginScenario(option)}>{option.replace("mc", "MC ")}%</button>)}
                  <button type="button" disabled={recalculating} className={scenario === "custom" ? "active" : ""} onClick={() => void selectMarginScenario("custom")}>Personalizado</button>
                </div>
                <label className="publisherCustomPrice">Precio personalizado
                  <div className="moneyInput"><span>$</span><input type="number" min="0.01" step="0.01" value={form.salePrice} onChange={event => scheduleCustomPriceRecalculation(event.target.value)} placeholder="Ej. 24.990" /></div>
                  <small>Se recalcula en tiempo real.</small>
                </label>
              </div>
              <div className="publisherPricingPrimaryActions">
                <button type="button" disabled={!calculatorReady || busy || recalculating} onClick={calculate}>{busy || recalculating ? "Calculando…" : "Calcular"}</button>
                <span>Usa tu Configuración y los costos actuales de Mercado Libre.</span>
              </div>
            </section>
          </div>

          <aside className="publisherPriceSummary">
            <div className="publisherPriceSummaryHeader"><h3>Precio principal</h3><p>{selectedMarginLabel}</p></div>
            <div className="publisherPrincipalPrice">{displayedPrincipalPrice > 0 ? money(displayedPrincipalPrice) : "—"}</div>
            <div className="publisherInstallmentActions">
              <button type="button" className={priceVariant === "3" ? "active" : ""} disabled={!basePrice} onClick={() => activateInstallmentVariant(3)}>
                <span>▤ Calcular precio 3 cuotas</span><b>{installment3Price ? money(installment3Price) : "—"}</b>
              </button>
              <button type="button" className={priceVariant === "6" ? "active" : ""} disabled={!basePrice} onClick={() => activateInstallmentVariant(6)}>
                <span>▤ Calcular precio 6 cuotas</span><b>{installment6Price ? money(installment6Price) : "—"}</b>
              </button>
            </div>
            <div className="publisherInstallmentPreview">
              <div><span>3 cuotas</span><b>{installment3Price ? `${money(installment3Price / 3)} × 3` : "—"}</b><small>+{pricingProfile.installment_3_markup_pct}% sobre precio principal</small></div>
              <div><span>6 cuotas</span><b>{installment6Price ? `${money(installment6Price / 6)} × 6` : "—"}</b><small>+{pricingProfile.installment_6_markup_pct}% sobre precio principal</small></div>
            </div>
            {breakdown ? <div className="publisherPriceLedger">
              <div><span>Costo del producto (con IVA)</span><b>{money(breakdown.grossCmv || Number(form.grossCmv))}</b></div>
              <div><span>Comisión Mercado Libre</span><b>− {money(breakdown.mlCommissionNet || 0)}</b></div>
              {Number(breakdown.financingNet || 0) > 0 && <div><span>Financiación Mercado Libre</span><b>− {money(breakdown.financingNet)}</b></div>}
              <div><span>Cargo fijo por venta</span><b>− {money(breakdown.fixedFee || 0)}</b></div>
              <div><span>Costo logístico neto</span><b>− {money(breakdown.netLogisticCost || 0)}</b></div>
              <div><span>IIBB</span><b>− {money(breakdown.iibb || 0)}</b></div>
              <div className="publisherMarginResult"><span>Margen resultante</span><b>{Number(breakdown.contributionMarginPct || 0).toFixed(2)}%</b><strong>{money(breakdown.contributionMargin || 0)}</strong></div>
            </div> : <div className="publisherPriceSummaryEmpty">Calculá el precio para ver el desglose económico.</div>}
          </aside>
        </div>

        {result && <div className="calculatorUsePriceBar">
          <div><b>Precio recomendado disponible</b><span>Podés llevar el precio principal calculado nuevamente al Publicador.</span></div>
          <button type="button" className="secondary" disabled={!basePrice} onClick={() => onUseRecommendedPrice(basePrice, result)}>Usar este precio en la publicación</button>
        </div>}
      </div>

      {error && <div className="notice pricingError">{error}</div>}
    </section>
  </>;
}

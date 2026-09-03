import React, {useEffect, useMemo, useState} from "react";
import {createRoot} from "react-dom/client";
import {api, downloadFile, jobEvents} from "./api";
import {PriceCalculator} from "./pricing/PriceCalculator";
import {PricingProfileEditor} from "./pricing/PricingProfileEditor";
import type {PricingCalculation, PricingProfile} from "./pricing/types";
import {TitleAssistant} from "./title-intelligence/TitleAssistant";
import "./styles.css";

type Account = {
  id: string;
  nickname: string;
  seller_id?: string;
  site_id: string;
  auth_status: string;
  active: boolean;
};
type CategorySuggestion = {category_id: string; category_name: string; domain_id?: string; domain_name?: string};
type CommercialOption = {
  commercial_intent: "WITH_INSTALLMENTS" | "WITHOUT_INSTALLMENTS";
  label: string;
  listing_type_id: string;
  listing_type_name: string;
};
type Field = {
  id: string;
  label: string;
  value_type: string;
  required: boolean;
  required_for_item?: boolean;
  catalog_required?: boolean;
  hidden?: boolean;
  importance?: "required" | "recommended" | "secondary" | "system";
  relevance?: number;
  is_boolean?: boolean;
  is_measurement?: boolean;
  allowed_units?: {id?: string; name: string}[];
  default_unit?: string;
  allow_custom_value?: boolean;
  attribute_group_id?: string;
  attribute_group_name?: string;
  hierarchy?: string;
  hint?: string;
  value_max_length?: number;
  values: {id?: string; name: string; struct?: any}[];
};
type RequirementGroup = {
  id: string;
  kind: "one_of";
  attribute_ids: string[];
  required: boolean;
  message?: string;
};
type ProductIdentifierContract = {
  kind: "gtin_or_empty_reason";
  required: boolean;
  gtin_attribute_id: string;
  empty_reason_attribute_id: string;
  empty_reason_values: {id?: string; name: string; struct?: any}[];
  empty_reason_source: "category_metadata" | "provider_contract_fallback" | string;
};
type DraftValidationIssue = {code?: string; field?: string; message?: string};
type Draft = {
  id: string; sequence_number: number; title: string; score: number;
  commercial_config?: Record<string, any>; status: string; image_order: string[]; last_error?: any;
  validation?: {
    valid: boolean;
    errors: DraftValidationIssue[];
    warnings: DraftValidationIssue[];
    created_at?: string;
  } | null;
};
type OAuthStatus = {configured: boolean; redirect_uri?: string; callback_is_local_publisher: boolean};
type ExistingProduct = {
  id: string;
  internal_sku: string;
  internal_name: string;
  latest_version: {
    id: string;
    version_number: number;
    category_id: string;
    title_reference: string;
    description: string;
    price: number;
    quantity: number;
    listing_type_id?: string | null;
    attributes: Record<string, any>;
    commercial: Record<string, any>;
    logistics: Record<string, any>;
    discovery_context?: Record<string, any>;
    images?: {id: string; original_name: string; position: number; mime_type: string}[];
  };
};

type UploadedImage = {id: string; original_name: string; position: number; mime_type: string};
type QuantityPriceTier = {min_purchase_unit: number; amount: number};
type CommercialAllocation = CommercialOption & {count: number};
const TERMINAL_JOB_STATES = ["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"];
const GTIN_ATTRIBUTE_ID = "GTIN";
const EMPTY_GTIN_REASON_ATTRIBUTE_ID = "EMPTY_GTIN_REASON";

function attributeValuePresent(value: any) {
  if (value === undefined || value === null || value === "") return false;
  if (typeof value === "object") return Boolean(value.value_id || value.value_name || value.name);
  return String(value).trim().length > 0;
}

function identifierText(value: any) {
  if (!attributeValuePresent(value)) return "";
  if (typeof value === "object") {
    return String(value.value_name || value.name || value.value_id || "").trim();
  }
  return String(value).trim();
}

function plausibleGtin(value: any) {
  const text = identifierText(value).replaceAll("-", "").replaceAll(" ", "");
  return Boolean(text) && /^\d+$/.test(text);
}

function optionMatches(value: any, options: {id?: string; name: string}[]) {
  if (!attributeValuePresent(value)) return false;
  const valueId = typeof value === "object" ? String(value.value_id || "").trim() : "";
  const valueName = identifierText(value).toLocaleLowerCase("es-AR");
  return options.some(option => {
    const optionId = String(option.id || "").trim();
    const optionName = String(option.name || "").trim().toLocaleLowerCase("es-AR");
    return Boolean((valueId && optionId && valueId === optionId) || (valueName && valueName === optionName));
  });
}

function measurementParts(value: any, field: Field) {
  const valueStruct = typeof value === "object" && value ? (value.value_struct || value.struct || {}) : {};
  const rawNumber = valueStruct.number ?? "";
  const allowedUnits = field.allowed_units || [];
  const configuredDefault = String(field.default_unit || "").trim();
  const fallbackUnit = String(allowedUnits[0]?.id || allowedUnits[0]?.name || "").trim();
  return {
    number: rawNumber === null || rawNumber === undefined ? "" : String(rawNumber),
    unit: String(valueStruct.unit || configuredDefault || fallbackUnit || "").trim(),
  };
}

function money(value: any) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return new Intl.NumberFormat("es-AR", {style: "currency", currency: "ARS", maximumFractionDigits: 2}).format(number);
}

function buildMeasurementValue(numberText: string, unit: string) {
  const normalizedNumber = numberText.trim().replace(",", ".");
  if (!normalizedNumber) return null;
  const number = Number(normalizedNumber);
  if (!Number.isFinite(number) || !unit) return null;
  return {
    value_name: `${normalizedNumber} ${unit}`,
    value_struct: {number, unit},
  };
}

function App() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categorySuggestions, setCategorySuggestions] = useState<CategorySuggestion[]>([]);
  const [selectedCategoryName, setSelectedCategoryName] = useState("");
  const [commercialOptions, setCommercialOptions] = useState<CommercialOption[]>([]);
  const [categoryContractLoading, setCategoryContractLoading] = useState(false);
  const [titleMaxLength, setTitleMaxLength] = useState<number | null>(null);
  const [accountId, setAccountId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [fields, setFields] = useState<Field[]>([]);
  const [requirements, setRequirements] = useState<RequirementGroup[]>([]);
  const [productIdentifierContract, setProductIdentifierContract] = useState<ProductIdentifierContract | null>(null);
  const [productIdentifierMode, setProductIdentifierMode] = useState<"GTIN" | "NO_GTIN" | "">("");
  const [attributes, setAttributes] = useState<Record<string, any>>({});
  const [customAttributeFields, setCustomAttributeFields] = useState<Record<string, boolean>>({});
  const [showSecondaryAttributes, setShowSecondaryAttributes] = useState(false);
  const [versionId, setVersionId] = useState("");
  const [batchId, setBatchId] = useState("");
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [job, setJob] = useState<any>(null);
  const [keywordIntelligence, setKeywordIntelligence] = useState<any>(null);
  const [selectedDraftIds, setSelectedDraftIds] = useState<string[]>([]);
  const [generationActive, setGenerationActive] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [accountModal, setAccountModal] = useState(false);
  const [manualMode, setManualMode] = useState(false);
  const [oauthStatus, setOauthStatus] = useState<OAuthStatus | null>(null);
  const [manualAccount, setManualAccount] = useState({nickname: "", token: ""});
  const [existingProduct, setExistingProduct] = useState<ExistingProduct | null>(null);
  const [dismissedExistingSku, setDismissedExistingSku] = useState("");
  const [skuLookupBusy, setSkuLookupBusy] = useState(false);
  const [commercialAllocations, setCommercialAllocations] = useState<CommercialAllocation[]>([]);
  const [uploadedImages, setUploadedImages] = useState<UploadedImage[]>([]);
  const [imageUploadBusy, setImageUploadBusy] = useState(false);
  const [activeView, setActiveView] = useState<"publisher" | "pricing-settings" | "price-calculator">("publisher");
  const [pricingConfigured, setPricingConfigured] = useState(false);
  const [pricingProfile, setPricingProfile] = useState<PricingProfile>({
    name: "Mercado Libre", channel: "MERCADOLIBRE", currency_id: "ARS",
    target_margin_pct: 20, minimum_margin_pct: 10, vat_rate_pct: 21, iibb_rate_pct: 0, ads_rate_pct: 0, refund_rate_pct: 0,
    monthly_units_projection: null, rounding_step: 1, components: []
  });
  const [productCost, setProductCost] = useState("0");
  const [additionalUnitCost, setAdditionalUnitCost] = useState("0");
  const [pricingAnalysis, setPricingAnalysis] = useState<any>(null);
  const [simulationPackage, setSimulationPackage] = useState({
    dimensions: "", weight: "", logisticType: "", shippingMode: "",
  });
  const [quantityPricingEnabled, setQuantityPricingEnabled] = useState(false);
  const [quantityPrices, setQuantityPrices] = useState<QuantityPriceTier[]>([]);

  const [form, setForm] = useState({
    sku: "", name: "", title: "", brand: "", model: "", characteristics: "", description: "",
    price: "0", quantity: "1", count: "6", localPickup: false, warrantyType: "SELLER",
    warrantyDuration: "30", warrantyUnit: "days"
  });

  const selectedAccount = useMemo(
    () => accounts.find(account => account.id === accountId),
    [accounts, accountId]
  );
  const totalCount = Math.max(1, Number(form.count) || 1);
  const allocatedCount = commercialAllocations.reduce((sum, option) => sum + Math.max(0, option.count), 0);
  const distributionInvalid = allocatedCount !== totalCount;

  const contextComplete = Boolean(accountId && categoryId);
  const productComplete = Boolean(versionId);
  const draftsComplete = drafts.length > 0;
  const approvedCount = drafts.filter(d => d.status === "APPROVED").length;
  const terminalJob = job && TERMINAL_JOB_STATES.includes(job.status);
  const approvedDraftIds = drafts.filter(d => d.status === "APPROVED").map(d => d.id);
  const selectedApprovedDraftIds = selectedDraftIds.filter(id => approvedDraftIds.includes(id));
  const allApprovedSelected = approvedDraftIds.length > 0
    && approvedDraftIds.every(id => selectedDraftIds.includes(id));
  const groupedRequiredAttributeIds = useMemo(
    () => new Set(requirements.filter(group => group.required).flatMap(group => group.attribute_ids)),
    [requirements]
  );
  const dedicatedAttributeIds = useMemo(
    () => new Set([GTIN_ATTRIBUTE_ID, EMPTY_GTIN_REASON_ATTRIBUTE_ID]),
    []
  );
  const requiredFields = useMemo(
    () => fields.filter(
      field => (field.importance === "required" || field.required || field.catalog_required)
        && !groupedRequiredAttributeIds.has(field.id)
        && !dedicatedAttributeIds.has(field.id)
    ),
    [fields, groupedRequiredAttributeIds, dedicatedAttributeIds]
  );
  const recommendedFields = useMemo(
    () => fields.filter(field => field.importance === "recommended" && !groupedRequiredAttributeIds.has(field.id) && !dedicatedAttributeIds.has(field.id)),
    [fields, groupedRequiredAttributeIds, dedicatedAttributeIds]
  );
  const secondaryFields = useMemo(
    () => fields.filter(field => field.importance === "secondary" && !groupedRequiredAttributeIds.has(field.id) && !dedicatedAttributeIds.has(field.id)),
    [fields, groupedRequiredAttributeIds, dedicatedAttributeIds]
  );
  const completedRecommendedFields = recommendedFields.filter(
    field => attributeValuePresent(attributes[field.id])
  ).length;
  const completedRequiredFields = requiredFields.filter(
    field => attributeValuePresent(attributes[field.id])
  ).length;
  const requiredGroupsComplete = requirements
    .filter(group => group.required)
    .every(group => group.attribute_ids.filter(id => attributeValuePresent(attributes[id])).length === 1);
  const hasGtinField = fields.some(field => field.id === GTIN_ATTRIBUTE_ID);
  const productIdentifierComplete = !hasGtinField || Boolean(
    productIdentifierContract
    && [GTIN_ATTRIBUTE_ID, EMPTY_GTIN_REASON_ATTRIBUTE_ID]
      .filter(id => attributeValuePresent(attributes[id])).length === 1
  );
  const requiredAttributesComplete = completedRequiredFields === requiredFields.length
    && requiredGroupsComplete
    && productIdentifierComplete;

  async function refreshAccounts() {
    const result = await api<Account[]>("/api/accounts");
    setAccounts(result);
    if (!accountId && result.length === 1) setAccountId(result[0].id);
  }

  useEffect(() => {
    refreshAccounts().catch(e => setMessage(e.message));
    api<OAuthStatus>("/api/accounts/oauth/status")
      .then(setOauthStatus)
      .catch(() => setOauthStatus(null));

    const params = new URLSearchParams(window.location.search);

      if (params.get("ml_connected") === "1") {
        const connectedAccountId = params.get("account_id");

        if (connectedAccountId) {
          setAccountId(connectedAccountId);
        }

        setMessage("Cuenta de Mercado Libre conectada correctamente.");
        refreshAccounts().catch(e => setMessage(e.message));

        window.history.replaceState(
          {},
          document.title,
          window.location.pathname
        );
      }
  }, []);

  useEffect(() => {
    api<any>("/api/pricing/profile?channel=MERCADOLIBRE")
      .then(result => {
        setPricingConfigured(Boolean(result.configured));
        if (result.profile) {
          setPricingProfile({
            name: result.profile.name,
            channel: result.profile.channel,
            currency_id: result.profile.currency_id,
            target_margin_pct: Number(result.profile.target_margin_pct),
            minimum_margin_pct: Number(result.profile.minimum_margin_pct),
            vat_rate_pct: Number(result.profile.vat_rate_pct),
            iibb_rate_pct: Number(result.profile.iibb_rate_pct),
            ads_rate_pct: Number(result.profile.ads_rate_pct),
            refund_rate_pct: Number(result.profile.refund_rate_pct),
            monthly_units_projection: result.profile.monthly_units_projection,
            rounding_step: Number(result.profile.rounding_step),
            components: (result.profile.components || []).map((component:any) => ({
              name: component.name, kind: component.kind, value: Number(component.value), basis: component.basis, active: Boolean(component.active)
            })),
          });
        }
      })
      .catch(() => setPricingConfigured(false));
  }, []);

  useEffect(() => {
    let source: EventSource | null = null;
    api<{job:any | null}>("/api/jobs/active/current")
      .then(result => {
        if (!result.job) return;
        const jobId = result.job.id;
        setJob({...result.job, job_id:jobId});
        source = watchJob(jobId);
      })
      .catch(() => undefined);
    return () => source?.close();
  }, []);

  useEffect(() => {
    setCategoryId("");
    setSelectedCategoryName("");
    setCategorySuggestions([]);
    setCommercialOptions([]);
    setCategoryContractLoading(false);
    setTitleMaxLength(null);
    setFields([]);
    setRequirements([]);
    setProductIdentifierContract(null);
    setProductIdentifierMode("");
    setAttributes({});
    setCustomAttributeFields({});
    setShowSecondaryAttributes(false);
    setVersionId("");
    setUploadedImages([]);
    setBatchId("");
    setDrafts([]);
    setKeywordIntelligence(null);
    setSelectedDraftIds([]);
  }, [accountId]);

  useEffect(() => {
    let cancelled = false;
    if (!categoryId) {
      setFields([]);
      setRequirements([]);
      setProductIdentifierContract(null);
      setProductIdentifierMode("");
      setCommercialOptions([]);
      setCommercialAllocations([]);
      setCategoryContractLoading(false);
      setTitleMaxLength(null);
      setAttributes({});
      return () => { cancelled = true; };
    }
    setCategoryContractLoading(true);
    setTitleMaxLength(null);
    setCommercialOptions([]);
    setRequirements([]);
    setProductIdentifierContract(null);
    setProductIdentifierMode("");
    setAttributes({});
    setCustomAttributeFields({});
    setShowSecondaryAttributes(false);
    setVersionId("");
    setUploadedImages([]);
    setDrafts([]);
    setKeywordIntelligence(null);
    setSelectedDraftIds([]);
    setBatchId("");
    Promise.all([
      api<any>(`/api/catalog/categories/${categoryId}?account_id=${encodeURIComponent(accountId)}`),
      api<{options: CommercialOption[]}>(
        `/api/publication/commercial-options?account_id=${encodeURIComponent(accountId)}&category_id=${encodeURIComponent(categoryId)}`
      ),
    ])
      .then(([meta, listingResponse]) => {
        if (cancelled) return;
        const loadedFields: Field[] = meta.schema.fields || [];
        const loadedIdentifierContract = (meta.schema.product_identifier_contract || null) as ProductIdentifierContract | null;
        const maxTitleLength = meta.schema?.settings?.max_title_length;
        setFields(loadedFields);
        setRequirements(meta.schema.requirements || []);
        setProductIdentifierContract(loadedIdentifierContract);
        setTitleMaxLength(
          typeof maxTitleLength === "number" && Number.isFinite(maxTitleLength) && maxTitleLength > 0
            ? maxTitleLength
            : null
        );

        const availableCommercialOptions = listingResponse.options || [];
        setCommercialOptions(availableCommercialOptions);
        setCommercialAllocations(current => {
          const previousByIntent = new Map(current.map(row => [row.commercial_intent, row.count]));
          const next = availableCommercialOptions.map(option => ({
            ...option,
            count: previousByIntent.get(option.commercial_intent) || 0,
          }));
          if (next.length && next.every(row => row.count === 0)) {
            const preferred = next.find(row => row.commercial_intent === "WITHOUT_INSTALLMENTS") || next[0];
            preferred.count = Math.max(1, Number(form.count) || 1);
          }
          return next;
        });

        const previous = existingProduct?.latest_version;
        const sameCategory = previous?.category_id === categoryId;
        const restored: Record<string, any> = sameCategory ? {...(previous?.attributes || {})} : {};

        // Old versions could contain UI placeholders such as "Otros" in GTIN.
        // Never restore those as a product identifier. The operator must explicitly
        // choose a real GTIN or a valid no-GTIN reason under the current contract.
        if (attributeValuePresent(restored[GTIN_ATTRIBUTE_ID]) && !plausibleGtin(restored[GTIN_ATTRIBUTE_ID])) {
          delete restored[GTIN_ATTRIBUTE_ID];
        }
        const allowedEmptyReasons = loadedIdentifierContract?.empty_reason_values || [];
        if (attributeValuePresent(restored[EMPTY_GTIN_REASON_ATTRIBUTE_ID])
          && !optionMatches(restored[EMPTY_GTIN_REASON_ATTRIBUTE_ID], allowedEmptyReasons)) {
          delete restored[EMPTY_GTIN_REASON_ATTRIBUTE_ID];
        }
        if (attributeValuePresent(restored[GTIN_ATTRIBUTE_ID])) {
          delete restored[EMPTY_GTIN_REASON_ATTRIBUTE_ID];
        }

        if (form.brand.trim()) restored.BRAND = restored.BRAND || form.brand.trim();
        if (form.model.trim()) restored.MODEL = restored.MODEL || form.model.trim();
        setAttributes(restored);
        setProductIdentifierMode(
          attributeValuePresent(restored[GTIN_ATTRIBUTE_ID])
            ? "GTIN"
            : attributeValuePresent(restored[EMPTY_GTIN_REASON_ATTRIBUTE_ID])
              ? "NO_GTIN"
              : ""
        );
      })
      .catch(e => {
        if (!cancelled) {
          setTitleMaxLength(null);
          setMessage(e.message);
        }
      })
      .finally(() => { if (!cancelled) setCategoryContractLoading(false); });

    return () => { cancelled = true; };
  }, [categoryId, accountId]);

  useEffect(() => {
    const sku = form.sku.trim();
    setExistingProduct(null);
    if (!sku) {
      setDismissedExistingSku("");
      return;
    }

    const timer = window.setTimeout(async () => {
      setSkuLookupBusy(true);
      try {
        const result = await api<{found: boolean; product?: ExistingProduct}>(
          `/api/products/lookup?sku=${encodeURIComponent(sku)}`
        );
        setExistingProduct(result.found && result.product ? result.product : null);
      } catch {
        // El lookup es una ayuda no bloqueante: un fallo no impide continuar la carga.
        setExistingProduct(null);
      } finally {
        setSkuLookupBusy(false);
      }
    }, 450);

    return () => window.clearTimeout(timer);
  }, [form.sku]);


  function loadExistingProduct() {
    if (!existingProduct) return;
    const version = existingProduct.latest_version;
    const context = version.discovery_context || {};
    const savedBrand = context.brand || version.attributes?.BRAND?.value_name || version.attributes?.BRAND || "";
    const savedModel = context.model || version.attributes?.MODEL?.value_name || version.attributes?.MODEL || "";

    setForm(current => ({
      ...current,
      sku: existingProduct.internal_sku,
      name: existingProduct.internal_name,
      title: version.title_reference || "",
      brand: String(savedBrand || ""),
      model: String(savedModel || ""),
      characteristics: String(context.characteristics || ""),
      description: version.description || "",
      price: String(version.price),
      quantity: String(version.quantity),
      localPickup: Boolean(version.logistics?.local_pick_up),
      warrantyType: String(version.commercial?.warranty?.type || "SELLER"),
      warrantyDuration: String(version.commercial?.warranty?.duration || "30"),
      warrantyUnit: String(version.commercial?.warranty?.unit || "days"),
    }));

    const savedQuantityPrices = Array.isArray(version.commercial?.quantity_prices) ? version.commercial.quantity_prices : [];
    setQuantityPrices(savedQuantityPrices.map((tier:any) => ({
      min_purchase_unit: Number(tier.min_purchase_unit),
      amount: Number(tier.amount),
    })));
    setQuantityPricingEnabled(savedQuantityPrices.length > 0);
    const savedPricing = version.commercial?.pricing_analysis || null;
    setPricingAnalysis(savedPricing);

    setCategoryId("");
    setSelectedCategoryName("");
    setCategorySuggestions([]);
    setFields([]);
    setProductIdentifierMode("");
    setAttributes({});
    setCustomAttributeFields({});
    setShowSecondaryAttributes(false);
    setVersionId("");
    setUploadedImages([]);
    setBatchId("");
    setDrafts([]);
    setKeywordIntelligence(null);
    setSelectedDraftIds([]);
    setMessage(
      `Datos de la versión ${version.version_number} recuperados. Podés cambiar el título y buscar otra categoría sin restricciones.`
    );
  }

  async function findCategorySuggestions() {
    if (!accountId) throw new Error("Seleccioná una cuenta de Mercado Libre.");
    if (!form.name.trim() && !form.title.trim()) {
      throw new Error("Ingresá el nombre o título descriptivo del producto antes de buscar categorías.");
    }
    const query = [form.title || form.name, form.brand, form.model, form.characteristics]
      .map(value => value.trim())
      .filter(Boolean)
      .join(" ");
    const result = await api<CategorySuggestion[]>(
      `/api/catalog/category-suggestions?account_id=${encodeURIComponent(accountId)}&q=${encodeURIComponent(query)}&limit=8`
    );
    setCategorySuggestions(result);
    setCategoryId("");
    setSelectedCategoryName("");
    if (result.length === 0) throw new Error("Mercado Libre no devolvió categorías sugeridas para estos datos.");
    setMessage("Mercado Libre devolvió categorías candidatas. Confirmá la categoría final correcta.");
  }

  function chooseCategory(suggestion: CategorySuggestion) {
    setCategoryId(suggestion.category_id);
    setSelectedCategoryName(suggestion.category_name);
    setMessage(`Categoría hoja seleccionada: ${suggestion.category_name}.`);
  }

  async function connectOAuth() {
    const result = await api<{authorization_url: string}>("/api/accounts/oauth/start");
    window.location.assign(result.authorization_url);
  }

  async function createManualAccount() {
    if (!manualAccount.nickname.trim() || !manualAccount.token.trim()) {
      throw new Error("Completá el nombre y el access token.");
    }
    const result = await api<Account>("/api/accounts", {
      method: "POST",
      body: JSON.stringify({
        nickname: manualAccount.nickname.trim(),
        access_token: manualAccount.token.trim(),
        site_id: "MLA"
      })
    });
    setManualAccount({nickname: "", token: ""});
    setAccountModal(false);
    setManualMode(false);
    await refreshAccounts();
    setAccountId(result.id);
    setMessage(`Cuenta ${result.nickname} conectada.`);
  }

  async function savePricingProfile() {
    const saved = await api<any>("/api/pricing/profile", {
      method: "PUT",
      body: JSON.stringify(pricingProfile),
    });
    setPricingConfigured(true);
    setPricingProfile({
      name: saved.name, channel: saved.channel, currency_id: saved.currency_id,
      target_margin_pct: Number(saved.target_margin_pct), minimum_margin_pct: Number(saved.minimum_margin_pct),
      vat_rate_pct: Number(saved.vat_rate_pct), iibb_rate_pct: Number(saved.iibb_rate_pct),
      ads_rate_pct: Number(saved.ads_rate_pct), refund_rate_pct: Number(saved.refund_rate_pct),
      monthly_units_projection: saved.monthly_units_projection, rounding_step: Number(saved.rounding_step),
      components: (saved.components || []).map((component:any) => ({
        name: component.name, kind: component.kind, value: Number(component.value), basis: component.basis, active: Boolean(component.active)
      })),
    });
    setMessage("Configuración económica guardada.");
  }

  async function simulateCurrentPrice() {
    if (!pricingConfigured) throw new Error("Configurá primero Costos y rentabilidad.");
    const listingTypeId = commercialAllocations[0]?.listing_type_id;
    if (!accountId || !categoryId || !listingTypeId) {
      throw new Error("Elegí cuenta, categoría y una modalidad comercial antes de calcular.");
    }
    const result = await api<any>("/api/pricing/simulate", {
      method: "POST",
      body: JSON.stringify({
        account_id: accountId,
        category_id: categoryId,
        listing_type_id: listingTypeId,
        product_cost: Number(productCost),
        sale_price: Number(form.price) > 0 ? Number(form.price) : null,
        additional_unit_costs: Number(additionalUnitCost) > 0
          ? [{name: "Otros costos directos del producto", amount: Number(additionalUnitCost)}]
          : [],
        package: {
          dimensions: simulationPackage.dimensions || null,
          weight: simulationPackage.weight ? Number(simulationPackage.weight) : null,
          logistic_type: simulationPackage.logisticType || null,
          shipping_mode: simulationPackage.shippingMode || null,
        },
      }),
    });
    setPricingAnalysis({calculation_version: "pricing_v2_economic", ...result});
  }

  function transferRecommendedPrice(price: number, calculation: PricingCalculation) {
    setForm(previous => ({...previous, price: String(price)}));
    setPricingAnalysis({
      calculation_version: "pricing_v2_economic",
      scenario: calculation.scenario,
      scenario_units: calculation.scenarioUnits,
      recommended_price: price,
      analyzed: {
        net_cmv: calculation.analyzed.netCmv,
        contribution_margin: calculation.analyzed.contributionMargin,
        contribution_margin_pct: calculation.analyzed.contributionMarginPct,
      },
      mc0: {gross_price: calculation.mc0.grossPrice},
      mc15: {gross_price: calculation.mc15.grossPrice},
      mc20: {gross_price: calculation.mc20.grossPrice},
    });
    setActiveView("publisher");
    setMessage("Precio recomendado transferido al formulario. Todavía no se creó ninguna publicación.");
  }

  function addQuantityPriceTier() {
    if (quantityPrices.length >= 5) return;
    const previousQuantity = quantityPrices.length ? quantityPrices[quantityPrices.length - 1].min_purchase_unit : 1;
    const previousPrice = quantityPrices.length ? quantityPrices[quantityPrices.length - 1].amount : Number(form.price || 0);
    setQuantityPrices(current => [...current, {
      min_purchase_unit: previousQuantity + 1,
      amount: previousPrice > 0 ? Math.max(0.01, Math.round(previousPrice * 0.95 * 100) / 100) : 0,
    }]);
  }

  function updateQuantityPriceTier(index: number, patch: Partial<QuantityPriceTier>) {
    setQuantityPrices(current => current.map((tier, position) => position === index ? {...tier, ...patch} : tier));
  }

  function removeQuantityPriceTier(index: number) {
    setQuantityPrices(current => current.filter((_, position) => position !== index));
  }

  function currentProductAttributes() {
    return {
      ...attributes,
      ...(form.brand.trim() ? {BRAND: form.brand.trim()} : {}),
      ...(form.model.trim() ? {MODEL: form.model.trim()} : {}),
    };
  }

  function currentCommercialContract() {
    return {
      buying_mode: "buy_it_now",
      warranty: {
        type: form.warrantyType,
        duration: form.warrantyType === "SELLER" ? Number(form.warrantyDuration) : 0,
        unit: form.warrantyUnit,
      },
      quantity_prices: quantityPricingEnabled ? quantityPrices.map(tier => ({
        min_purchase_unit: Number(tier.min_purchase_unit),
        amount: Number(tier.amount),
      })) : [],
      pricing_analysis: pricingAnalysis,
    };
  }

  function currentLogisticsContract() {
    return {local_pick_up: form.localPickup};
  }

  async function createProduct() {
    if (!accountId || !categoryId) throw new Error("Elegí cuenta y una categoría hoja sugerida por Mercado Libre.");
    if (!form.sku.trim() || !form.name.trim()) throw new Error("Completá SKU y nombre interno.");
    if (categoryContractLoading) {
      throw new Error("Esperá a que termine de cargar el contrato de categoría de Mercado Libre.");
    }
    if (!requiredAttributesComplete) {
      throw new Error("Completá los atributos obligatorios informados por Mercado Libre.");
    }
    const payload = {
      internal_sku: form.sku.trim(),
      internal_name: form.name.trim(),
      category_id: categoryId,
      title_reference: (form.title || form.name).trim(),
      description: form.description,
      price: Number(form.price),
      quantity: Number(form.quantity),
      condition: "new",
      currency_id: "ARS",
      listing_type_id: null,
      attributes: currentProductAttributes(),
      commercial: currentCommercialContract(),
      logistics: currentLogisticsContract(),
      discovery_context: {
        brand: form.brand.trim(),
        model: form.model.trim(),
        characteristics: form.characteristics.trim(),
      }
    };
    const result = await api<any>("/api/products", {method:"POST", body:JSON.stringify(payload)});
    setVersionId(result.version_id);
    setUploadedImages([]);
    setMessage(
      result.created_master
        ? "Ficha maestra guardada. Ya podés cargar imágenes y definir el lote."
        : `SKU existente: se guardó la versión ${result.version_number} sin bloquear la nueva categoría o el nuevo título.`
    );
  }

  async function saveCorrectionsAndRevalidate() {
    if (!batchId || drafts.length === 0) {
      await createProduct();
      return;
    }
    if (!requiredAttributesComplete) {
      throw new Error("Completá los atributos obligatorios antes de revalidar el lote.");
    }

    const correction = await api<any>(`/api/drafts/batches/${batchId}/product-correction`, {
      method:"POST",
      body:JSON.stringify({
        description: form.description,
        price: Number(form.price),
        quantity: Number(form.quantity),
        attributes: currentProductAttributes(),
        commercial: currentCommercialContract(),
        logistics: currentLogisticsContract(),
      })
    });

    setVersionId(correction.version_id);
    setUploadedImages((correction.images || []) as UploadedImage[]);

    const validation = await api<any>(`/api/drafts/batches/${batchId}/validate`, {method:"POST"});
    await loadBatch(batchId);
    setMessage(
      `Correcciones guardadas en la versión ${correction.version_number}. ` +
      `${validation.ready} borrador(es) listos y ${validation.invalid} con observaciones. No fue necesario regenerar el lote.`
    );
  }

  async function refreshUploadedImages(currentVersionId = versionId) {
    if (!currentVersionId) {
      setUploadedImages([]);
      return [];
    }
    const version = await api<any>(`/api/products/versions/${currentVersionId}`);
    const confirmed = (version.images || []) as UploadedImage[];
    setUploadedImages(confirmed);
    return confirmed;
  }

  async function uploadImages(files: FileList | null) {
    if (!files || !versionId) return;
    setImageUploadBusy(true);
    try {
      let uploaded = 0;
      for (const file of Array.from(files)) {
        const fd = new FormData();
        fd.append("file", file);
        await api(`/api/products/versions/${versionId}/images`, {method:"POST", body:fd});
        uploaded += 1;
      }
      const confirmed = await refreshUploadedImages(versionId);
      setMessage(`${uploaded} imagen(es) cargadas y ${confirmed.length} confirmadas por el backend.`);
    } finally {
      setImageUploadBusy(false);
    }
  }

  function updateCommercialAllocation(commercialIntent: string, raw: string) {
    const count = Math.max(0, Number(raw) || 0);
    setCommercialAllocations(rows => rows.map(
      row => row.commercial_intent === commercialIntent ? {...row, count} : row
    ));
  }

  async function generateDrafts() {
    if (distributionInvalid) {
      throw new Error("La distribución comercial debe sumar exactamente el total de publicaciones.");
    }
    const confirmedImages = await refreshUploadedImages();
    if (confirmedImages.length === 0) {
      throw new Error("Las imágenes seleccionadas todavía no fueron cargadas al backend. Cargá al menos una imagen válida antes de generar borradores.");
    }
    setGenerationActive(true);
    try {
      const distribution = commercialAllocations
        .filter(row => row.count > 0)
        .map(row => ({commercial_intent: row.commercial_intent, count: row.count}));
      const result = await api<any>("/api/drafts/generate", {
        method:"POST",
        body:JSON.stringify({
          product_version_id: versionId,
          account_id: accountId,
          count: totalCount,
          commercial_distribution: distribution
        })
      });
      setBatchId(result.batch_id);
      await loadBatch(result.batch_id);
      setMessage(`${result.count} borradores generados con condiciones comerciales confirmadas por Mercado Libre.`);
    } finally {
      setGenerationActive(false);
    }
  }

  async function loadBatch(id = batchId) {
    if (!id) return;
    const result = await api<any>(`/api/drafts/batches/${id}`);
    setDrafts(result.drafts);
    setKeywordIntelligence(result.keyword_intelligence || null);
    setSelectedDraftIds(current => current.filter(draftId => result.drafts.some((draft: Draft) => draft.id === draftId)));
  }

  async function validateDraft(id: string) {
    await api(`/api/drafts/${id}/validate`, {method:"POST"});
    await loadBatch();
  }

  async function approveDraft(id: string) {
    await api(`/api/drafts/${id}/approve`, {method:"POST"});
    await loadBatch();
  }

  async function validateAll() {
    if (!batchId) return;
    const result = await api<any>(`/api/drafts/batches/${batchId}/validate`, {method:"POST"});
    await loadBatch(batchId);
    setMessage(`${result.ready} borrador(es) listos y ${result.invalid} con observaciones después de validar el lote.`);
  }

  async function approveReady() {
    for (const d of drafts.filter(x => x.status === "READY")) {
      await api(`/api/drafts/${d.id}/approve`, {method:"POST"});
    }
    await loadBatch();
  }

  function watchJob(jobId: string) {
    const es = jobEvents(jobId);
    let pollingTimer: number | null = null;

    const applyJobState = (data: any) => {
      setJob({...data, job_id: jobId});
      if (TERMINAL_JOB_STATES.includes(data.status)) {
        es.close();
        if (pollingTimer !== null) window.clearInterval(pollingTimer);
        setSelectedDraftIds([]);
        loadBatch();
        return true;
      }
      return false;
    };

    const startPollingFallback = () => {
      if (pollingTimer !== null) return;
      pollingTimer = window.setInterval(async () => {
        try {
          const data = await api<any>(`/api/jobs/${jobId}`);
          applyJobState(data);
        } catch {
          // Keep the last known state. The next polling interval retries automatically.
        }
      }, 1500);
    };

    es.addEventListener("progress", (event: MessageEvent) => {
      const data = JSON.parse(event.data);
      applyJobState(data);
    });
    es.onerror = () => {
      es.close();
      startPollingFallback();
      setMessage("Se interrumpió SSE; el progreso continúa actualizándose por polling.");
    };
    return es;
  }

  async function startJob() {
    if (!selectedApprovedDraftIds.length) {
      throw new Error("Seleccioná al menos un borrador APPROVED para publicar.");
    }
    const result = await api<any>("/api/publication/jobs", {
      method:"POST",
      body:JSON.stringify({batch_id: batchId, draft_ids: selectedApprovedDraftIds})
    });
    setJob(result);
    watchJob(result.job_id);
  }

  async function cancelPendingJob() {
    const id = job?.job_id || job?.id;
    if (!id) return;
    const cancelled = await api<any>(`/api/jobs/${id}/cancel`, {method:"POST"});
    setJob({...cancelled, job_id:id});
    setMessage("Job pendiente cancelado. Ningún borrador de ese job será reclamado por el worker.");
  }

  function toggleDraftSelection(draftId: string) {
    setSelectedDraftIds(current =>
      current.includes(draftId)
        ? current.filter(id => id !== draftId)
        : [...current, draftId]
    );
  }

  function toggleAllApprovedDrafts() {
    const approvedSet = new Set(approvedDraftIds);
    setSelectedDraftIds(current => {
      if (allApprovedSelected) {
        return current.filter(id => !approvedSet.has(id));
      }
      return Array.from(new Set([...current, ...approvedDraftIds]));
    });
  }

  async function exportExcel() {
    if (!job?.job_id && !job?.id) return;
    const id = job.job_id || job.id;
    await downloadFile(`/api/publication/jobs/${id}/export.xlsx`, `publicaciones_ml_${id}.xlsx`);
  }

  async function run<T>(fn: () => Promise<T>) {
    setBusy(true); setMessage("");
    try { await fn(); } catch (e:any) { setMessage(e.message); }
    finally { setBusy(false); }
  }

  function attributeHasValue(field: Field) {
    return attributeValuePresent(attributes[field.id]);
  }

  function renderAttributeField(field: Field, required = false) {
    const current = attributes[field.id];
    const usingCustom = Boolean(field.allow_custom_value) && (
      Boolean(customAttributeFields[field.id])
      || (typeof current === "string" && current.trim() !== "" && Boolean(field.values?.length))
    );
    const selectedValue = typeof current === "object"
      ? String(current?.value_id || current?.value_name || "")
      : usingCustom ? "__custom__" : "";
    const helper = field.hint || (field.is_measurement ? "Ingresá el valor con la unidad que corresponda según Mercado Libre." : "");

    return <label key={field.id} className={`attributeField ${attributeHasValue(field) ? "completed" : ""}`}>
      <span className="attributeLabel">{field.label}{required && <b className="required"> *</b>}</span>
      {field.is_measurement ? (() => {
        const parts = measurementParts(current, field);
        const units = field.allowed_units || [];
        const commit = (numberText: string, unit: string) => {
          setAttributes({...attributes, [field.id]: buildMeasurementValue(numberText, unit)});
        };
        return <div className="measurementInput">
          <input
            inputMode="decimal"
            placeholder="Valor"
            value={parts.number}
            onChange={e=>commit(e.target.value, parts.unit)}
          />
          <select value={parts.unit} onChange={e=>commit(parts.number, e.target.value)}>
            {!parts.unit && <option value="">Unidad…</option>}
            {units.map(unit=><option key={String(unit.id || unit.name)} value={String(unit.id || unit.name)}>{unit.name}</option>)}
          </select>
        </div>;
      })() : field.is_boolean && !field.values?.length ? (
        <select value={typeof current === "object" ? String(current?.value_name || "") : String(current || "")} onChange={e=>{
          const value = e.target.value;
          setAttributes({...attributes, [field.id]: value ? {value_name:value} : null});
        }}>
          <option value="">Seleccionar…</option>
          <option value="Sí">Sí</option>
          <option value="No">No</option>
        </select>
      ) : field.values?.length ? (
        <>
          <select value={selectedValue} onChange={e=>{
            if (e.target.value === "__custom__") {
              setCustomAttributeFields({...customAttributeFields, [field.id]: true});
              setAttributes({...attributes, [field.id]: ""});
              return;
            }
            const selected = field.values.find(v=>String(v.id || v.name) === e.target.value);
            setCustomAttributeFields({...customAttributeFields, [field.id]: false});
            setAttributes({...attributes, [field.id]: selected ? {value_id:selected.id, value_name:selected.name} : null});
          }}>
            <option value="">Seleccionar…</option>
            {field.values.slice(0,250).map(v=><option key={String(v.id||v.name)} value={String(v.id||v.name)}>{v.name}</option>)}
            {field.allow_custom_value && <option value="__custom__">Otro valor…</option>}
          </select>
          {field.allow_custom_value && usingCustom && <input
            autoFocus
            maxLength={field.value_max_length || undefined}
            placeholder="Escribir valor manualmente"
            value={typeof current === "string" ? current : ""}
            onChange={e=>setAttributes({...attributes,[field.id]:e.target.value})}
          />}
        </>
      ) : (
        <input
          maxLength={field.value_max_length || undefined}
          value={typeof current === "string" ? current : ""}
          onChange={e=>setAttributes({...attributes,[field.id]:e.target.value})}
        />
      )}
      {helper && <small className="helper">{helper}</small>}
      {field.attribute_group_name && <small className="attributeMeta">{field.attribute_group_name}</small>}
    </label>;
  }

  function renderProductIdentifierRequirement() {
    const gtinField = fields.find(field => field.id === GTIN_ATTRIBUTE_ID);
    if (!gtinField) return null;

    const reasonField = fields.find(field => field.id === EMPTY_GTIN_REASON_ATTRIBUTE_ID);
    if (!productIdentifierContract || !reasonField) {
      return <div className="identifierContract identifierContractError">
        <div className="identifierContractHeader">
          <div>
            <h3>Código universal del producto</h3>
            <p className="helper blockHelper">La metadata recibida no permite resolver todavía el contrato GTIN / sin GTIN. Actualizá la categoría antes de guardar la ficha.</p>
          </div>
          <span className="contractPending">Contrato incompleto</span>
        </div>
      </div>;
    }

    const group = requirements.find(requirement => requirement.id === "GTIN_OR_EMPTY_REASON");
    const gtinPresent = attributeValuePresent(attributes[GTIN_ATTRIBUTE_ID]);
    const reasonPresent = attributeValuePresent(attributes[EMPTY_GTIN_REASON_ATTRIBUTE_ID]);
    const identifierComplete = (plausibleGtin(attributes[GTIN_ATTRIBUTE_ID]) && !reasonPresent)
      || (!gtinPresent && optionMatches(attributes[EMPTY_GTIN_REASON_ATTRIBUTE_ID], reasonField.values));

    const mode = productIdentifierMode;

    const selectMode = (nextMode: "GTIN" | "NO_GTIN") => {
      setProductIdentifierMode(nextMode);
      setAttributes(current => {
        if (nextMode === "GTIN") {
          return {...current, [EMPTY_GTIN_REASON_ATTRIBUTE_ID]: null};
        }
        return {...current, [GTIN_ATTRIBUTE_ID]: null};
      });
    };

    return <div className="identifierContract">
      <div className="identifierContractHeader">
        <div>
          <h3>Código universal del producto</h3>
          <p className="helper blockHelper">Informá un GTIN/EAN real. Si el producto no tiene código universal, elegí el motivo correspondiente; nunca uses el SKU ni valores como 0 u “Otros” como GTIN.</p>
        </div>
        <span className={identifierComplete ? "contractComplete" : "contractPending"}>{identifierComplete ? "Completo" : "Obligatorio"}</span>
      </div>
      <div className="identifierChoice">
        <label className={`choiceCard ${mode === "GTIN" ? "selected" : ""}`}>
          <input type="radio" name="gtin-mode" checked={mode === "GTIN"} onChange={()=>selectMode("GTIN")}/>
          <span><b>Tengo código universal</b><small>Ingresá el GTIN/EAN real del producto.</small></span>
        </label>
        <label className={`choiceCard ${mode === "NO_GTIN" ? "selected" : ""}`}>
          <input type="radio" name="gtin-mode" checked={mode === "NO_GTIN"} onChange={()=>selectMode("NO_GTIN")}/>
          <span><b>No tiene código universal</b><small>Mercado Libre requiere indicar el motivo.</small></span>
        </label>
      </div>
      {mode === "GTIN" && <div className="identifierInput">{renderAttributeField(gtinField, true)}</div>}
      {mode === "NO_GTIN" && <div className="identifierInput">{renderAttributeField(reasonField, true)}</div>}
      {mode === "NO_GTIN" && productIdentifierContract.empty_reason_source === "provider_contract_fallback" &&
        <p className="helper identifierSource">Mercado Libre no expuso este selector en la metadata de la categoría; la app usa el contrato general vigente del marketplace.</p>}
      {group?.message && <p className="helper identifierHelper">{group.message}</p>}
    </div>;
  }

  return (
    <div className="app">
      <aside>
        <div className="brand">Publicador ML</div>
        <div className="muted">Gestión masiva de publicaciones</div>
        <div className="viewSwitch pricingViewSwitch">
          <button className={activeView === "publisher" ? "active" : ""} onClick={()=>setActiveView("publisher")}>Publicador</button>
          <button className={activeView === "pricing-settings" ? "active" : ""} onClick={()=>setActiveView("pricing-settings")}>Configuración</button>
          <button className={activeView === "price-calculator" ? "active" : ""} onClick={()=>setActiveView("price-calculator")}>Calculadora</button>
        </div>
        <nav className="sideSteps">
          <div className={contextComplete ? "done" : "active"}><span>1</span> Producto y categoría</div>
          <div className={productComplete ? "done" : contextComplete ? "active" : ""}><span>2</span> Ficha técnica</div>
          <div className={draftsComplete ? "done" : productComplete ? "active" : ""}><span>3</span> Lote y cuotas</div>
          <div className={approvedCount ? "done" : draftsComplete ? "active" : ""}><span>4</span> Revisión</div>
          <div className={terminalJob ? "done" : approvedCount ? "active" : ""}><span>5</span> Publicación</div>
        </nav>
        <div className="status">
          <span className="dot"/> Publicación real protegida por configuración
        </div>
      </aside>

      <main style={{display: activeView === "pricing-settings" ? undefined : "none"}}>
        {message && <div className="notice">{message}</div>}
        <PricingProfileEditor profile={pricingProfile} busy={busy} onChange={setPricingProfile} onSave={() => run(savePricingProfile)} />
      </main>

      <main style={{display: activeView === "price-calculator" ? undefined : "none"}}>
        {message && <div className="notice">{message}</div>}
        <PriceCalculator accountId={accountId} onUseRecommendedPrice={transferRecommendedPrice} />
      </main>

      <main style={{display: activeView === "publisher" ? undefined : "none"}}>
        <header>
          <div>
            <h1>Nueva publicación masiva</h1>
            <p>Prepará la ficha una vez, generá publicaciones independientes y controlá todo el lote antes de publicar.</p>
          </div>
          <button className="secondary" onClick={() => setAccountModal(true)}>+ Conectar cuenta</button>
        </header>

        <section className="summaryBar">
          <div><span>Cuenta</span><b>{selectedAccount?.nickname || "Sin seleccionar"}</b></div>
          <div><span>Categoría</span><b>{selectedCategoryName || "Sin seleccionar"}</b></div>
          <div><span>Ficha</span><b className={versionId ? "ok" : ""}>{versionId ? "Guardada" : "Pendiente"}</b></div>
          <div><span>Borradores</span><b>{drafts.length}</b></div>
        </section>

        {message && <div className="notice">{message}</div>}

        <section className="card">
          <div className="sectionTitle"><span>1</span> Producto y categoría</div>
          <div className="grid2">
            <label>Cuenta
              <select value={accountId} onChange={e=>setAccountId(e.target.value)}>
                <option value="">Seleccionar…</option>
                {accounts.map(a=><option key={a.id} value={a.id}>{a.nickname} {a.seller_id ? `· ${a.seller_id}`:""}</option>)}
              </select>
              {selectedAccount && <small className="helper">{selectedAccount.auth_status.replaceAll("_", " ")} · {selectedAccount.site_id}</small>}
            </label>
          </div>

          <div className="attributeHeader">
            <div>
              <h3>Información básica del producto</h3>
              <p className="helper blockHelper">Mercado Libre utiliza estos datos para sugerir la categoría final. No elegimos una categoría padre manualmente.</p>
            </div>
          </div>
          <div className="grid3">
            <label>SKU<input disabled={!accountId} value={form.sku} onChange={e=>{setForm({...form,sku:e.target.value}); setDismissedExistingSku("");}}/>
              {skuLookupBusy && <small className="helper">Buscando ficha guardada…</small>}
            </label>
            <label>Nombre del producto<input disabled={!accountId} value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
            <label>Título descriptivo<input disabled={!accountId} value={form.title} onChange={e=>setForm({...form,title:e.target.value})}/></label>
            <label>Marca<input disabled={!accountId} value={form.brand} onChange={e=>setForm({...form,brand:e.target.value})}/></label>
            <label>Modelo<input disabled={!accountId} value={form.model} onChange={e=>setForm({...form,model:e.target.value})}/></label>
            <label>Características conocidas<input disabled={!accountId} value={form.characteristics} onChange={e=>setForm({...form,characteristics:e.target.value})}/></label>
          </div>

          {existingProduct && dismissedExistingSku !== form.sku.trim() && <div className="existingSkuNotice">
            <div>
              <b>Este SKU ya tiene una ficha guardada.</b>
              <span>Última versión: {existingProduct.latest_version.version_number}. Podés recuperar sus datos o seguir escribiendo normalmente. El SKU no limita el título ni la categoría.</span>
            </div>
            <div className="existingSkuActions">
              <button type="button" className="secondary" onClick={loadExistingProduct}>Cargar datos guardados</button>
              <button type="button" className="textButton" onClick={()=>setDismissedExistingSku(form.sku.trim())}>Seguir sin cargar</button>
            </div>
          </div>}

          <button disabled={!accountId || busy || (!form.name.trim() && !form.title.trim())} onClick={()=>run(findCategorySuggestions)}>Buscar categorías en Mercado Libre</button>

          {categorySuggestions.length > 0 && <div className="categorySuggestions">
            <h3>Categorías sugeridas</h3>
            <p className="helper">Confirmá la categoría hoja que corresponde al producto. La ficha técnica se cargará recién después de esta selección.</p>
            <div className="categorySuggestionList">
              {categorySuggestions.map(suggestion => <button
                type="button"
                key={suggestion.category_id}
                className={`categorySuggestion ${categoryId === suggestion.category_id ? "selected" : ""}`}
                onClick={()=>chooseCategory(suggestion)}
              >
                <b>{suggestion.category_name}</b>
                {suggestion.domain_name && <small>{suggestion.domain_name}</small>}
                <span>{suggestion.category_id}</span>
              </button>)}
            </div>
          </div>}

          <TitleAssistant
            accountId={accountId}
            categoryId={categoryId}
            productText={form.title || form.name}
            attributes={currentProductAttributes()}
            maxLength={titleMaxLength}
            onUseTitle={(title) => setForm(current => ({...current, title}))}
          />
        </section>

        <section className={`card ${!contextComplete ? "locked" : ""}`}>
          <div className="sectionTitle"><span>2</span> Ficha técnica</div>
          {!contextComplete && <div className="lockedMessage">Ingresá el producto, buscá categorías y confirmá una categoría hoja para continuar.</div>}
          <div className="grid3">
            <label>Precio ARS<input disabled={!contextComplete} type="number" value={form.price} onChange={e=>setForm({...form,price:e.target.value})}/></label>
            <label>Stock<input disabled={!contextComplete} type="number" value={form.quantity} onChange={e=>setForm({...form,quantity:e.target.value})}/></label>
          </div>
          <div className="economicSimulator">
            <div className="economicSimulatorHeader">
              <div><h3>Análisis económico</h3><p className="helper blockHelper">Usa la Calculadora de Precio con costos configurados y la tarifa/logística real de Mercado Libre.</p></div>
              {!pricingConfigured && <button type="button" className="secondary" onClick={()=>setActiveView("pricing-settings")}>Configurar costos</button>}
            </div>
            <div className="grid3">
              <label>Costo del producto<input disabled={!contextComplete} type="number" min="0" step="0.01" value={productCost} onChange={e=>setProductCost(e.target.value)}/></label>
              <label>Otros costos netos / unidad<input disabled={!contextComplete} type="number" min="0" step="0.01" value={additionalUnitCost} onChange={e=>setAdditionalUnitCost(e.target.value)}/></label>
              <label>Modalidad ML<input disabled value={commercialAllocations[0]?.listing_type_name || "Pendiente de resolver"}/></label>
            </div>
            <div className="grid4">
              <label>Dimensiones<input disabled={!contextComplete} value={simulationPackage.dimensions} onChange={e=>setSimulationPackage({...simulationPackage, dimensions:e.target.value})} placeholder="30x20x10"/></label>
              <label>Peso<input disabled={!contextComplete} type="number" min="0" step="0.01" value={simulationPackage.weight} onChange={e=>setSimulationPackage({...simulationPackage, weight:e.target.value})}/></label>
              <label>Tipo logístico<input disabled={!contextComplete} value={simulationPackage.logisticType} onChange={e=>setSimulationPackage({...simulationPackage, logisticType:e.target.value})} placeholder="drop_off"/></label>
              <label>Modo de envío<input disabled={!contextComplete} value={simulationPackage.shippingMode} onChange={e=>setSimulationPackage({...simulationPackage, shippingMode:e.target.value})} placeholder="me2"/></label>
            </div>
            <button type="button" className="secondary" disabled={!contextComplete || !pricingConfigured || busy} onClick={()=>run(simulateCurrentPrice)}>Calcular rentabilidad</button>
            {pricingAnalysis && <div className="pricingResults">
              <div><span>CMV neto</span><b>{money(pricingAnalysis.analyzed.net_cmv)}</b></div>
              <div><span>MC 0%</span><b>{money(pricingAnalysis.mc0.gross_price)}</b></div>
              <div><span>MC 15%</span><b>{money(pricingAnalysis.mc15.gross_price)}</b></div>
              <div><span>MC 20%</span><b>{money(pricingAnalysis.mc20.gross_price)}</b></div>
              <div className="recommended"><span>Sugerido</span><b>{money(pricingAnalysis.recommended_price)}</b></div>
              <div className="priceHealth"><span>Margen analizado</span><b>{pricingAnalysis.analyzed.contribution_margin_pct}%</b><small>{money(pricingAnalysis.analyzed.contribution_margin)}</small></div>
              <button type="button" onClick={()=>setForm({...form,price:String(pricingAnalysis.recommended_price)})}>Usar precio sugerido</button>
            </div>}
          </div>

          <div className="quantityPricingBox">
            <label className="checkboxLabel"><input type="checkbox" disabled={!contextComplete} checked={quantityPricingEnabled} onChange={e=>setQuantityPricingEnabled(e.target.checked)}/> Publicar precios mayoristas B2B por cantidad</label>
            <p className="helper blockHelper">Mercado Libre habilita PxQ B2B sólo para vendedores seleccionados. La publicación principal no se pierde si ML rechaza la tabla mayorista; el job lo informa como advertencia.</p>
            {quantityPricingEnabled && <>
              <div className="quantityPriceRows">
                {quantityPrices.map((tier,index)=><div className="quantityPriceRow" key={index}>
                  <label>Desde<input type="number" min="2" value={tier.min_purchase_unit} onChange={e=>updateQuantityPriceTier(index,{min_purchase_unit:Number(e.target.value)})}/></label>
                  <label>Precio unitario ARS<input type="number" min="0.01" step="0.01" value={tier.amount} onChange={e=>updateQuantityPriceTier(index,{amount:Number(e.target.value)})}/></label>
                  {pricingAnalysis && <span className={Number(tier.amount) < Number(pricingAnalysis.mc0.gross_price) ? "tierRisk bad" : "tierRisk ok"}>{Number(tier.amount) < Number(pricingAnalysis.mc0.gross_price) ? "Debajo del piso MC 0%" : "Sobre el piso MC 0%"}</span>}
                  <button type="button" className="tiny dangerButton" onClick={()=>removeQuantityPriceTier(index)}>Eliminar</button>
                </div>)}
              </div>
              <button type="button" className="secondary" disabled={quantityPrices.length >= 5} onClick={addQuantityPriceTier}>+ Agregar escalón mayorista</button>
              <small className="helper">Máximo 5 escalones. La cantidad mínima debe ser mayor a 1 y el precio unitario debe bajar al aumentar la cantidad.</small>
            </>}
          </div>
          <label>Descripción<textarea disabled={!contextComplete} value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/></label>
          <div className="grid3">
            <label className="checkboxLabel">
              <input
                type="checkbox"
                disabled={!contextComplete}
                checked={form.localPickup}
                onChange={e=>setForm({...form, localPickup:e.target.checked})}
              />
              Permitir retiro en persona
            </label>
            <label>Garantía
              <select disabled={!contextComplete} value={form.warrantyType} onChange={e=>setForm({...form,warrantyType:e.target.value})}>
                <option value="SELLER">Garantía del vendedor</option>
                <option value="NONE">Sin garantía</option>
              </select>
            </label>
            {form.warrantyType === "SELLER" && <label>Duración de garantía
              <div className="inlineWarranty">
                <input type="number" min="1" disabled={!contextComplete} value={form.warrantyDuration} onChange={e=>setForm({...form,warrantyDuration:e.target.value})}/>
                <select disabled={!contextComplete} value={form.warrantyUnit} onChange={e=>setForm({...form,warrantyUnit:e.target.value})}>
                  <option value="days">días</option>
                  <option value="months">meses</option>
                  <option value="years">años</option>
                </select>
              </div>
            </label>}
          </div>

          {contextComplete && <>
            {renderProductIdentifierRequirement()}
            <div className="attributeHeader">
              <div>
                <h3>Datos imprescindibles</h3>
                <p className="helper blockHelper">Son los atributos que Mercado Libre marca como necesarios para esta categoría hoja.</p>
              </div>
              <div className="attributeProgress">
                {completedRequiredFields + (requiredGroupsComplete ? requirements.filter(group => group.required).length : 0)}/{requiredFields.length + requirements.filter(group => group.required).length} obligatorios completos
              </div>
            </div>

            {requiredFields.length > 0 ? (
              <div className="grid3">{requiredFields.map(field => renderAttributeField(field, true))}</div>
            ) : (
              <div className="optionalNotice">Mercado Libre no informó atributos manuales obligatorios adicionales para esta categoría.</div>
            )}

            {recommendedFields.length > 0 && <>
              <div className="attributeHeader qualityHeader">
                <div>
                  <h3>Completar para mejorar la publicación</h3>
                  <p className="helper blockHelper">Mostramos señales de calidad de la metadata oficial: atributos relevantes, medidas y características Sí/No. No bloquean el guardado salvo que Mercado Libre también los marque como obligatorios.</p>
                </div>
                <div className="attributeProgress qualityProgress">
                  {completedRecommendedFields}/{recommendedFields.length} completados
                </div>
              </div>
              <div className="grid3 recommendedGrid">{recommendedFields.map(field => renderAttributeField(field))}</div>
            </>}

            {secondaryFields.length > 0 && <div className="secondaryAttributes">
              <button type="button" className="secondary optionalToggle" onClick={()=>setShowSecondaryAttributes(value=>!value)}>
                {showSecondaryAttributes ? "Ocultar" : "Mostrar"} más características ({secondaryFields.length})
              </button>
              <span className="helper">Características secundarias disponibles en la categoría.</span>
              {showSecondaryAttributes && <div className="grid3 secondaryGrid">{secondaryFields.map(field => renderAttributeField(field))}</div>}
            </div>}
          </>}
          <button
            disabled={!contextComplete || categoryContractLoading || !requiredAttributesComplete || busy}
            onClick={()=>run(batchId && drafts.length > 0 ? saveCorrectionsAndRevalidate : createProduct)}
          >
            {batchId && drafts.length > 0
              ? "Guardar correcciones y revalidar lote"
              : existingProduct ? "Guardar nueva versión" : "Guardar ficha"}
          </button>
          {batchId && drafts.length > 0 && <p className="helper blockHelper">
            Si la validación detecta un dato faltante, completalo acá y guardá las correcciones. La app crea un nuevo snapshot de la ficha, conserva los borradores e imágenes y vuelve a validar el lote sin recargar la página.
          </p>}
        </section>

        <section className={`card ${!productComplete ? "locked" : ""}`}>
          <div className="sectionTitle"><span>3</span> Imágenes y plan del lote</div>
          {!productComplete && <div className="lockedMessage">Guardá la ficha maestra para definir el lote.</div>}
          <div className="grid2">
            <label>Imágenes
              <input type="file" accept="image/jpeg,image/png" multiple disabled={!versionId || imageUploadBusy}
                onChange={e=>run(()=>uploadImages(e.target.files))}/>
              <small>Mercado Libre: mínimo 500 px por lado. Recomendado: 1200 × 1200 px. Formatos admitidos por la app: JPG/JPEG y PNG.</small>
              <span className={`uploadConfirmation ${uploadedImages.length ? "ok" : "pending"}`}>
                {imageUploadBusy
                  ? "Cargando y validando imágenes…"
                  : uploadedImages.length
                    ? `${uploadedImages.length} imagen(es) confirmadas por el backend`
                    : "Todavía no hay imágenes confirmadas por el backend"}
              </span>
            </label>
            <label>Cantidad total de publicaciones
              <input type="number" min="1" max="100" disabled={!versionId} value={form.count}
                onChange={e=>setForm({...form,count:e.target.value})}/>
            </label>
          </div>

          <div className="installmentBox">
            <div className="installmentHeader">
              <div>
                <h3>Distribución comercial</h3>
                <p>Elegí cuántas publicaciones querés con cuotas y cuántas sin cuotas. El backend resuelve automáticamente el listing type real habilitado por Mercado Libre.</p>
              </div>
              <div className={`allocation ${distributionInvalid ? "bad" : ""}`}>
                {allocatedCount}/{totalCount} asignadas
              </div>
            </div>
            <div className="installmentGrid">
              {commercialAllocations.map(option => <label className={`planCard ${option.commercial_intent === "WITHOUT_INSTALLMENTS" ? "standard" : ""}`} key={option.commercial_intent}>
                <span>{option.label}</span>
                <input
                  disabled={!versionId}
                  type="number"
                  min="0"
                  max={totalCount}
                  value={option.count}
                  onChange={e=>updateCommercialAllocation(option.commercial_intent, e.target.value)}
                />
                <small>Mercado Libre resuelve {option.listing_type_id} ({option.listing_type_name})</small>
              </label>)}
            </div>
            <p className="helper blockHelper">
              En Argentina, Mercado Libre documenta “No agregar cuotas” sobre gold_special y “Agregar cuotas” sobre gold_pro. La app sólo muestra la opción si ML la informó disponible para esta cuenta/categoría.
            </p>
          </div>

          <button disabled={!versionId || busy || distributionInvalid} onClick={()=>run(generateDrafts)}>Generar borradores con IA</button>
        </section>

        {drafts.length > 0 && <section className="card wide">
          <div className="toolbar">
            <div>
              <div className="sectionTitle"><span>4</span> Revisión de borradores</div>
              <p className="sectionSubtitle">{drafts.length} publicaciones · {approvedCount} aprobadas · {selectedApprovedDraftIds.length} seleccionadas para publicar</p>
            </div>
            <div className="actions">
              <button className="secondary" onClick={()=>run(validateAll)}>Validar todos</button>
              <button className="secondary" onClick={()=>run(approveReady)}>Aprobar listos</button>
              <button
                className="secondary"
                disabled={!approvedDraftIds.length || Boolean(job && !terminalJob)}
                onClick={toggleAllApprovedDrafts}
              >
                {allApprovedSelected ? "Deseleccionar aprobados" : `Seleccionar todos aprobados (${approvedDraftIds.length})`}
              </button>
              <button disabled={!selectedApprovedDraftIds.length || Boolean(job && !terminalJob)} onClick={()=>run(startJob)}>Publicar seleccionados ({selectedApprovedDraftIds.length})</button>
            </div>
          </div>
          {keywordIntelligence && <div className="keywordPanel">
            <div>
              <b>Señales usadas para los títulos</b>
              <span>{keywordIntelligence.selected_terms?.join(" · ") || "Sin términos seleccionados"}</span>
            </div>
            <small>Cache: {keywordIntelligence.cache_status || "-"} · Modelo semántico: {keywordIntelligence.semantic_model || "-"}</small>
          </div>}
          <div className="tableWrap">
            <table>
              <thead><tr><th>Publicar</th><th>#</th><th>Título</th><th>Chars</th><th>Modalidad</th><th>Score</th><th>Imgs</th><th>Estado</th><th>Acciones</th></tr></thead>
              <tbody>
                {drafts.map(d=><tr key={d.id}>
                  <td><input className="draftCheckbox" type="checkbox" checked={selectedDraftIds.includes(d.id)} disabled={d.status !== "APPROVED" || Boolean(job && !terminalJob)} onChange={()=>toggleDraftSelection(d.id)}/></td>
                  <td>{d.sequence_number}</td>
                  <td className="titleCell">
                    {d.title}
                    {d.validation?.errors?.length ? <div className="draftValidation errors">
                      {d.validation.errors.map((issue, index) => <span key={`${d.id}-error-${index}`}>
                        <code>{issue.code || "VALIDATION_ERROR"}</code>{issue.field ? ` · ${issue.field}` : ""}: {issue.message || "Validación fallida."}
                      </span>)}
                    </div> : null}
                    {!d.validation?.errors?.length && d.validation?.warnings?.length ? <div className="draftValidation warnings">
                      {d.validation.warnings.map((issue, index) => <span key={`${d.id}-warning-${index}`}>
                        <code>{issue.code || "WARNING"}</code>: {issue.message || "Advertencia de validación."}
                      </span>)}
                    </div> : null}
                  </td>
                  <td><span className={d.title.length >= 54 ? "charCount good" : "charCount"}>{d.title.length}/60</span></td>
                  <td><span className="installmentPill">{d.commercial_config?.commercial_label || d.commercial_config?.listing_type_name || "Mercado Libre"}</span></td>
                  <td><strong>{d.score}</strong></td>
                  <td>{d.image_order.length}</td>
                  <td><span className={`pill ${d.status.toLowerCase()}`}>{d.status}</span></td>
                  <td className="rowActions">
                    <button className="tiny secondary" onClick={()=>run(()=>validateDraft(d.id))}>Validar</button>
                    {d.status==="READY" && <button className="tiny" onClick={()=>run(()=>approveDraft(d.id))}>Aprobar</button>}
                  </td>
                </tr>)}
              </tbody>
            </table>
          </div>
        </section>}

        {job && <section className="card">
          <div className="toolbar executionHeader">
            <div className="sectionTitle"><span>5</span> Ejecución</div>
            {terminalJob && job.succeeded > 0 &&
              <button className="excelButton" onClick={()=>run(exportExcel)}>Descargar Excel MLA + SKU</button>}
          </div>
          <div className="progress"><div style={{width:`${job.progress || 0}%`}}/></div>
          <div className="metrics">
            <div><b>{job.processed || 0}</b><span>Procesados</span></div>
            <div><b>{job.succeeded || 0}</b><span>Publicados</span></div>
            <div><b>{job.failed || 0}</b><span>Errores</span></div>
            <div><b>{job.progress || 0}%</b><span>Progreso</span></div>
          </div>
          <div className="executionStage"><b>{job.current_message || `Estado: ${job.status}`}</b>{job.current_title && <span>{job.current_sequence ? `#${job.current_sequence} · ` : ""}{job.current_title}</span>}<small>Estado técnico: {job.status}{job.current_stage ? ` · ${job.current_stage}` : ""}</small></div>
          {job.warnings?.length > 0 && <div className="jobWarnings">
            <h3>Publicaciones creadas con advertencias</h3>
            {job.warnings.map((warning:any)=><div className="jobWarning" key={warning.job_item_id}>
              <b>{warning.sequence_number ? `#${warning.sequence_number} · ` : ""}{warning.title || "Publicación"}</b>
              <p>{warning.message || "La publicación fue creada, pero una configuración posterior no pudo aplicarse."}</p>
              {warning.http_status && <small>Mercado Libre HTTP {warning.http_status}{warning.provider_error ? ` · ${warning.provider_error}` : ""}</small>}
            </div>)}
          </div>}
          {job.failures?.length > 0 && <div className="jobFailures">
            <h3>Detalle de errores</h3>
            {job.failures.map((failure:any)=><div className="jobFailure" key={failure.job_item_id}>
              <div className="jobFailureHeader">
                <b>{failure.sequence_number ? `#${failure.sequence_number} · ` : ""}{failure.title || "Borrador"}</b>
                {failure.error?.http_status && <span>HTTP {failure.error.http_status}</span>}
              </div>
              <p>{failure.error?.message || failure.error?.code || "La publicación no pudo completarse."}</p>
              {failure.error?.provider_error && <small>Mercado Libre: {failure.error.provider_error}</small>}
              {failure.error?.causes?.length > 0 && <ul>
                {failure.error.causes.map((cause:any, index:number)=><li key={`${failure.job_item_id}-${index}`}>
                  {cause.code && <code>{cause.code}</code>} {cause.field && <strong>{cause.field}: </strong>}{cause.message || "Validación rechazada por Mercado Libre."}
                </li>)}
              </ul>}
            </div>)}
          </div>}
        </section>}
      </main>

      {generationActive && <div className="modalBackdrop progressBackdrop">
        <div className="modal progressModal">
          <div className="spinner"/>
          <h2>Generando borradores</h2>
          <p>El backend está ejecutando el flujo real: tendencias de Mercado Libre → análisis semántico local → generación con IA → validación y ranking de títulos.</p>
          <div className="progressSteps">
            <span>Consultando evidencia de categoría</span>
            <span>Analizando relevancia semántica</span>
            <span>Generando y validando candidatos</span>
          </div>
          <small>No cierres esta ventana. En la primera ejecución el modelo local puede tardar más en cargar.</small>
        </div>
      </div>}

      {job && !terminalJob && <div className="modalBackdrop progressBackdrop">
        <div className="modal progressModal publicationProgressModal">
          <div className="spinner"/>
          <h2>Publicación en curso</h2>
          <p>{job.current_message || "El job fue creado y está esperando ejecución."}</p>
          {job.current_title && <div className="currentPublication">{job.current_sequence ? `#${job.current_sequence} · ` : ""}{job.current_title}</div>}
          <div className="progress"><div style={{width:`${job.progress || 0}%`}}/></div>
          <div className="progressNumbers">{job.processed || 0}/{job.total || 0} procesados · {job.succeeded || 0} publicados · {job.failed || 0} errores</div>
          {job.status === "PENDING" && <>
            <div className={`workerHint ${job.worker?.online === false ? "offline" : ""}`}>
              {job.worker?.online === false
                ? "No hay un worker de publicación activo. El job permanece guardado en PostgreSQL y no se perderá. Reiniciá el backend con python -m app.run."
                : "Servicio de publicación activo. El worker reclamará el job automáticamente."}
            </div>
            <button className="secondary cancelJobButton" onClick={()=>run(cancelPendingJob)}>Cancelar job pendiente</button>
          </>}
        </div>
      </div>}

      {accountModal && <div className="modalBackdrop" onMouseDown={()=>setAccountModal(false)}>
        <div className="modal" onMouseDown={e=>e.stopPropagation()}>
          <button className="modalClose" onClick={()=>setAccountModal(false)}>×</button>
          <div className="modalIcon">ML</div>
          <h2>Conectar Mercado Libre</h2>
          <p>Vinculá una cuenta para consultar su identidad y utilizarla en los lotes de publicación.</p>

          {!manualMode ? <>
            <button className="connectButton" disabled={!oauthStatus?.configured || !oauthStatus?.callback_is_local_publisher || busy} onClick={()=>run(connectOAuth)}>
              Conectar con Mercado Libre
            </button>
            {oauthStatus?.configured && !oauthStatus.callback_is_local_publisher &&
              <div className="oauthNote">
                OAuth está configurado, pero la Redirect URI actual pertenece a la aplicación existente. Para probar este publicador en local podés usar la conexión temporal; el OAuth definitivo ya queda preparado para el callback propio.
              </div>}
            {!oauthStatus?.configured && <div className="oauthNote">OAuth todavía no está completo en la configuración del backend.</div>}
            <button className="linkButton" onClick={()=>setManualMode(true)}>Usar conexión temporal con access token</button>
          </> : <>
            <div className="manualForm">
              <label>Nombre interno
                <input value={manualAccount.nickname} onChange={e=>setManualAccount({...manualAccount,nickname:e.target.value})} placeholder="Ej. SILMAR_BAZAR"/>
              </label>
              <label>Access token
                <input type="password" value={manualAccount.token} onChange={e=>setManualAccount({...manualAccount,token:e.target.value})} placeholder="No se muestra ni queda guardado en el navegador"/>
              </label>
            </div>
            <button disabled={busy} onClick={()=>run(createManualAccount)}>Verificar y conectar</button>
            <button className="linkButton" onClick={()=>setManualMode(false)}>Volver a OAuth</button>
          </>}
        </div>
      </div>}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);

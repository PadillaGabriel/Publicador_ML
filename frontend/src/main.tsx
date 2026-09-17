import React, {useEffect, useMemo, useRef, useState} from "react";
import {createRoot} from "react-dom/client";
import {api, downloadFile, jobEvents, loadReusableTechnicalAttributes, loadShippingCapabilities, previewMlaPublication, resolveMlaPublicationReuse} from "./api";
import {PriceCalculator} from "./pricing/PriceCalculator";
import {PricingProfileEditor} from "./pricing/PricingProfileEditor";
import {normalizeQuantityPricing, type PricingCalculation, type PricingCalculatorPrefill, type PricingProfile, type QuantityPricingAnalysis, type QuantityPricingApiResponse, type ShippingCapabilities} from "./pricing/types";
import {TitleAssistant} from "./title-intelligence/TitleAssistant";
import {applyReusableAttributes} from "./technical-attributes/reuse";
import {buildImportedProductSeed} from "./technical-attributes/publication-import";
import type {MlaPublicationSnapshot, ReuseTechnicalAttributesResult} from "./technical-attributes/types";
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
  conditional_required?: boolean;
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

function publisherPricingTargets(analysis: any) {
  if (!analysis) return [];
  const options = [
    {key: "mc0", label: "MC 0%", target: analysis.mc0},
    {key: "mc15", label: "MC 15%", target: analysis.mc15},
    {key: "mc20", label: "MC 20%", target: analysis.mc20},
  ].filter(option => option.target);

  const recommendedMargin = Number(analysis.audit?.recommended_target_margin_pct);
  const recommendedPrice = Number(analysis.recommended_price);
  const marginVisible = options.some(option => Math.abs(Number(option.target.target_margin_pct) - recommendedMargin) < 0.001);
  if (!marginVisible) {
    const recommendedTarget = [analysis.target, analysis.minimum].find(
      target => target && Math.abs(Number(target.target_margin_pct) - recommendedMargin) < 0.001
    );
    if (recommendedTarget) {
      options.push({key: "recommended", label: `MC ${recommendedMargin}%`, target: recommendedTarget});
    }
  }

  return options.map(option => ({
    ...option,
    recommended: Math.abs(Number(option.target.gross_price) - recommendedPrice) < 0.01,
  }));
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
  const [productMasterId, setProductMasterId] = useState("");
  const [startMode, setStartMode] = useState<"" | "MLA_IMPORT" | "MANUAL">("");
  const [mlaImportId, setMlaImportId] = useState("");
  const [mlaPreview, setMlaPreview] = useState<MlaPublicationSnapshot | null>(null);
  const [technicalReuse, setTechnicalReuse] = useState<ReuseTechnicalAttributesResult | null>(null);
  const [reusedAttributeIds, setReusedAttributeIds] = useState<Set<string>>(new Set());
  const [technicalAttributeBusy, setTechnicalAttributeBusy] = useState(false);
  const attributesRef = useRef<Record<string, any>>({});
  const [dismissedExistingSku, setDismissedExistingSku] = useState("");
  const [skuLookupBusy, setSkuLookupBusy] = useState(false);
  const [commercialAllocations, setCommercialAllocations] = useState<CommercialAllocation[]>([]);
  const [pricingListingTypeId, setPricingListingTypeId] = useState("");
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
  const [pricingAnalysis, setPricingAnalysis] = useState<any>(null);
  const [calculatorPrefill, setCalculatorPrefill] = useState<PricingCalculatorPrefill | null>(null);
  const [simulationPackage, setSimulationPackage] = useState({
    dimensions: "", weight: "", logisticType: "", shippingMode: "", freeShipping: "",
  });
  const [shippingCapabilities, setShippingCapabilities] = useState<ShippingCapabilities | null>(null);
  const [shippingCapabilitiesLoading, setShippingCapabilitiesLoading] = useState(false);
  const [shippingCapabilitiesError, setShippingCapabilitiesError] = useState("");
  const [quantityPricingEnabled, setQuantityPricingEnabled] = useState(false);
  const [quantityPrices, setQuantityPrices] = useState<QuantityPriceTier[]>([]);
  const [quantityPricingAnalysis, setQuantityPricingAnalysis] = useState<QuantityPricingAnalysis | null>(null);

  const [form, setForm] = useState({
    sku: "", name: "", title: "", brand: "", model: "", characteristics: "", description: "",
    price: "0", quantity: "1", count: "6", localPickup: false, warrantyType: "SELLER",
    warrantyDuration: "30", warrantyUnit: "days"
  });

  useEffect(() => {
    attributesRef.current = attributes;
  }, [attributes]);

  const selectedAccount = useMemo(
    () => accounts.find(account => account.id === accountId),
    [accounts, accountId]
  );
  const totalCount = Math.max(1, Number(form.count) || 1);
  const allocatedCount = commercialAllocations.reduce((sum, option) => sum + Math.max(0, option.count), 0);
  const distributionInvalid = allocatedCount !== totalCount;
  const activeCommercialAllocations = useMemo(
    () => commercialAllocations.filter(option => option.count > 0),
    [commercialAllocations]
  );

  const contextComplete = Boolean(accountId && categoryId);
  const shippingReady = Boolean(
    shippingCapabilities
    && simulationPackage.shippingMode === shippingCapabilities.mode
    && (
      simulationPackage.logisticType === shippingCapabilities.base_logistic_type
      || (shippingCapabilities.flex_available && simulationPackage.logisticType === shippingCapabilities.flex_logistic_type)
    )
  );
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
  const conditionalFields = useMemo(
    () => fields.filter(
      field => Boolean(field.conditional_required)
        && !groupedRequiredAttributeIds.has(field.id)
        && !dedicatedAttributeIds.has(field.id)
    ),
    [fields, groupedRequiredAttributeIds, dedicatedAttributeIds]
  );
  const conditionalFieldIds = useMemo(
    () => new Set(conditionalFields.map(field => field.id)),
    [conditionalFields]
  );
  const recommendedFields = useMemo(
    () => fields.filter(
      field => field.importance === "recommended"
        && !conditionalFieldIds.has(field.id)
        && !groupedRequiredAttributeIds.has(field.id)
        && !dedicatedAttributeIds.has(field.id)
    ),
    [fields, conditionalFieldIds, groupedRequiredAttributeIds, dedicatedAttributeIds]
  );
  const secondaryFields = useMemo(
    () => fields.filter(
      field => field.importance === "secondary"
        && !conditionalFieldIds.has(field.id)
        && !groupedRequiredAttributeIds.has(field.id)
        && !dedicatedAttributeIds.has(field.id)
    ),
    [fields, conditionalFieldIds, groupedRequiredAttributeIds, dedicatedAttributeIds]
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

  async function searchCategoriesForPricing(pricingAccountId: string, query: string) {
    const result = await api<CategorySuggestion[]>(
      `/api/catalog/category-suggestions?account_id=${encodeURIComponent(pricingAccountId)}&q=${encodeURIComponent(query)}&limit=8`
    );
    if (result.length === 0) throw new Error("No encontramos categorías para esa búsqueda. Probá con otras palabras.");
    return result;
  }

  async function loadPublicationTypes(pricingAccountId: string, pricingCategoryId: string) {
    const response = await api<{options: CommercialOption[]}>(
      `/api/publication/commercial-options?account_id=${encodeURIComponent(pricingAccountId)}&category_id=${encodeURIComponent(pricingCategoryId)}`
    );
    return response.options || [];
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
    setTechnicalReuse(null);
    setReusedAttributeIds(new Set());
    setCustomAttributeFields({});
    setShowSecondaryAttributes(false);
    setVersionId("");
    setUploadedImages([]);
    setBatchId("");
    setDrafts([]);
    setKeywordIntelligence(null);
    setSelectedDraftIds([]);
    setPricingAnalysis(null);
    setShippingCapabilities(null);
    setShippingCapabilitiesError("");
  }, [accountId]);

  useEffect(() => {
    let cancelled = false;
    if (!accountId || !categoryId) {
      setShippingCapabilities(null);
      setShippingCapabilitiesError("");
      setShippingCapabilitiesLoading(false);
      return () => { cancelled = true; };
    }

    setShippingCapabilitiesLoading(true);
    setShippingCapabilitiesError("");
    loadShippingCapabilities(accountId, categoryId)
      .then(capabilities => {
        if (cancelled) return;
        setShippingCapabilities(capabilities);
        setSimulationPackage(current => {
          const keepFlex = current.logisticType === capabilities.flex_logistic_type && capabilities.flex_available;
          return {
            ...current,
            shippingMode: capabilities.mode,
            logisticType: keepFlex ? capabilities.flex_logistic_type : capabilities.base_logistic_type,
          };
        });
        setPricingAnalysis(null);
      })
      .catch(reason => {
        if (cancelled) return;
        setShippingCapabilities(null);
        setShippingCapabilitiesError(
          reason instanceof Error ? reason.message : "No fue posible resolver Mercado Envíos para esta cuenta."
        );
      })
      .finally(() => { if (!cancelled) setShippingCapabilitiesLoading(false); });

    return () => { cancelled = true; };
  }, [accountId, categoryId]);

  useEffect(() => {
    setPricingListingTypeId(current => {
      if (activeCommercialAllocations.some(option => option.listing_type_id === current)) return current;
      return activeCommercialAllocations.length === 1 ? activeCommercialAllocations[0].listing_type_id : "";
    });
  }, [activeCommercialAllocations]);

  useEffect(() => {
    setQuantityPricingAnalysis(null);
  }, [
    accountId, categoryId, pricingListingTypeId, productCost, form.price,
    simulationPackage.dimensions, simulationPackage.weight, simulationPackage.logisticType,
    simulationPackage.shippingMode, simulationPackage.freeShipping, pricingAnalysis,
    quantityPrices.map(tier => tier.min_purchase_unit).join(","),
  ]);

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
      setTechnicalReuse(null);
      setReusedAttributeIds(new Set());
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
      loadPublicationTypes(accountId, categoryId),
    ])
      .then(([meta, listingResponse]) => {
        if (cancelled) return;
        const loadedFields: Field[] = meta.schema.fields || [];
        setSelectedCategoryName(String(meta.name || categoryId));
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

        const availableCommercialOptions = listingResponse;
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
    let cancelled = false;
    if (!mlaPreview || !accountId || !categoryId || fields.length === 0) {
      return () => { cancelled = true; };
    }

    resolveMlaPublicationReuse(accountId, mlaPreview.item_id, categoryId)
      .then(result => {
        if (cancelled) return;
        setTechnicalReuse({
          product_id: productMasterId || "",
          category_id: result.category_id,
          reusable: result.reusable,
          pending: result.pending,
          incompatible: result.incompatible,
        });
        const merged = applyReusableAttributes(attributesRef.current, result.reusable);
        attributesRef.current = merged.attributes;
        setAttributes(merged.attributes);
        if (merged.appliedIds.length) {
          setReusedAttributeIds(current => {
            const next = new Set(current);
            merged.appliedIds.forEach(id => next.add(id));
            return next;
          });
        }
      })
      .catch(error => {
        if (!cancelled) setMessage(error.message);
      });

    return () => { cancelled = true; };
  }, [mlaPreview?.item_id, accountId, categoryId, fields.length]);

  useEffect(() => {
    let cancelled = false;
    if (!productMasterId || !accountId || !categoryId || fields.length === 0) {
      return () => { cancelled = true; };
    }

    loadReusableTechnicalAttributes(productMasterId, accountId, categoryId)
      .then(result => {
        if (cancelled) return;
        setTechnicalReuse(result);
        const merged = applyReusableAttributes(attributesRef.current, result.reusable);
        attributesRef.current = merged.attributes;
        setAttributes(merged.attributes);
        if (merged.appliedIds.length) {
          setReusedAttributeIds(current => {
            const next = new Set(current);
            merged.appliedIds.forEach(id => next.add(id));
            return next;
          });
        }
      })
      .catch(error => {
        if (!cancelled) setMessage(error.message);
      });

    return () => { cancelled = true; };
  }, [productMasterId, accountId, categoryId, fields.length]);

  useEffect(() => {
    const sku = form.sku.trim();
    setExistingProduct(null);
    setProductMasterId("");
    if (startMode !== "MLA_IMPORT") {
      setTechnicalReuse(null);
      setAttributes(current => {
        if (reusedAttributeIds.size === 0) return current;
        const next = {...current};
        reusedAttributeIds.forEach(id => delete next[id]);
        return next;
      });
      setReusedAttributeIds(new Set());
    }
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
        const foundProduct = result.found && result.product ? result.product : null;
        setExistingProduct(foundProduct);
        setProductMasterId(foundProduct?.id || "");
      } catch {
        // El lookup es una ayuda no bloqueante: un fallo no impide continuar la carga.
        setExistingProduct(null);
        setProductMasterId("");
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
    const savedPricingInputs = savedPricing?.publisher_inputs || {};
    const savedPackage = version.logistics?.pricing_package || savedPricingInputs.package || {};
    const savedMarketplaceContext = savedPricing?.audit?.marketplace_context || {};
    const weightFromAudit = Number(savedMarketplaceContext.package_weight_grams);
    const savedFreeShipping = savedPackage.free_shipping ?? savedMarketplaceContext.free_shipping;
    setPricingAnalysis(savedPricing);
    setProductCost(String(savedPricingInputs.product_cost ?? savedPricing?.analyzed?.gross_cmv ?? "0"));
    setSimulationPackage({
      dimensions: String(savedPackage.dimensions || savedMarketplaceContext.dimensions || ""),
      weight: String(savedPackage.weight_kg ?? (Number.isFinite(weightFromAudit) && weightFromAudit > 0 ? weightFromAudit / 1000 : "")),
      logisticType: String(savedPackage.logistic_type || savedMarketplaceContext.logistic_type || ""),
      shippingMode: String(savedPackage.shipping_mode || savedMarketplaceContext.shipping_mode || ""),
      freeShipping: savedFreeShipping === true || savedFreeShipping === "true"
        ? "true"
        : savedFreeShipping === false || savedFreeShipping === "false"
          ? "false"
          : "",
    });

    setCategoryId(version.category_id);
    setSelectedCategoryName(version.category_id);
    setTechnicalReuse(null);
    setReusedAttributeIds(new Set());
    setCategorySuggestions([]);
    setFields([]);
    setProductIdentifierMode("");
    setAttributes({...version.attributes});
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
    const result = await searchCategoriesForPricing(accountId, query);
    setPricingAnalysis(null);
    setCategorySuggestions(result);
    setCategoryId("");
    setSelectedCategoryName("");
    if (result.length === 0) throw new Error("Mercado Libre no devolvió categorías sugeridas para estos datos.");
    setMessage("Mercado Libre devolvió categorías candidatas. Confirmá la categoría final correcta.");
  }

  function chooseCategory(suggestion: CategorySuggestion) {
    setPricingAnalysis(null);
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
    setPricingAnalysis(null);
    setMessage("Configuración económica guardada.");
  }

  function publisherPricingPayload(salePrice: number | null) {
    return {
      account_id: accountId,
      category_id: categoryId,
      listing_type_id: pricingListingTypeId,
      product_cost: Number(productCost),
      sale_price: salePrice,
      package: {
        dimensions: simulationPackage.dimensions || null,
        weight: simulationPackage.weight ? Number(simulationPackage.weight) : null,
        logistic_type: simulationPackage.logisticType || null,
        shipping_mode: simulationPackage.shippingMode || null,
        free_shipping: simulationPackage.freeShipping === "" ? null : simulationPackage.freeShipping === "true",
      },
    };
  }

  async function simulateCurrentPrice() {
    if (!pricingConfigured) throw new Error("Configurá primero Costos y rentabilidad.");
    const listingTypeId = pricingListingTypeId;
    if (!accountId || !categoryId || !listingTypeId) {
      throw new Error("Elegí cuenta, categoría y la modalidad de Mercado Libre que querés analizar.");
    }
    const result = await api<any>("/api/pricing/simulate", {
      method: "POST",
      body: JSON.stringify(publisherPricingPayload(Number(form.price) > 0 ? Number(form.price) : null)),
    });
    setPricingAnalysis({
      calculation_version: "pricing_v2_economic",
      ...result,
      publisher_inputs: {
        product_cost: Number(productCost),
        package: {
          dimensions: simulationPackage.dimensions || null,
          weight_kg: simulationPackage.weight ? Number(simulationPackage.weight) : null,
          logistic_type: simulationPackage.logisticType || null,
          shipping_mode: simulationPackage.shippingMode || null,
          free_shipping: simulationPackage.freeShipping === "" ? null : simulationPackage.freeShipping === "true",
        },
      },
    });
  }

  async function simulateQuantityPrices() {
    if (!pricingConfigured) throw new Error("Configurá primero Costos y rentabilidad.");
    if (!accountId || !categoryId || !pricingListingTypeId) {
      throw new Error("Completá cuenta, categoría y modalidad antes de analizar precios mayoristas.");
    }
    if (!quantityPrices.length) throw new Error("Agregá al menos un escalón mayorista.");
    const invalidTier = quantityPrices.some(tier => tier.min_purchase_unit <= 1);
    if (invalidTier) throw new Error("Completá cantidades mayores a 1.");
    const response = await api<QuantityPricingApiResponse>("/api/pricing/quantity-tiers", {
      method: "POST",
      body: JSON.stringify({
        ...publisherPricingPayload(Number(form.price) > 0 ? Number(form.price) : null),
        tiers: quantityPrices.map(tier => ({min_purchase_unit: tier.min_purchase_unit})),
      }),
    });
    const normalized = normalizeQuantityPricing(response);
    setQuantityPricingAnalysis(normalized);
    setQuantityPrices(current => current.map((tier, index) => {
      const analysis = normalized.tiers[index];
      return {
        ...tier,
        amount: analysis?.status === "OPTIMO" ? analysis.amount : 0,
      };
    }));
  }

  function transferRecommendedPrice(price: number, calculation: PricingCalculation) {
    setForm(previous => ({...previous, price: String(price)}));
    const marketplaceContext = calculation.audit.marketplaceContext;
    const packageWeightGrams = Number(marketplaceContext.package_weight_grams);
    setPricingAnalysis({
      calculation_version: "pricing_v2_economic",
      scenario: calculation.scenario,
      scenario_units: calculation.scenarioUnits,
      recommended_price: price,
      analyzed: {
        gross_price: calculation.analyzed.grossPrice,
        gross_cmv: calculation.analyzed.grossCmv,
        net_cmv: calculation.analyzed.netCmv,
        contribution_margin: calculation.analyzed.contributionMargin,
        contribution_margin_pct: calculation.analyzed.contributionMarginPct,
      },
      mc0: {target_margin_pct: calculation.mc0.targetMarginPct, gross_price: calculation.mc0.grossPrice},
      mc15: {target_margin_pct: calculation.mc15.targetMarginPct, gross_price: calculation.mc15.grossPrice},
      mc20: {target_margin_pct: calculation.mc20.targetMarginPct, gross_price: calculation.mc20.grossPrice},
      minimum: {target_margin_pct: calculation.minimum.targetMarginPct, gross_price: calculation.minimum.grossPrice},
      target: {target_margin_pct: calculation.target.targetMarginPct, gross_price: calculation.target.grossPrice},
      audit: {
        marketplace_context: marketplaceContext,
        target_margin_pct: calculation.audit.targetMarginPct,
        target_margin_source: calculation.audit.targetMarginSource,
        minimum_margin_pct: calculation.audit.minimumMarginPct,
        recommended_target_margin_pct: calculation.audit.recommendedTargetMarginPct,
        rounding_step: calculation.audit.roundingStep,
      },
      publisher_inputs: {
        product_cost: calculation.analyzed.grossCmv,
        package: {
          dimensions: String(marketplaceContext.dimensions || ""),
          weight_kg: Number.isFinite(packageWeightGrams) && packageWeightGrams > 0 ? packageWeightGrams / 1000 : null,
          logistic_type: String(marketplaceContext.logistic_type || ""),
          shipping_mode: String(marketplaceContext.shipping_mode || ""),
          free_shipping: String(marketplaceContext.free_shipping) === "true",
        },
      },
    });
    setActiveView("publisher");
    setMessage("Precio recomendado transferido al formulario. Todavía no se creó ninguna publicación.");
  }

  function addQuantityPriceTier() {
    if (quantityPrices.length >= 5) return;
    const previousQuantity = quantityPrices.length ? quantityPrices[quantityPrices.length - 1].min_purchase_unit : 1;
    setQuantityPrices(current => [...current, {
      min_purchase_unit: previousQuantity + 1,
      amount: 0,
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
    const hasPricingPackage = Boolean(
      simulationPackage.dimensions.trim()
      || simulationPackage.weight
      || simulationPackage.logisticType
      || simulationPackage.shippingMode
      || simulationPackage.freeShipping
    );
    return {
      local_pick_up: form.localPickup,
      ...(hasPricingPackage ? {
        pricing_package: {
          dimensions: simulationPackage.dimensions.trim() || null,
          weight_kg: simulationPackage.weight ? Number(simulationPackage.weight) : null,
          logistic_type: simulationPackage.logisticType || null,
          shipping_mode: simulationPackage.shippingMode || null,
          free_shipping: simulationPackage.freeShipping === "" ? null : simulationPackage.freeShipping === "true",
        },
      } : {}),
    };
  }

  function openPricingDetail() {
    const listingTypeId = pricingListingTypeId;
    setCalculatorPrefill({
      requestId: Date.now(),
      accountId,
      categoryId,
      categoryLabel: selectedCategoryName || categoryId,
      listingTypeId,
      grossCmv: productCost,
      salePrice: form.price,
      dimensions: simulationPackage.dimensions,
      weight: simulationPackage.weight,
      logisticType: simulationPackage.logisticType,
      shippingMode: simulationPackage.shippingMode,
      freeShipping: simulationPackage.freeShipping,
    });
    setActiveView("price-calculator");
  }

  async function createProduct() {
    if (!accountId || !categoryId) throw new Error("Elegí cuenta y una categoría hoja sugerida por Mercado Libre.");
    if (quantityPricingEnabled) {
      if (!quantityPrices.length) throw new Error("Agregá al menos un escalón mayorista.");
      if (quantityPrices.some(tier => tier.min_purchase_unit <= 1 || tier.amount <= 0)) {
        throw new Error("Calculá precios mayoristas óptimos antes de guardar el producto.");
      }
    }
    if (!form.sku.trim() || !form.name.trim()) throw new Error("Completá SKU y nombre interno.");
    if (categoryContractLoading) {
      throw new Error("Esperá a que termine de cargar el contrato de categoría de Mercado Libre.");
    }
    if (!requiredAttributesComplete) {
      throw new Error("Completá los atributos obligatorios informados por Mercado Libre.");
    }
    if (!shippingReady) {
      throw new Error("Esperá a que Mercado Libre confirme la configuración de Mercado Envíos para esta categoría.");
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
    setProductMasterId(String(result.product_id || ""));
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
    if (!shippingReady) {
      throw new Error("Esperá a que Mercado Libre confirme la configuración de Mercado Envíos antes de revalidar.");
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
    const firstIssue = validation.results?.flatMap((result:any) => result.errors || [])[0];
    setMessage(
      `Correcciones guardadas en la versión ${correction.version_number}. ` +
      `${validation.ready} borrador(es) listos y ${validation.invalid} con observaciones.` +
      (firstIssue?.message ? ` Falta corregir: ${firstIssue.message}` : " No fue necesario regenerar el lote.")
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
    const result = await api<any>(`/api/drafts/${id}/validate`, {method:"POST"});
    await loadBatch();
    const firstIssue = result.errors?.[0];
    setMessage(
      result.valid
        ? "El borrador pasó la validación previa de Mercado Libre."
        : `Falta corregir: ${firstIssue?.message || "Mercado Libre rechazó la validación previa."}`
    );
  }

  async function approveDraft(id: string) {
    await api(`/api/drafts/${id}/approve`, {method:"POST"});
    await loadBatch();
  }

  async function validateAll() {
    if (!batchId) return;
    const result = await api<any>(`/api/drafts/batches/${batchId}/validate`, {method:"POST"});
    await loadBatch(batchId);
    const firstIssue = result.results?.flatMap((item:any) => item.errors || [])[0];
    setMessage(
      `${result.ready} borrador(es) listos y ${result.invalid} con observaciones después de validar el lote.` +
      (firstIssue?.message ? ` Falta corregir: ${firstIssue.message}` : "")
    );
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

  function updateTechnicalAttribute(attributeId: string, value: any) {
    setAttributes(current => ({...current, [attributeId]: value}));
    setReusedAttributeIds(current => {
      if (!current.has(attributeId)) return current;
      const next = new Set(current);
      next.delete(attributeId);
      return next;
    });
  }

  async function importMlaPublication() {
    const itemId = mlaImportId.trim().toUpperCase();
    if (!accountId) throw new Error("Seleccioná una cuenta de Mercado Libre.");
    if (!/^MLA\d+$/.test(itemId)) throw new Error("Ingresá un MLA válido, por ejemplo MLA123456789.");

    setTechnicalAttributeBusy(true);
    try {
      const imported = await previewMlaPublication(accountId, itemId);
      const seed = buildImportedProductSeed(imported);
      setMlaPreview(imported);
      setMlaImportId(imported.item_id);
      setStartMode("MLA_IMPORT");
      setForm(current => ({
        ...current,
        sku: seed.sku,
        name: seed.name,
        title: seed.title,
        description: seed.description,
        brand: seed.brand,
        model: seed.model,
      }));
      setCategorySuggestions([]);
      setSelectedCategoryName(seed.categoryId);
      setCategoryId(seed.categoryId);
      setMessage(
        seed.categoryId
          ? `Publicación ${imported.item_id} importada. Cargamos sus datos y estamos validando la ficha contra ${seed.categoryId}.`
          : `Publicación ${imported.item_id} importada. Completá o buscá una categoría para continuar.`
      );
    } finally {
      setTechnicalAttributeBusy(false);
    }
  }

  function startFromZero() {
    setStartMode("MANUAL");
    setMlaPreview(null);
    setMlaImportId("");
    setTechnicalReuse(null);
    setReusedAttributeIds(new Set());
    setProductMasterId("");
    setExistingProduct(null);
    setCategoryId("");
    setSelectedCategoryName("");
    setCategorySuggestions([]);
    setAttributes({});
    setForm(current => ({
      ...current,
      sku: "",
      name: "",
      title: "",
      brand: "",
      model: "",
      characteristics: "",
      description: "",
    }));
    setMessage("Carga manual iniciada. Completá los datos del producto y buscá su categoría.");
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
      <span className="attributeLabel">{field.label}{required && <b className="required"> *</b>}{reusedAttributeIds.has(field.id) && <em className="reusedAttributeBadge">Reutilizado</em>}</span>
      {field.is_measurement ? (() => {
        const parts = measurementParts(current, field);
        const units = field.allowed_units || [];
        const commit = (numberText: string, unit: string) => {
          updateTechnicalAttribute(field.id, buildMeasurementValue(numberText, unit));
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
          updateTechnicalAttribute(field.id, value ? {value_name:value} : null);
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
              updateTechnicalAttribute(field.id, "");
              return;
            }
            const selected = field.values.find(v=>String(v.id || v.name) === e.target.value);
            setCustomAttributeFields({...customAttributeFields, [field.id]: false});
            updateTechnicalAttribute(field.id, selected ? {value_id:selected.id, value_name:selected.name} : null);
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
            onChange={e=>updateTechnicalAttribute(field.id, e.target.value)}
          />}
        </>
      ) : (
        <input
          maxLength={field.value_max_length || undefined}
          value={typeof current === "string" ? current : ""}
          onChange={e=>updateTechnicalAttribute(field.id, e.target.value)}
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
        <PriceCalculator
          accountId={accountId}
          accounts={accounts}
          prefill={calculatorPrefill}
          onSearchCategories={searchCategoriesForPricing}
          onLoadPublicationTypes={loadPublicationTypes}
          onUseRecommendedPrice={transferRecommendedPrice}
        />
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
              <select value={accountId} onChange={e=>{
                setAccountId(e.target.value);
                setStartMode("");
                setMlaPreview(null);
                setMlaImportId("");
                setCategoryId("");
                setSelectedCategoryName("");
              }}>
                <option value="">Seleccionar…</option>
                {accounts.map(a=><option key={a.id} value={a.id}>{a.nickname} {a.seller_id ? `· ${a.seller_id}`:""}</option>)}
              </select>
              {selectedAccount && <small className="helper">{selectedAccount.auth_status.replaceAll("_", " ")} · {selectedAccount.site_id}</small>}
            </label>
          </div>

          {accountId && <div className="publisherStartPanel">
            <div className="publisherStartHeader">
              <div>
                <h3>¿Cómo querés comenzar?</h3>
                <p className="helper blockHelper">Podés traer una publicación propia de Mercado Libre para reutilizar sus datos o cargar el producto completamente desde cero.</p>
              </div>
            </div>
            <div className="publisherStartChoices">
              <button
                type="button"
                className={`publisherStartChoice ${startMode === "MLA_IMPORT" ? "selected" : ""}`}
                onClick={()=>setStartMode("MLA_IMPORT")}
              >
                <b>Importar publicación de Mercado Libre</b>
                <span>Traer título, SKU, categoría y ficha técnica desde un MLA propio.</span>
              </button>
              <button
                type="button"
                className={`publisherStartChoice ${startMode === "MANUAL" ? "selected" : ""}`}
                onClick={startFromZero}
              >
                <b>Crear producto desde cero</b>
                <span>Completar SKU, producto, categoría y ficha manualmente.</span>
              </button>
            </div>
            {startMode === "MLA_IMPORT" && <div className="publisherMlaImport">
              <label>MLA de origen
                <input
                  value={mlaImportId}
                  disabled={technicalAttributeBusy}
                  onChange={e=>setMlaImportId(e.target.value.toUpperCase())}
                  placeholder="MLA123456789"
                  aria-label="MLA para importar publicación"
                />
              </label>
              <button
                type="button"
                disabled={technicalAttributeBusy || !/^MLA\d+$/.test(mlaImportId.trim().toUpperCase())}
                onClick={()=>run(importMlaPublication)}
              >
                {technicalAttributeBusy ? "Importando…" : "Importar y continuar"}
              </button>
              {mlaPreview && <small className="helper importSourceOk">Origen cargado: {mlaPreview.item_id}. Podés editar cualquier dato antes de guardar.</small>}
            </div>}
          </div>}

          {startMode && <><div className="attributeHeader">
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
          /></>}
        </section>

        <section className={`card ${!contextComplete ? "locked" : ""}`}>
          <div className="sectionTitle"><span>2</span> Ficha técnica</div>
          {(mlaPreview || technicalReuse) && <div className="technicalReusePanel">
            <div className="technicalReuseIntro">
              <div>
                <h3>{mlaPreview ? `Ficha importada desde ${mlaPreview.item_id}` : "Ficha técnica reutilizada"}</h3>
                <p className="helper blockHelper">Sólo completamos campos vacíos compatibles con la categoría actual. Cualquier edición manual tiene prioridad.</p>
              </div>
            </div>
            {technicalReuse && <div className="technicalReuseSummary">
              <span><b>{technicalReuse.reusable.length}</b> reutilizables</span>
              <span><b>{technicalReuse.pending.length}</b> pendientes</span>
              <span><b>{technicalReuse.incompatible.length}</b> no aplican</span>
            </div>}
          </div>}
          {!contextComplete && <div className="lockedMessage">Ingresá el producto, buscá categorías y confirmá una categoría hoja para continuar.</div>}
          <div className="grid3">
            <label>Precio ARS<input disabled={!contextComplete} type="number" value={form.price} onChange={e=>{setForm({...form,price:e.target.value});setPricingAnalysis(null);}}/></label>
            <label>Stock<input disabled={!contextComplete} type="number" value={form.quantity} onChange={e=>setForm({...form,quantity:e.target.value})}/></label>
          </div>
          <div className="publisherShippingContext">
            <div className="publisherContextHeader">
              <div><h3>Datos de envío</h3><p className="helper blockHelper">Estos datos describen el paquete y se reutilizan para publicación y cálculo de costos. No son parámetros económicos.</p></div>
            </div>
            <div className="grid2 shippingPackageGrid">
              <label>Dimensiones del paquete (L×A×H, cm)<input disabled={!contextComplete} value={simulationPackage.dimensions} onChange={e=>{setSimulationPackage({...simulationPackage, dimensions:e.target.value});setPricingAnalysis(null);}} placeholder="30x20x10"/></label>
              <label>Peso del paquete (kg)<input disabled={!contextComplete} type="number" min="0.01" step="0.01" value={simulationPackage.weight} onChange={e=>{setSimulationPackage({...simulationPackage, weight:e.target.value});setPricingAnalysis(null);}}/></label>
            </div>
            <div className="shippingPanel">
              <div className="shippingPanelHeader">
                <div><span className="shippingEyebrow">Envío</span><b>Mercado Envíos</b><small>La modalidad técnica se toma de la configuración real de tu cuenta y de la categoría.</small></div>
                <span className={`shippingStatus ${shippingCapabilities ? "ready" : "pending"}`}>{shippingCapabilitiesLoading ? "Consultando…" : shippingCapabilities ? "Activo" : "Pendiente"}</span>
              </div>
              {shippingCapabilitiesError && <div className="shippingCapabilityError">{shippingCapabilitiesError}</div>}
              {shippingCapabilities && <div className="shippingDecisionGrid">
                <div className="shippingDecision">
                  <span>¿Ofrecer Mercado Envíos Flex?</span>
                  <div className="segmentedChoice" role="group" aria-label="Ofrecer Mercado Envíos Flex">
                    <button type="button" className={simulationPackage.logisticType !== shippingCapabilities.flex_logistic_type ? "active" : ""} onClick={()=>{setSimulationPackage(current=>({...current,shippingMode:shippingCapabilities.mode,logisticType:shippingCapabilities.base_logistic_type}));setPricingAnalysis(null);}}>No</button>
                    <button type="button" disabled={!shippingCapabilities.flex_available} className={simulationPackage.logisticType === shippingCapabilities.flex_logistic_type ? "active" : ""} onClick={()=>{setSimulationPackage(current=>({...current,shippingMode:shippingCapabilities.mode,logisticType:shippingCapabilities.flex_logistic_type}));setPricingAnalysis(null);}}>Sí</button>
                  </div>
                  <small>{shippingCapabilities.flex_available ? "Flex está habilitado para esta cuenta y categoría." : "Mercado Libre no habilita Flex para este contexto."}</small>
                </div>
                <label>Quién paga el envío<select disabled={!contextComplete} value={simulationPackage.freeShipping} onChange={e=>{setSimulationPackage({...simulationPackage, freeShipping:e.target.value});setPricingAnalysis(null);}}><option value="">Elegí una opción</option><option value="false">El comprador paga</option><option value="true">Ofrecer envío gratis</option></select><small>Mercado Libre aplicará igualmente las reglas obligatorias de envío gratis cuando correspondan.</small></label>
              </div>}
            </div>
          </div>

          <div className="economicSimulator pricingProposalPanel">
            <div className="economicSimulatorHeader">
              <div><h3>Propuestas de precio</h3><p className="helper blockHelper">Ingresá únicamente el costo del producto. El resto se toma de Configuración y de Mercado Libre.</p></div>
              {!pricingConfigured && <button type="button" className="secondary" onClick={()=>setActiveView("pricing-settings")}>Configurar política económica</button>}
            </div>
            <div className={`publisherPricingInputs ${activeCommercialAllocations.length > 1 ? "withListingType" : ""}`}>
              <label className="publisherCostInput">Costo del producto (con IVA)<input disabled={!contextComplete} type="number" min="0" step="0.01" value={productCost} onChange={e=>{setProductCost(e.target.value);setPricingAnalysis(null);}} placeholder="0,00"/><small>Es el único costo que cargás por producto. Los demás costos se administran en Configuración.</small></label>
              {activeCommercialAllocations.length > 1 && <label>Modalidad a analizar<select disabled={!contextComplete} value={pricingListingTypeId} onChange={e=>{setPricingListingTypeId(e.target.value);setPricingAnalysis(null);}}><option value="">Elegí una modalidad</option>{activeCommercialAllocations.map(option=><option key={option.listing_type_id} value={option.listing_type_id}>{option.listing_type_name}</option>)}</select><small>Este lote usa más de una modalidad de publicación.</small></label>}
              {activeCommercialAllocations.length === 1 && <div className="pricingResolvedContext"><span>Modalidad</span><b>{activeCommercialAllocations[0].listing_type_name}</b><small>Se toma automáticamente de la configuración del lote.</small></div>}
            </div>
            <div className="pricingProposalActions">
              <button type="button" disabled={!contextComplete || !pricingConfigured || !Number(productCost) || busy} onClick={()=>run(simulateCurrentPrice)}>{busy ? "Calculando…" : "Calcular propuestas"}</button>
              <span>Usa la categoría, modalidad y logística ya cargadas en esta ficha.</span>
            </div>
            {pricingAnalysis && <div className="publisherPricingStory">
              {Number(form.price) > 0 && <div className="publisherCurrentPrice">
                <div><span>Precio actual</span><b>{money(form.price)}</b></div>
                <div><span>Margen actual</span><b>{Number(pricingAnalysis.analyzed.contribution_margin_pct).toFixed(2)}%</b></div>
                <div><span>Resultado por venta</span><b>{money(pricingAnalysis.analyzed.contribution_margin)}</b></div>
              </div>}
              <div className="publisherPricingTargets">
                {publisherPricingTargets(pricingAnalysis).map(option => <div key={option.key} className={`publisherPricingTarget${option.recommended ? " recommended" : ""}`}>
                  <div className="publisherPricingTargetHeader"><span>{option.label}</span>{option.recommended && <em>Recomendado</em>}</div>
                  <b>{money(option.target.gross_price)}</b>
                  <small>Margen logrado: {Number(option.target.achieved_margin_pct ?? option.target.target_margin_pct).toFixed(2)}%</small>
                  {option.recommended && <button type="button" onClick={()=>setForm({...form,price:String(pricingAnalysis.recommended_price)})}>Usar este precio</button>}
                </div>)}
              </div>
              <div className="pricingInlineFooter">
                <span>Recomendación según tu política económica vigente.</span>
                <button type="button" className="secondary" onClick={openPricingDetail}>Ver detalle en Calculadora</button>
              </div>
            </div>}
          </div>

          <div className="quantityPricingBox">
            <label className="checkboxLabel"><input type="checkbox" disabled={!contextComplete} checked={quantityPricingEnabled} onChange={e=>setQuantityPricingEnabled(e.target.checked)}/> Publicar precios mayoristas B2B por cantidad</label>
            <p className="helper blockHelper">Mercado Libre habilita PxQ B2B sólo para vendedores seleccionados. La publicación principal no se pierde si ML rechaza la tabla mayorista; el job lo informa como advertencia.</p>
            {quantityPricingEnabled && <>
              <div className="quantityPriceRows">
                {quantityPrices.map((tier,index)=>{
                  const analysis = quantityPricingAnalysis?.tiers[index];
                  return <div className="quantityPriceRow" key={index}>
                    <label>Desde<input type="number" min="2" value={tier.min_purchase_unit} onChange={e=>updateQuantityPriceTier(index,{min_purchase_unit:Number(e.target.value),amount:0})}/></label>
                    <label>Precio óptimo unitario ARS<input type="number" value={tier.amount || ""} readOnly placeholder="Se calcula automáticamente"/></label>
                    <div className="quantityTierEconomics">
                      {analysis ? <>
                        <span className={`tierRisk ${analysis.status === "OPTIMO" ? "ok" : "bad"}`}>{analysis.status === "OPTIMO" ? "ÓPTIMO" : "SIN VENTAJA"}</span>
                        <small>MC estimado: <b>{analysis.contributionMarginPct}%</b> · {money(analysis.contributionMargin)}</small>
                        <small>Minorista: <b>{money(analysis.retailPrice)}</b> · Piso económico: <b>{money(analysis.minimumPrice)}</b></small>
                        <small>{analysis.status === "OPTIMO" ? <>Descuento sostenible máximo: <b>{analysis.discountPct}%</b></> : <>No existe un descuento sostenible frente al precio minorista actual.</>}</small>
                      </> : <small>El precio se calcula automáticamente usando el margen mínimo configurado.</small>}
                    </div>
                    <button type="button" className="tiny dangerButton" onClick={()=>removeQuantityPriceTier(index)}>Eliminar</button>
                  </div>;
                })}
              </div>
              <div className="quantityPricingActions">
                <button type="button" className="secondary" disabled={quantityPrices.length >= 5} onClick={addQuantityPriceTier}>+ Agregar escalón mayorista</button>
                <button type="button" className="secondary" disabled={!pricingConfigured || !quantityPrices.length || busy} onClick={()=>run(simulateQuantityPrices)}>Calcular precios óptimos</button>
              </div>
              <small className="helper">Máximo 5 escalones. El sistema busca el precio unitario más bajo que conserva el margen mínimo configurado; no aplica porcentajes de descuento arbitrarios.</small>
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

            {conditionalFields.length > 0 && <>
              <div className="attributeHeader conditionalHeader">
                <div>
                  <h3>Datos que Mercado Libre puede exigir</h3>
                  <p className="helper blockHelper">Dependen del contexto real de la publicación. Los dejamos visibles porque Mercado Libre puede volverlos obligatorios al validar, aunque la categoría no los marque como requeridos para todos los productos.</p>
                </div>
                <span className="conditionalBadge">Validación dinámica</span>
              </div>
              <div className="grid3 conditionalGrid">{conditionalFields.map(field => renderAttributeField(field))}</div>
            </>}

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
            disabled={!contextComplete || categoryContractLoading || shippingCapabilitiesLoading || !shippingReady || !requiredAttributesComplete || busy}
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

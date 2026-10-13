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
import {OperatorUsers} from "./OperatorUsers";
import {PublicationManager} from "./PublicationManager";
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
  batch_id?: string; account_id?: string; account_nickname?: string;
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
type ToastKind = "success" | "info" | "warning" | "error";
type ToastNotice = {id: number; message: string; kind: ToastKind};

function ToastItem({notice, dismiss}: {notice: ToastNotice; dismiss: (id: number) => void}) {
  useEffect(() => {
    if (notice.kind === "error") return;
    const duration = notice.kind === "warning" ? 8000 : notice.kind === "success" ? 4000 : 5000;
    const timer = window.setTimeout(() => dismiss(notice.id), duration);
    return () => window.clearTimeout(timer);
  }, [notice.id, notice.kind, dismiss]);
  return <div className={`toastNotice toast-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
    <span className="toastSymbol" aria-hidden="true">{notice.kind === "error" ? "!" : notice.kind === "warning" ? "!" : notice.kind === "success" ? "✓" : "i"}</span>
    <div className="toastBody"><strong>{notice.kind === "error" ? "Error" : notice.kind === "warning" ? "Advertencia" : notice.kind === "success" ? "Operación completada" : "Información"}</strong><p>{notice.message}</p></div>
    <button type="button" className="toastClose" aria-label="Cerrar notificación" onClick={() => dismiss(notice.id)}>×</button>
  </div>;
}

type CommercialAllocation = CommercialOption & {count: number};
const TERMINAL_JOB_STATES = ["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"];
const GTIN_ATTRIBUTE_ID = "GTIN";
const EMPTY_GTIN_REASON_ATTRIBUTE_ID = "EMPTY_GTIN_REASON";

function activeJobStorageKey(accountId: string) {
  return `ml-publisher-active-job:${accountId}`;
}

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

function packageDimensionParts(dimensions: string) {
  const [length = "", width = "", height = ""] = String(dimensions || "").split("x").map(value => value.trim());
  return {length, width, height};
}

function packageDimensionsValue(parts: {length: string; width: string; height: string}) {
  if (!parts.length && !parts.width && !parts.height) return "";
  return `${parts.length}x${parts.width}x${parts.height}`;
}

function numericMeasurement(value: any): {number: number; unit: string} | null {
  const struct = typeof value === "object" && value ? (value.value_struct || value.struct || {}) : {};
  const structured = Number(struct.number);
  const structuredUnit = String(struct.unit || "").trim().toLowerCase();
  if (Number.isFinite(structured) && structured > 0) return {number: structured, unit: structuredUnit};
  const raw = identifierText(value).replace(",", ".");
  const match = raw.match(/(-?\d+(?:\.\d+)?)\s*([a-zA-Z]+)?/);
  if (!match) return null;
  const number = Number(match[1]);
  if (!Number.isFinite(number) || number <= 0) return null;
  return {number, unit: String(match[2] || "").toLowerCase()};
}

function measurementToCm(measurement: {number: number; unit: string} | null) {
  if (!measurement) return "";
  const factors: Record<string, number> = {mm: 0.1, cm: 1, m: 100};
  const factor = factors[measurement.unit] ?? (measurement.unit ? NaN : 1);
  if (!Number.isFinite(factor)) return "";
  return String(Math.round(measurement.number * factor * 100) / 100);
}

function measurementToKg(measurement: {number: number; unit: string} | null) {
  if (!measurement) return "";
  const factors: Record<string, number> = {g: 0.001, gr: 0.001, kg: 1};
  const factor = factors[measurement.unit] ?? (measurement.unit ? NaN : 1);
  if (!Number.isFinite(factor)) return "";
  return String(Math.round(measurement.number * factor * 1000) / 1000);
}

function technicalPackageDefaults(fields: Field[], values: Record<string, any>) {
  const find = (kind: "length" | "width" | "height" | "weight") => {
    const patterns = {
      length: /(package|packaging|paquete|embalaje).*(length|largo)|(length|largo).*(package|packaging|paquete|embalaje)/i,
      width: /(package|packaging|paquete|embalaje).*(width|ancho)|(width|ancho).*(package|packaging|paquete|embalaje)/i,
      height: /(package|packaging|paquete|embalaje).*(height|alto)|(height|alto).*(package|packaging|paquete|embalaje)/i,
      weight: /(package|packaging|paquete|embalaje).*(weight|peso)|(weight|peso).*(package|packaging|paquete|embalaje)/i,
    }[kind];
    const field = fields.find(candidate => patterns.test(`${candidate.id} ${candidate.label}`));
    return field ? numericMeasurement(values[field.id]) : null;
  };
  return {
    length: measurementToCm(find("length")),
    width: measurementToCm(find("width")),
    height: measurementToCm(find("height")),
    weight: measurementToKg(find("weight")),
  };
}

function installmentPrice(basePrice: number, markupPct: number) {
  if (!Number.isFinite(basePrice) || basePrice <= 0) return 0;
  const markup = Number.isFinite(markupPct) ? Math.max(0, markupPct) : 0;
  return Math.round(basePrice * (1 + markup / 100));
}

function publisherScenarioTarget(analysis: any, scenario: "mc0" | "mc15" | "mc20" | "mc25" | "mc35" | "custom") {
  if (!analysis || scenario === "custom") return null;
  if (scenario === "mc25" || scenario === "mc35") return analysis.custom || null;
  return analysis[scenario] || null;
}

function publisherScenarioBreakdown(analysis: any, scenario: "mc0" | "mc15" | "mc20" | "mc25" | "mc35" | "custom", variant: "base" | "3" | "6") {
  if (!analysis) return null;
  if (variant !== "base" || scenario === "custom") return analysis.analyzed || null;
  if (scenario === "mc25" || scenario === "mc35") return analysis.breakdowns?.custom || analysis.analyzed || null;
  return analysis.breakdowns?.[scenario] || analysis.analyzed || null;
}

function App({operatorRole}: {operatorRole: "ADMIN" | "SUPERVISOR" | "OPERATOR"}) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categorySuggestions, setCategorySuggestions] = useState<CategorySuggestion[]>([]);
  const [selectedCategoryName, setSelectedCategoryName] = useState("");
  const [commercialOptions, setCommercialOptions] = useState<CommercialOption[]>([]);
  const [categoryContractLoading, setCategoryContractLoading] = useState(false);
  const [titleMaxLength, setTitleMaxLength] = useState<number | null>(null);
  const [accountId, setAccountId] = useState("");
  const [targetAccountIds, setTargetAccountIds] = useState<string[]>([]);
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
  const [batchIds, setBatchIds] = useState<string[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [job, setJob] = useState<any>(null);
  const [keywordIntelligence, setKeywordIntelligence] = useState<any>(null);
  const [selectedDraftIds, setSelectedDraftIds] = useState<string[]>([]);
  const [generationActive, setGenerationActive] = useState(false);
  const [validationActive, setValidationActive] = useState(false);
  const [toasts, setToasts] = useState<ToastNotice[]>([]);
  const toastSequence = useRef(0);
  const dismissToast = React.useCallback((id: number) => {
    setToasts(current => current.filter(toast => toast.id !== id));
  }, []);
  function notify(message: string, kind: ToastKind = "info") {
    if (!message.trim()) return;
    setToasts(current => {
      if (current.some(toast => toast.message === message && toast.kind === kind)) return current;
      return [...current, {id: ++toastSequence.current, message, kind}].slice(-3);
    });
  }
  function setMessage(message: string) { notify(message); }

  const [busy, setBusy] = useState(false);
  const [accountModal, setAccountModal] = useState(false);
  const [manualMode, setManualMode] = useState(false);
  const [oauthStatus, setOauthStatus] = useState<OAuthStatus | null>(null);
  const [manualAccount, setManualAccount] = useState({nickname: "", token: ""});
  const [existingProduct, setExistingProduct] = useState<ExistingProduct | null>(null);
  const [productMasterId, setProductMasterId] = useState("");
  const [editLease, setEditLease] = useState<{productId: string; token: string; expiresAt: string} | null>(null);
  const editLeaseRef = useRef<{productId: string; token: string; expiresAt: string} | null>(null);
  function rememberEditLease(next: {productId: string; token: string; expiresAt: string} | null) {
    editLeaseRef.current = next;
    setEditLease(next);
  }
  function releaseEditLease() {
    const prior = editLeaseRef.current;
    if (!prior) return;
    rememberEditLease(null);
    void api(`/api/product-edit-leases/${prior.productId}`, {
      method: "DELETE", body: JSON.stringify({fencing_token: prior.token}),
    }).catch(() => { /* The lease will expire server-side if connectivity is lost. */ });
  }
  async function takeEditLease(productId: string) {
    const existing = editLeaseRef.current;
    if (existing?.productId === productId && new Date(existing.expiresAt).getTime() > Date.now() + 15_000) {
      return existing.token;
    }
    if (existing && existing.productId !== productId) releaseEditLease();
    const response = await api<{fencing_token: string; expires_at: string}>(
      `/api/product-edit-leases/${productId}`, {method: "POST"}
    );
    rememberEditLease({productId, token: response.fencing_token, expiresAt: response.expires_at});
    return response.fencing_token;
  }
  useEffect(() => {
    if (!editLease) return;
    const timer = window.setInterval(async () => {
      const current = editLeaseRef.current;
      if (!current || current.productId !== editLease.productId || current.token !== editLease.token) return;
      try {
        const renewed = await api<{expires_at: string}>(`/api/product-edit-leases/${current.productId}`, {
          method: "PUT", body: JSON.stringify({fencing_token: current.token}),
        });
        if (editLeaseRef.current?.token === current.token) {
          rememberEditLease({...current, expiresAt: renewed.expires_at});
        }
      } catch {
        if (editLeaseRef.current?.token === current.token) {
          rememberEditLease(null);
          notify("Se perdió el bloqueo de edición. Volvé a tomarlo antes de guardar.", "warning");
        }
      }
    }, 50_000);
    return () => window.clearInterval(timer);
  }, [editLease?.productId, editLease?.token]);

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
  const [activeView, setActiveView] = useState<"publisher" | "pricing-settings" | "price-calculator" | "manager">("publisher");
  const [publisherStep, setPublisherStep] = useState<"category" | "technical" | "prices" | "images" | "review" | "execution">("category");
  const [lastAction, setLastAction] = useState("Todavía no hay acciones en esta ficha.");
  const [lastSavedAt, setLastSavedAt] = useState("");
  const [savedSignature, setSavedSignature] = useState("");
  const [resumeJobId, setResumeJobId] = useState("");
  const trackedJobRef = useRef<string | null>(null);

  const [pricingConfigured, setPricingConfigured] = useState(false);
  const [pricingProfile, setPricingProfile] = useState<PricingProfile>({
    name: "Mercado Libre", channel: "MERCADOLIBRE", currency_id: "ARS",
    target_margin_pct: 20, minimum_margin_pct: 10, installment_3_markup_pct: 0, installment_6_markup_pct: 0, vat_rate_pct: 21, iibb_rate_pct: 0, ads_rate_pct: 0, refund_rate_pct: 0,
    monthly_units_projection: null, rounding_step: 1, components: []
  });
  const [productCost, setProductCost] = useState("0");
  const [pricingAnalysis, setPricingAnalysis] = useState<any>(null);
  const [calculatorPrefill, setCalculatorPrefill] = useState<PricingCalculatorPrefill | null>(null);
  const [simulationPackage, setSimulationPackage] = useState({
    dimensions: "", weight: "", logisticType: "", shippingMode: "", freeShipping: "false",
  });
  const [pricingLogisticType, setPricingLogisticType] = useState("");
  const [pricingScenario, setPricingScenario] = useState<"mc0" | "mc15" | "mc20" | "mc25" | "mc35" | "custom">("mc20");
  const [priceVariant, setPriceVariant] = useState<"base" | "3" | "6">("base");
  const [basePrincipalPrice, setBasePrincipalPrice] = useState(0);
  const [pricingRecalculationBusy, setPricingRecalculationBusy] = useState(false);
  const customPriceTimerRef = useRef<number | null>(null);
  const [shippingCapabilities, setShippingCapabilities] = useState<ShippingCapabilities | null>(null);
  const [shippingCapabilitiesLoading, setShippingCapabilitiesLoading] = useState(false);
  const [shippingCapabilitiesError, setShippingCapabilitiesError] = useState("");
  const [logisticsQuotes, setLogisticsQuotes] = useState<any>(null);
  const [quantityPricingEnabled, setQuantityPricingEnabled] = useState(false);
  const [quantityPrices, setQuantityPrices] = useState<QuantityPriceTier[]>([]);
  const [quantityPricingAnalysis, setQuantityPricingAnalysis] = useState<QuantityPricingAnalysis | null>(null);

  const [form, setForm] = useState({
    sku: "", name: "", title: "", brand: "", model: "", characteristics: "", description: "",
    price: "0", quantity: "1", count: "6", localPickup: false, warrantyType: "SELLER",
    warrantyDuration: "30", warrantyUnit: "days"
  });

  // Only persisted product fields count as unsaved changes. Transient API metadata is excluded.
  const editSignature = JSON.stringify({
    accountId, categoryId, form, attributes, quantityPricingEnabled, quantityPrices,
    simulationPackage, pricingLogisticType, productCost,
  });
  const dirty = Boolean(startMode && (versionId
    ? editSignature !== savedSignature
    : Boolean(form.sku.trim() || form.name.trim() || form.title.trim() || form.description.trim()
      || form.brand.trim() || form.model.trim() || form.characteristics.trim()
      || categoryId || Object.keys(attributes).length || uploadedImages.length || batchId
      || quantityPricingEnabled || quantityPrices.length || productCost !== "0"
      || form.price !== "0" || form.quantity !== "1")));
  useEffect(() => {
    const warnOnExit = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnOnExit);
    return () => window.removeEventListener("beforeunload", warnOnExit);
  }, [dirty]);

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
  const packageParts = packageDimensionParts(simulationPackage.dimensions);
  const packageDefaults = technicalPackageDefaults(fields, currentProductAttributes());
  const packageUsesTechnicalData = Boolean(
    (packageDefaults.length && packageParts.length === packageDefaults.length)
    || (packageDefaults.width && packageParts.width === packageDefaults.width)
    || (packageDefaults.height && packageParts.height === packageDefaults.height)
    || (packageDefaults.weight && simulationPackage.weight === packageDefaults.weight)
  );
  const selectedPricingTarget = publisherScenarioTarget(pricingAnalysis, pricingScenario);
  const selectedPricingBreakdown = publisherScenarioBreakdown(pricingAnalysis, pricingScenario, priceVariant);
  const displayedPrincipalPrice = Number(form.price) > 0
    ? Number(form.price)
    : Number(selectedPricingTarget?.gross_price || pricingAnalysis?.recommended_price || 0);
  const installmentBasePrice = basePrincipalPrice > 0 ? basePrincipalPrice : displayedPrincipalPrice;
  const installment3Price = installmentPrice(installmentBasePrice, pricingProfile.installment_3_markup_pct);
  const installment6Price = installmentPrice(installmentBasePrice, pricingProfile.installment_6_markup_pct);

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
    setTargetAccountIds(current => current.filter(id => result.some(account => account.id === id)));
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
            installment_3_markup_pct: Number(result.profile.installment_3_markup_pct || 0),
            installment_6_markup_pct: Number(result.profile.installment_6_markup_pct || 0),
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

  // Recovery is explicit: a stored job never attaches itself to a different product.
  useEffect(() => {
    setResumeJobId(accountId ? window.localStorage.getItem(activeJobStorageKey(accountId)) || "" : "");
  }, [accountId]);

  async function resumePreviousJob() {
    if (!resumeJobId) return;
    const result = await api<any>(`/api/jobs/${resumeJobId}`);
    trackedJobRef.current = resumeJobId;
    if (TERMINAL_JOB_STATES.includes(result.status)) {
      window.localStorage.removeItem(activeJobStorageKey(accountId));
      setResumeJobId("");
      setJob({...result, job_id: resumeJobId});
      setLastAction("Resultado del trabajo anterior consultado.");
    } else {
      setJob({...result, job_id: resumeJobId});
      watchJob(resumeJobId);
      setLastAction("Seguimiento del trabajo anterior reanudado.");
    }
    setActiveView("publisher");
    setPublisherStep("execution");
  }

  useEffect(() => {
    setTargetAccountIds(accountId ? [accountId] : []);
    setBatchIds([]);
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
    setBatchIds([]);
    setDrafts([]);
    setKeywordIntelligence(null);
    setSelectedDraftIds([]);
    setPricingAnalysis(null);
    setShippingCapabilities(null);
    setShippingCapabilitiesError("");
    setLogisticsQuotes(null);
  }, [accountId]);

  useEffect(() => {
    let cancelled = false;
    if (!accountId || !categoryId) {
      setShippingCapabilities(null);
      setShippingCapabilitiesError("");
    setLogisticsQuotes(null);
      setShippingCapabilitiesLoading(false);
      return () => { cancelled = true; };
    }

    setShippingCapabilitiesLoading(true);
    setShippingCapabilitiesError("");
    setLogisticsQuotes(null);
    loadShippingCapabilities(accountId, categoryId)
      .then(capabilities => {
        if (cancelled) return;
        setShippingCapabilities(capabilities);
        setSimulationPackage(current => ({
          ...current,
          shippingMode: capabilities.mode,
          freeShipping: current.freeShipping || "false",
          // Publicación: Flex se ofrece siempre que Mercado Libre lo habilite.
          logisticType: capabilities.flex_available
            ? capabilities.flex_logistic_type
            : capabilities.base_logistic_type,
        }));
        setPricingLogisticType(current => (
          current === capabilities.base_logistic_type
          || (capabilities.flex_available && current === capabilities.flex_logistic_type)
            ? current
            : capabilities.base_logistic_type
        ));
        setPricingAnalysis(null);
        setLogisticsQuotes(null);
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
    if (!fields.length) return;
    const defaults = technicalPackageDefaults(fields, currentProductAttributes());
    if (!defaults.length && !defaults.width && !defaults.height && !defaults.weight) return;
    setSimulationPackage(current => {
      const parts = packageDimensionParts(current.dimensions);
      const nextParts = {
        length: parts.length || defaults.length,
        width: parts.width || defaults.width,
        height: parts.height || defaults.height,
      };
      const nextDimensions = packageDimensionsValue(nextParts);
      const nextWeight = current.weight || defaults.weight;
      if (nextDimensions === current.dimensions && nextWeight === current.weight) return current;
      return {...current, dimensions: nextDimensions, weight: nextWeight};
    });
  }, [fields, attributes]);

  useEffect(() => {
    setQuantityPricingAnalysis(null);
  }, [
    accountId, categoryId, pricingListingTypeId, productCost, form.price,
    simulationPackage.dimensions, simulationPackage.weight, pricingLogisticType,
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


  async function loadExistingProduct() {
    if (!existingProduct) return;
    await takeEditLease(existingProduct.id);
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

    const savedQuantityPrices = Array.isArray(version.commercial?.quantity_prices_draft)
      ? version.commercial.quantity_prices_draft
      : Array.isArray(version.commercial?.quantity_prices) ? version.commercial.quantity_prices : [];
    setQuantityPrices(savedQuantityPrices.map((tier:any) => ({
      min_purchase_unit: Number(tier.min_purchase_unit),
      amount: Number(tier.amount),
    })));
    setQuantityPricingEnabled(Boolean(version.commercial?.quantity_pricing_enabled ?? savedQuantityPrices.length > 0));
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
      logisticType: String(savedPackage.publication_logistic_type || savedPackage.logistic_type || savedMarketplaceContext.logistic_type || ""),
      shippingMode: String(savedPackage.shipping_mode || savedMarketplaceContext.shipping_mode || ""),
      freeShipping: savedFreeShipping === true || savedFreeShipping === "true"
        ? "true"
        : "false",
    });
    setPricingLogisticType(String(savedPackage.pricing_logistic_type || savedPricingInputs.package?.logistic_type || savedMarketplaceContext.logistic_type || ""));
    setPricingScenario("mc20");
    setPriceVariant("base");
    setBasePrincipalPrice(Number(version.price) || 0);

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
    setBatchIds([]);
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
    const expected3 = Number(pricingProfile.installment_3_markup_pct || 0);
    const expected6 = Number(pricingProfile.installment_6_markup_pct || 0);
    const saved = await api<any>("/api/pricing/profile", {
      method: "PUT",
      body: JSON.stringify(pricingProfile),
    });
    if (saved.installment_3_markup_pct === undefined || saved.installment_6_markup_pct === undefined) {
      throw new Error("El backend activo no soporta todavía los porcentajes de 3/6 cuotas. Aplicá la migración 0014 y reiniciá el backend.");
    }
    const verified = await api<any>("/api/pricing/profile");
    if (!verified?.configured || !verified.profile) {
      throw new Error("La política económica no pudo verificarse después de guardarla.");
    }
    const persisted3 = Number(verified.profile.installment_3_markup_pct ?? NaN);
    const persisted6 = Number(verified.profile.installment_6_markup_pct ?? NaN);
    if (!Number.isFinite(persisted3) || !Number.isFinite(persisted6)
      || Math.abs(persisted3 - expected3) > 0.0001
      || Math.abs(persisted6 - expected6) > 0.0001) {
      throw new Error("Los porcentajes de cuotas no quedaron persistidos. Verificá que Alembic esté en 0014_pricing_installment_markups.");
    }
    const profile = verified.profile;
    setPricingConfigured(true);
    setPricingProfile({
      name: profile.name, channel: profile.channel, currency_id: profile.currency_id,
      target_margin_pct: Number(profile.target_margin_pct), minimum_margin_pct: Number(profile.minimum_margin_pct),
      installment_3_markup_pct: persisted3, installment_6_markup_pct: persisted6,
      vat_rate_pct: Number(profile.vat_rate_pct), iibb_rate_pct: Number(profile.iibb_rate_pct),
      ads_rate_pct: Number(profile.ads_rate_pct), refund_rate_pct: Number(profile.refund_rate_pct),
      monthly_units_projection: profile.monthly_units_projection, rounding_step: Number(profile.rounding_step),
      components: (profile.components || []).map((component:any) => ({
        name: component.name, kind: component.kind, value: Number(component.value), basis: component.basis, active: Boolean(component.active)
      })),
    });
    setPricingAnalysis(null);
    setMessage(`Configuración económica guardada. 3 cuotas +${persisted3}% · 6 cuotas +${persisted6}%.`);
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
        logistic_type: pricingLogisticType || simulationPackage.logisticType || null,
        shipping_mode: simulationPackage.shippingMode || null,
        free_shipping: simulationPackage.freeShipping === "true",
      },
    };
  }

  async function refreshLogisticsQuotes(price: number, logisticType = pricingLogisticType) {
    const listingTypeId = pricingListingTypeId;
    if (!accountId || !categoryId || !listingTypeId || price <= 0) return;
    if (!simulationPackage.dimensions || Number(simulationPackage.weight) <= 0) return;
    try {
      const quotes = await api<any>("/api/pricing/logistics-quotes", {
        method: "POST",
        body: JSON.stringify({
          account_id: accountId,
          category_id: categoryId,
          listing_type_id: listingTypeId,
          sale_price: price,
          dimensions: simulationPackage.dimensions,
          weight: Number(simulationPackage.weight),
          free_shipping: simulationPackage.freeShipping === "true",
          condition: "new",
          currency_id: "ARS",
        }),
      });
      setLogisticsQuotes(quotes);
      if (!pricingLogisticType && logisticType) setPricingLogisticType(logisticType);
    } catch {
      setLogisticsQuotes(null);
    }
  }

  async function simulateCurrentPrice(options?: {
    salePrice?: number | null;
    targetMarginPct?: number | null;
    scenario?: "mc0" | "mc15" | "mc20" | "mc25" | "mc35" | "custom";
    variant?: "base" | "3" | "6";
    logisticType?: string;
    updateBase?: boolean;
  }) {
    if (!pricingConfigured) throw new Error("Configurá primero Costos y rentabilidad.");
    const listingTypeId = pricingListingTypeId;
    if (!accountId || !categoryId || !listingTypeId) {
      throw new Error("Elegí cuenta, categoría y la modalidad de Mercado Libre que querés analizar.");
    }
    const effectiveLogisticType = options?.logisticType || pricingLogisticType || simulationPackage.logisticType;
    const requestedSalePrice = options && "salePrice" in options
      ? options.salePrice ?? null
      : (Number(form.price) > 0 ? Number(form.price) : null);
    const payload = {
      ...publisherPricingPayload(requestedSalePrice),
      package: {
        ...publisherPricingPayload(requestedSalePrice).package,
        logistic_type: effectiveLogisticType || null,
      },
      ...(options?.targetMarginPct !== undefined && options.targetMarginPct !== null
        ? {target_margin_pct: options.targetMarginPct}
        : {}),
    };
    setPricingRecalculationBusy(true);
    try {
      const result = await api<any>("/api/pricing/simulate", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const nextScenario = options?.scenario || (() => {
        const recommendedMargin = Number(result.audit?.recommended_target_margin_pct);
        if (Math.abs(recommendedMargin - 0) < 0.001) return "mc0" as const;
        if (Math.abs(recommendedMargin - 15) < 0.001) return "mc15" as const;
        if (Math.abs(recommendedMargin - 20) < 0.001) return "mc20" as const;
        if (Math.abs(recommendedMargin - 25) < 0.001) return "mc25" as const;
        if (Math.abs(recommendedMargin - 35) < 0.001) return "mc35" as const;
        return "custom" as const;
      })();
      const target = nextScenario === "mc0" ? result.mc0
        : nextScenario === "mc15" ? result.mc15
        : nextScenario === "mc20" ? result.mc20
        : nextScenario === "mc25" || nextScenario === "mc35" ? result.custom
        : null;
      const resolvedPrice = requestedSalePrice && requestedSalePrice > 0
        ? requestedSalePrice
        : Number(target?.gross_price || result.recommended_price || result.analyzed?.gross_price || 0);
      const nextAnalysis = {
        calculation_version: "pricing_v2_economic",
        ...result,
        publisher_inputs: {
          product_cost: Number(productCost),
          package: {
            dimensions: simulationPackage.dimensions || null,
            weight_kg: simulationPackage.weight ? Number(simulationPackage.weight) : null,
            logistic_type: effectiveLogisticType || null,
            shipping_mode: simulationPackage.shippingMode || null,
            free_shipping: simulationPackage.freeShipping === "true",
          },
        },
      };
      setPricingAnalysis(nextAnalysis);
      setPricingScenario(nextScenario);
      setPriceVariant(options?.variant || "base");
      if (resolvedPrice > 0) {
        setForm(current => ({...current, price: String(resolvedPrice)}));
        if (options?.updateBase !== false && (options?.variant || "base") === "base") {
          setBasePrincipalPrice(resolvedPrice);
        }
        await refreshLogisticsQuotes(resolvedPrice, effectiveLogisticType);
      }
      return nextAnalysis;
    } finally {
      setPricingRecalculationBusy(false);
    }
  }

  async function chooseMarginScenario(
    scenario: "mc0" | "mc15" | "mc20" | "mc25" | "mc35",
    margin: number,
  ) {
    if (!pricingAnalysis || scenario === "mc25" || scenario === "mc35") {
      await simulateCurrentPrice({
        salePrice: null,
        targetMarginPct: margin,
        scenario,
        variant: "base",
        updateBase: true,
      });
      return;
    }
    const target = pricingAnalysis[scenario];
    const price = Number(target?.gross_price || 0);
    if (!price) return;
    setPricingScenario(scenario);
    setPriceVariant("base");
    setBasePrincipalPrice(price);
    setForm(current => ({...current, price: String(price)}));
    await refreshLogisticsQuotes(price);
  }

  function scheduleCustomPriceRecalculation(raw: string) {
    setForm(current => ({...current, price: raw}));
    setPricingScenario("custom");
    setPriceVariant("base");
    if (customPriceTimerRef.current !== null) window.clearTimeout(customPriceTimerRef.current);
    const price = Number(raw);
    if (!Number.isFinite(price) || price <= 0 || !pricingConfigured) return;
    customPriceTimerRef.current = window.setTimeout(() => {
      void simulateCurrentPrice({salePrice: price, scenario: "custom", variant: "base", updateBase: true})
        .catch(reason => notify(reason instanceof Error ? reason.message : "No fue posible recalcular el precio.", "error"));
    }, 450);
  }

  async function calculateInstallmentVariant(term: 3 | 6) {
    const base = basePrincipalPrice > 0 ? basePrincipalPrice : Number(form.price);
    if (!Number.isFinite(base) || base <= 0) throw new Error("Calculá primero el precio principal.");
    const markup = term === 3 ? pricingProfile.installment_3_markup_pct : pricingProfile.installment_6_markup_pct;
    const financedPrice = installmentPrice(base, markup);
    await simulateCurrentPrice({
      salePrice: financedPrice,
      scenario: pricingScenario,
      variant: term === 3 ? "3" : "6",
      updateBase: false,
    });
  }

  async function selectPricingLogistics(logisticType: string) {
    setPricingLogisticType(logisticType);
    const currentPrice = Number(form.price);
    if (!pricingAnalysis || currentPrice <= 0) {
      if (currentPrice > 0) await refreshLogisticsQuotes(currentPrice, logisticType);
      return;
    }

    const marginByScenario: Partial<Record<typeof pricingScenario, number>> = {
      mc0: 0, mc15: 15, mc20: 20, mc25: 25, mc35: 35,
    };
    const targetMargin = marginByScenario[pricingScenario];

    // When a target MC is selected, changing logistics keeps that target and
    // recalculates the required principal price. A custom price stays fixed.
    if (targetMargin !== undefined) {
      const activeVariant = priceVariant;
      const baseAnalysis = await simulateCurrentPrice({
        salePrice: null,
        targetMarginPct: targetMargin,
        scenario: pricingScenario,
        variant: "base",
        logisticType,
        updateBase: true,
      });
      if (activeVariant !== "base") {
        const target = publisherScenarioTarget(baseAnalysis, pricingScenario);
        const recalculatedBase = Number(target?.gross_price || baseAnalysis?.recommended_price || 0);
        if (recalculatedBase > 0) {
          const markup = activeVariant === "3"
            ? pricingProfile.installment_3_markup_pct
            : pricingProfile.installment_6_markup_pct;
          await simulateCurrentPrice({
            salePrice: installmentPrice(recalculatedBase, markup),
            scenario: pricingScenario,
            variant: activeVariant,
            logisticType,
            updateBase: false,
          });
        }
      }
      return;
    }

    await simulateCurrentPrice({
      salePrice: currentPrice,
      scenario: "custom",
      variant: priceVariant,
      logisticType,
      updateBase: priceVariant === "base",
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
    const analysisByQuantity = new Map(
      normalized.tiers.map(tier => [tier.minPurchaseUnit, tier])
    );
    setQuantityPrices(current => current.map(tier => {
      const analysis = analysisByQuantity.get(tier.min_purchase_unit);
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

  function updatePackageDimensionPart(part: "length" | "width" | "height", value: string) {
    const current = packageDimensionParts(simulationPackage.dimensions);
    setSimulationPackage(previous => ({
      ...previous,
      dimensions: packageDimensionsValue({...current, [part]: value}),
    }));
    setPricingAnalysis(null);
    setLogisticsQuotes(null);
  }

  function currentProductAttributes() {
    return {
      ...attributes,
      ...(form.brand.trim() ? {BRAND: form.brand.trim()} : {}),
      ...(form.model.trim() ? {MODEL: form.model.trim()} : {}),
    };
  }

  function quantityPricingSnapshot() {
    const draft = quantityPricingEnabled ? quantityPrices.map(tier => ({
      min_purchase_unit: Number(tier.min_purchase_unit),
      amount: Number(tier.amount),
    })) : [];
    // El borrador comercial nunca debe confundirse con los escalones enviados a ML.
    // Sólo se habilita el envío de una tabla completa y compatible con las reglas B2B.
    const ordered = [...draft].sort((a, b) => a.min_purchase_unit - b.min_purchase_unit);
    const basePrice = Number(form.price);
    const valid = ordered.length > 0 && ordered.length <= 5 && Number.isFinite(basePrice) && basePrice > 0
      && ordered.every((tier, index) =>
        Number.isInteger(tier.min_purchase_unit) && tier.min_purchase_unit > 1
        && Number.isFinite(tier.amount) && tier.amount > 0
        && tier.amount < (index === 0 ? basePrice : ordered[index - 1].amount)
        && (index === 0 || tier.min_purchase_unit !== ordered[index - 1].min_purchase_unit)
      );
    return {draft, publishable: valid ? ordered : [], valid};
  }

  function currentCommercialContract() {
    const tiers = quantityPricingSnapshot();
    return {
      buying_mode: "buy_it_now",
      warranty: {
        type: form.warrantyType,
        duration: form.warrantyType === "SELLER" ? Number(form.warrantyDuration) : 0,
        unit: form.warrantyUnit,
      },
      quantity_pricing_enabled: quantityPricingEnabled,
      quantity_prices_draft: tiers.draft,
      quantity_prices: tiers.publishable,
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
          pricing_logistic_type: pricingLogisticType || null,
          shipping_mode: simulationPackage.shippingMode || null,
          free_shipping: simulationPackage.freeShipping === "true",
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
      logisticType: pricingLogisticType || simulationPackage.logisticType,
      shippingMode: simulationPackage.shippingMode,
      freeShipping: simulationPackage.freeShipping,
    });
    setActiveView("price-calculator");
  }

  function warnQuantityPricing() {
    if (!quantityPricingEnabled) return;
    const snapshot = quantityPricingSnapshot();
    if (!snapshot.valid) {
      notify("Ficha guardable: los escalones mayoristas incompletos o incompatibles con Mercado Libre se conservarán como borrador y NO se publicarán hasta corregirlos.", "warning");
      return;
    }
    const analysisByQuantity = new Map(
      (quantityPricingAnalysis?.tiers || []).map(tier => [tier.minPurchaseUnit, tier])
    );
    const belowFloor = snapshot.publishable.filter(tier => {
      const analysis = analysisByQuantity.get(tier.min_purchase_unit);
      return analysis && tier.amount + 0.005 < analysis.minimumPrice;
    });
    if (belowFloor.length) {
      notify(
        `Precio(s) desde ${belowFloor.map(tier => tier.min_purchase_unit).join(", ")} unidades por debajo del piso de MC configurado. Es una advertencia económica: se conservarán tus precios manuales.`,
        "warning"
      );
    } else if (snapshot.publishable.some(tier => !analysisByQuantity.has(tier.min_purchase_unit))) {
      notify("Sin simulación económica vigente para todos los escalones. Podés operar con los precios ingresados; el cálculo es opcional.", "warning");
    }
  }

  async function createProduct() {
    if (!accountId || !categoryId) throw new Error("Elegí cuenta y una categoría hoja sugerida por Mercado Libre.");
    warnQuantityPricing();
    if (!form.sku.trim() || !form.name.trim()) throw new Error("Completá SKU y nombre interno.");
    if (categoryContractLoading) {
      throw new Error("Esperá a que termine de cargar el contrato de categoría de Mercado Libre.");
    }
    // Guardar ficha y adjuntar imágenes no requiere validación de publicación.
    // La completitud de atributos y la logística se comprueban antes de publicar.
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
    const matched = existingProduct?.internal_sku === form.sku.trim() ? existingProduct : null;
    const leaseToken = matched ? await takeEditLease(matched.id) : null;
    const headers: Record<string, string> = {};
    if (matched && leaseToken) {
      headers["X-Product-Lease-Token"] = leaseToken;
      headers["X-Expected-Version"] = String(matched.latest_version.version_number);
    }
    const result = await api<any>("/api/products", {method:"POST", headers, body:JSON.stringify(payload)});
    // A new ficha also requires a lease for its subsequent image uploads.
    if (result.created_master) await takeEditLease(String(result.product_id));
    setExistingProduct(previous => previous && previous.id === result.product_id
      ? {...previous, latest_version: {...previous.latest_version, version_number: result.version_number, id: result.version_id}}
      : previous);
    setVersionId(result.version_id);
    setProductMasterId(String(result.product_id || ""));
    setUploadedImages([]);
    setSavedSignature(editSignature);
    setLastSavedAt(new Date().toLocaleString("es-AR"));
    setLastAction("Ficha guardada. Podés cargar las imágenes.");
    setPublisherStep("images");
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
    warnQuantityPricing();
    if (!requiredAttributesComplete) {
      throw new Error("Completá los atributos obligatorios antes de revalidar el lote.");
    }
    if (!shippingReady) {
      throw new Error("Esperá a que Mercado Libre confirme la configuración de Mercado Envíos antes de revalidar.");
    }

    if (!versionId || !productMasterId) {
      throw new Error("No se identificó la versión de ficha asociada al lote. Volvé a cargar la ficha.");
    }
    const correctionToken = await takeEditLease(productMasterId);
    const correction = await api<any>(`/api/drafts/batches/${batchId}/product-correction`, {
      method:"POST",
      headers: {
        "X-Product-Lease-Token": correctionToken,
        "X-Expected-Product-Version": versionId,
      },
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
    setExistingProduct(previous => previous && previous.id === productMasterId
      ? {...previous, latest_version: {...previous.latest_version, version_number: correction.version_number, id: correction.version_id}}
      : previous);
    setUploadedImages((correction.images || []) as UploadedImage[]);
    setSavedSignature(editSignature);
    setLastSavedAt(new Date().toLocaleString("es-AR"));
    setLastAction("Correcciones guardadas y lote revalidado.");

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
    if (!productMasterId) throw new Error("No se identificó la ficha para subir imágenes");

    const pending = Array.from(files);
    const batchSize = 6;
    setImageUploadBusy(true);

    try {
      let uploaded = 0;
      const failures: string[] = [];

      for (let start = 0; start < pending.length; start += batchSize) {
        const chunk = pending.slice(start, start + batchSize);
        const fd = new FormData();
        chunk.forEach(file => fd.append("files", file));

        const result = await api<any>(
          `/api/products/versions/${versionId}/images/batch`,
          {method:"POST", body:fd, headers: {"X-Product-Lease-Token":
            await takeEditLease(productMasterId)}}
        );
        uploaded += Number(result.uploaded_count || 0);
        (result.failed || []).forEach((failure:any) => {
          failures.push(`${failure.name || "Imagen"}: ${failure.detail || "No se pudo cargar."}`);
        });
      }

      const confirmed = await refreshUploadedImages(versionId);
      if (failures.length) {
        throw new Error(
          `${uploaded} imagen(es) cargadas y ${failures.length} fallaron. ${failures.join(" · ")}`
        );
      }

      setMessage(`${uploaded} imagen(es) cargadas y ${confirmed.length} confirmadas por el backend.`);
      if (confirmed.length) {
        setLastAction(`${confirmed.length} imágenes confirmadas. Siguiente: generar borradores.`);
        setPublisherStep("images");
      }
    } finally {
      setImageUploadBusy(false);
    }
  }

  async function persistImageOrder(next: UploadedImage[]) {
    if (!versionId || !productMasterId) return;
    await api(`/api/products/versions/${versionId}/images/order`, {
      method: "PUT",
      headers: {"X-Product-Lease-Token": await takeEditLease(productMasterId)},
      body: JSON.stringify({image_ids: next.map(image => image.id)}),
    });
    setUploadedImages(next.map((image, index) => ({...image, position: index + 1})));
    setLastAction("Orden de imágenes guardado.");
  }

  async function moveImage(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= uploadedImages.length) return;
    const next = [...uploadedImages];
    [next[index], next[target]] = [next[target], next[index]];
    await persistImageOrder(next);
  }

  async function reorderImageByDrop(sourceId: string, targetId: string) {
    if (!sourceId || !targetId || sourceId === targetId) return;
    const sourceIndex = uploadedImages.findIndex(image => image.id === sourceId);
    const targetIndex = uploadedImages.findIndex(image => image.id === targetId);
    if (sourceIndex < 0 || targetIndex < 0) return;
    const next = [...uploadedImages];
    const [moved] = next.splice(sourceIndex, 1);
    next.splice(targetIndex, 0, moved);
    await persistImageOrder(next);
  }

  async function removeUploadedImage(imageId: string) {
    if (!versionId || !productMasterId) return;
    await api(`/api/products/versions/${versionId}/images/${imageId}`, {
      method: "DELETE",
      headers: {"X-Product-Lease-Token": await takeEditLease(productMasterId)},
    });
    await refreshUploadedImages(versionId);
    setLastAction("Imagen eliminada y orden normalizado.");
  }

  function updateCommercialAllocation(commercialIntent: string, raw: string) {
    const count = Math.max(0, Number(raw) || 0);
    setCommercialAllocations(rows => rows.map(
      row => row.commercial_intent === commercialIntent ? {...row, count} : row
    ));
  }

  async function generateDrafts() {
    if (distributionInvalid) {
      throw new Error("La distribución comercial debe sumar exactamente el total de publicaciones por cuenta.");
    }
    const confirmedImages = await refreshUploadedImages();
    if (confirmedImages.length === 0) {
      throw new Error("Las imágenes seleccionadas todavía no fueron cargadas al backend. Cargá al menos una imagen válida antes de generar borradores.");
    }
    const targets = targetAccountIds.length ? targetAccountIds : (accountId ? [accountId] : []);
    if (!targets.length) throw new Error("Seleccioná al menos una cuenta de Mercado Libre.");
    setGenerationActive(true);
    try {
      const distribution = commercialAllocations
        .filter(row => row.count > 0)
        .map(row => ({commercial_intent: row.commercial_intent, count: row.count}));
      const createdBatchIds: string[] = [];
      const collectedDrafts: Draft[] = [];
      const reservedTitles: string[] = [];
      let firstKeywordIntelligence: any = null;

      for (const targetAccountId of targets) {
        const result = await api<any>("/api/drafts/generate", {
          method:"POST",
          body:JSON.stringify({
            product_version_id: versionId,
            account_id: targetAccountId,
            count: totalCount,
            commercial_distribution: distribution,
            reserved_titles: reservedTitles,
          })
        });
        const detail = await api<any>(`/api/drafts/batches/${result.batch_id}`);
        const account = accounts.find(item => item.id === targetAccountId);
        createdBatchIds.push(String(result.batch_id));
        if (!firstKeywordIntelligence) firstKeywordIntelligence = detail.keyword_intelligence || null;
        for (const draft of detail.drafts || []) {
          collectedDrafts.push({
            ...draft,
            batch_id: String(result.batch_id),
            account_id: targetAccountId,
            account_nickname: account?.nickname || targetAccountId,
          });
          reservedTitles.push(String(draft.title));
        }
      }

      setBatchIds(createdBatchIds);
      setBatchId(createdBatchIds[0] || "");
      setDrafts(collectedDrafts);
      setKeywordIntelligence(firstKeywordIntelligence);
      setSelectedDraftIds([]);
      setLastAction(`${collectedDrafts.length} borradores generados en ${createdBatchIds.length} cuenta(s). Siguiente: revisar y validar.`);
      setPublisherStep("review");
      setMessage(`${collectedDrafts.length} borradores multicuenta generados sin repetir títulos dentro de la operación.`);
    } finally {
      setGenerationActive(false);
    }
  }

  async function loadBatches(ids = batchIds.length ? batchIds : (batchId ? [batchId] : [])) {
    if (!ids.length) return;
    const details = await Promise.all(ids.map(id => api<any>(`/api/drafts/batches/${id}`)));
    const combined: Draft[] = [];
    for (const detail of details) {
      const account = accounts.find(item => item.id === String(detail.account_id));
      for (const draft of detail.drafts || []) {
        combined.push({
          ...draft,
          batch_id: String(detail.id),
          account_id: String(detail.account_id),
          account_nickname: account?.nickname || String(detail.account_id),
        });
      }
    }
    setDrafts(combined);
    setKeywordIntelligence(details[0]?.keyword_intelligence || null);
    setSelectedDraftIds(current => current.filter(draftId => combined.some((draft: Draft) => draft.id === draftId)));
  }

  async function loadBatch(id = batchId) {
    if (!id) return;
    if (batchIds.length > 1) {
      await loadBatches(batchIds);
      return;
    }
    const result = await api<any>(`/api/drafts/batches/${id}`);
    const account = accounts.find(item => item.id === String(result.account_id));
    const enriched = (result.drafts || []).map((draft: Draft) => ({...draft, batch_id: String(result.id), account_id: String(result.account_id), account_nickname: account?.nickname || String(result.account_id)}));
    setDrafts(enriched);
    setKeywordIntelligence(result.keyword_intelligence || null);
    setSelectedDraftIds(current => current.filter(draftId => enriched.some((draft: Draft) => draft.id === draftId)));
  }

  async function validateDraft(id: string) {
    setValidationActive(true);
    try {
      const result = await api<any>(`/api/drafts/${id}/validate`, {method:"POST"});
      await loadBatch();
      const firstIssue = result.errors?.[0];
      setMessage(
        result.valid
          ? "El borrador pasó la validación previa de Mercado Libre."
          : `Falta corregir: ${firstIssue?.message || "Mercado Libre rechazó la validación previa."}`
      );
    } finally {
      setValidationActive(false);
    }
  }

  async function approveDraft(id: string) {
    await api(`/api/drafts/${id}/approve`, {method:"POST"});
    await loadBatch();
  }

  async function validateAll() {
    const ids = batchIds.length ? batchIds : (batchId ? [batchId] : []);
    if (!ids.length) return;
    setValidationActive(true);
    try {
      const results = [];
      for (const id of ids) results.push(await api<any>(`/api/drafts/batches/${id}/validate`, {method:"POST"}));
      await loadBatches(ids);
      const ready = results.reduce((sum, result) => sum + Number(result.ready || 0), 0);
      const invalid = results.reduce((sum, result) => sum + Number(result.invalid || 0), 0);
      const firstIssue = results.flatMap(result => result.results || []).flatMap((item:any) => item.errors || [])[0];
      setMessage(`${ready} borrador(es) listos y ${invalid} con observaciones después de validar ${ids.length} cuenta(s).` + (firstIssue?.message ? ` Falta corregir: ${firstIssue.message}` : ""));
    } finally {
      setValidationActive(false);
    }
  }

  async function approveReady() {
    const ids = batchIds.length ? batchIds : (batchId ? [batchId] : []);
    if (!ids.length) return;
    let approved = 0;
    for (const id of ids) {
      const result = await api<any>(`/api/drafts/batches/${id}/approve-ready`, {method:"POST"});
      approved += Number(result.approved || 0);
    }
    await loadBatches(ids);
    setMessage(`${approved} borrador(es) aprobados en ${ids.length} cuenta(s).`);
  }

  function watchJob(jobId: string) {
    const es = jobEvents(jobId);
    let pollingTimer: number | null = null;

    const applyJobState = (data: any) => {
      // An earlier job must not write progress into a newly started publication.
      if (trackedJobRef.current !== jobId) {
        es.close();
        if (pollingTimer !== null) window.clearInterval(pollingTimer);
        return true;
      }
      setJob({...data, job_id: jobId});
      if (TERMINAL_JOB_STATES.includes(data.status)) {
        es.close();
        if (pollingTimer !== null) window.clearInterval(pollingTimer);
        if (accountId) window.localStorage.removeItem(activeJobStorageKey(accountId));
        setResumeJobId("");
        setLastAction("Ejecución terminada. Revisá el resultado antes de crear una nueva publicación.");
        setSelectedDraftIds([]);
        loadBatches().catch(() => undefined);
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
    const multiAccount = new Set(drafts.filter(d => selectedApprovedDraftIds.includes(d.id)).map(d => d.account_id).filter(Boolean)).size > 1;
    const result = await api<any>(multiAccount ? "/api/publication/jobs/multi" : "/api/publication/jobs", {
      method:"POST",
      body:JSON.stringify(multiAccount
        ? {draft_ids: selectedApprovedDraftIds}
        : {batch_id: batchId, draft_ids: selectedApprovedDraftIds})
    });
    setJob(result);
    trackedJobRef.current = result.job_id;
    if (accountId) window.localStorage.setItem(activeJobStorageKey(accountId), result.job_id);
    setResumeJobId(result.job_id);
    setLastAction("Publicación iniciada. Consultá el progreso y el resultado.");
    setPublisherStep("execution");
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

  function resetPublicationState(nextAccountId = accountId) {
    releaseEditLease();
    // The persisted job reference remains available for explicit recovery.
    setAccountId(nextAccountId);
    setStartMode("");
    setMlaPreview(null);
    setMlaImportId("");
    setTechnicalReuse(null);
    setReusedAttributeIds(new Set());
    setProductMasterId("");
    setExistingProduct(null);
    setDismissedExistingSku("");
    setCategoryId("");
    setSelectedCategoryName("");
    setCategorySuggestions([]);
    setFields([]);
    setRequirements([]);
    setProductIdentifierContract(null);
    setProductIdentifierMode("");
    setAttributes({});
    setCustomAttributeFields({});
    setShowSecondaryAttributes(false);
    setTitleMaxLength(null);
    setVersionId("");
    setUploadedImages([]);
    setBatchId("");
    setBatchIds([]);
    setDrafts([]);
    setSelectedDraftIds([]);
    setKeywordIntelligence(null);
    setJob(null);
    trackedJobRef.current = null;
    setCommercialOptions([]);
    setCommercialAllocations([]);
    setPricingListingTypeId("");
    setQuantityPricingEnabled(false);
    setQuantityPrices([]);
    setQuantityPricingAnalysis(null);
    setPricingAnalysis(null);
    setProductCost("0");
    setSimulationPackage({dimensions:"", weight:"", logisticType:"", shippingMode:"", freeShipping:"false"});
    setPricingLogisticType("");
    setPricingScenario("mc20");
    setPriceVariant("base");
    setBasePrincipalPrice(0);
    setShippingCapabilities(null);
    setShippingCapabilitiesError("");
    setLogisticsQuotes(null);
    setForm({sku:"", name:"", title:"", brand:"", model:"", characteristics:"", description:"",
      price:"0", quantity:"1", count:"6", localPickup:false, warrantyType:"SELLER",
      warrantyDuration:"30", warrantyUnit:"days"});
    setSavedSignature("");
    setLastSavedAt("");
    setLastAction("Nueva ficha preparada. Elegí cómo comenzar.");
    setPublisherStep("category");
    setActiveView("publisher");
  }

  function confirmDiscard() {
    if (!dirty && !versionId && !batchId && !job && !uploadedImages.length) return true;
    return window.confirm(dirty
      ? "Tenés cambios sin guardar. Si continuás, se descartarán los cambios locales; las fichas y publicaciones ya guardadas no se borrarán. ¿Continuar?"
      : "Vas a salir del trabajo actual. Las fichas y publicaciones guardadas permanecerán intactas, pero se limpiará el contexto visible. ¿Continuar?");
  }

  function beginNewPublication() {
    if (!confirmDiscard()) return;
    resetPublicationState();
    notify("Nueva publicación preparada. Los datos del trabajo anterior no se copiaron.", "success");
  }

  function startFromZero() {
    if (!confirmDiscard()) return;
    resetPublicationState();
    setStartMode("MANUAL");
    setMessage("Carga manual iniciada. Completá los datos del producto y buscá su categoría.");
  }

  function switchAccount(nextAccountId: string) {
    if (nextAccountId === accountId || !confirmDiscard()) return;
    resetPublicationState(nextAccountId);
  }

  async function run<T>(fn: () => Promise<T>) {
    setBusy(true);
    try { await fn(); } catch (e:any) { notify(e instanceof Error ? e.message : String(e), "error"); }
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
      <div className="toastViewport" aria-label="Notificaciones">
        {toasts.map(toast => <ToastItem key={toast.id} notice={toast} dismiss={dismissToast}/>)}
      </div>
      <aside>
        <div className="brand">Publicador ML</div>
        <div className="muted">Gestión masiva de publicaciones</div>
        <nav className="primaryNav" aria-label="Navegación principal">
          <button type="button" className={activeView === "publisher" ? "active" : ""} onClick={()=>setActiveView("publisher")}>Publicador</button>
          <button type="button" className={activeView === "manager" ? "active" : ""} onClick={()=>setActiveView("manager")}>Gestor e historial</button>
          <button type="button" className={activeView === "pricing-settings" ? "active" : ""} onClick={()=>setActiveView("pricing-settings")}>Configuración</button>
          <button type="button" className={activeView === "price-calculator" ? "active" : ""} onClick={()=>setActiveView("price-calculator")}>Calculadora</button>
          <button type="button" className="newPublicationAction" onClick={beginNewPublication}>+ Nueva publicación</button>
        </nav>
        {activeView === "publisher" && <div className="sideSectionLabel">ETAPAS DE LA FICHA</div>}
        {activeView === "publisher" && <nav className="sideSteps" aria-label="Etapas del publicador">
          {([
            ["category", "Producto y categoría", contextComplete],
            ["technical", "Ficha técnica", productComplete],
            ["prices", "Precios", Number(form.price) > 0 && shippingReady],
            ["images", "Imágenes y lote", uploadedImages.length > 0],
            ["review", "Revisión", draftsComplete],
            ["execution", "Publicación", Boolean(terminalJob)],
          ] as const).map(([key, label, complete], index) =>
            <button
              key={key}
              type="button"
              className={`wizardStep ${publisherStep === key ? "active" : complete ? "done" : ""}`}
              aria-current={publisherStep === key ? "step" : undefined}
              onClick={() => {setActiveView("publisher"); setPublisherStep(key);}}
            ><span>{index + 1}</span>{label}</button>
          )}
        </nav>}
        <div className="status">
          <span className="dot"/> Publicación real protegida por configuración
        </div>
      </aside>

      <main style={{display: activeView === "manager" ? undefined : "none"}}>
        {activeView === "manager" && <PublicationManager canAudit={operatorRole !== "OPERATOR"}/>}
      </main>

      <main style={{display: activeView === "pricing-settings" ? undefined : "none"}}>
        
        <PricingProfileEditor profile={pricingProfile} busy={busy} onChange={setPricingProfile} onSave={() => run(savePricingProfile)} />
      </main>

      <main style={{display: activeView === "price-calculator" ? undefined : "none"}}>
        
        <PriceCalculator
          accountId={accountId}
          accounts={accounts}
          pricingProfile={pricingProfile}
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

        <section className="workflowContext" aria-label="Estado de la publicación actual">
          <div><span>Producto actual</span><strong>{form.sku.trim() || "Sin SKU"}</strong></div>
          <div><span>Etapa actual</span><strong>{({category:"Producto y categoría", technical:"Ficha técnica", prices:"Precios", images:"Imágenes", review:"Revisión", execution:"Publicación"} as const)[publisherStep]}</strong></div>
          <div><span>Última acción</span><strong>{lastAction}</strong></div>
          <div><span>Último guardado</span><strong>{lastSavedAt || "Aún no guardada"}{dirty ? " · Cambios pendientes" : ""}</strong></div>
        </section>
        {resumeJobId && (!job || (job.job_id !== resumeJobId && job.id !== resumeJobId)) && <div className="resumeJobNotice">
          <span>Hay un trabajo anterior registrado para esta cuenta. No se mezclará con la ficha actual.</span>
          <button type="button" className="secondary" onClick={()=>run(resumePreviousJob)}>Consultar trabajo anterior</button>
        </div>}
        <section className="summaryBar">
          <div><span>Cuenta</span><b>{selectedAccount?.nickname || "Sin seleccionar"}</b></div>
          <div><span>Categoría</span><b>{selectedCategoryName || "Sin seleccionar"}</b></div>
          <div><span>Ficha</span><b className={versionId ? "ok" : ""}>{versionId ? "Guardada" : "Pendiente"}</b></div>
          <div><span>Borradores</span><b>{drafts.length}</b></div>
        </section>

        


        <section className="card" style={{display: publisherStep === "category" ? undefined : "none"}}>
          <div className="sectionTitle"><span>1</span> Producto y categoría</div>
          <div className="grid2">
            <label>Cuenta
              <select value={accountId} onChange={e=>switchAccount(e.target.value)}>
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

            {startMode && <div className="multiAccountSelector publisherStartAccounts">
              <div>
                <h3>¿En qué cuentas querés publicar?</h3>
                <p>Seleccioná una o ambas cuentas. La cuenta elegida arriba se usa como referencia para traer la publicación existente y mostrar el pricing; cada cuenta seleccionada se genera, valida y publica de forma independiente.</p>
              </div>
              <div className="multiAccountGrid">
                {accounts.map(account => <label className={`accountCheck ${targetAccountIds.includes(account.id) ? "selected" : ""}`} key={account.id}>
                  <input
                    type="checkbox"
                    checked={targetAccountIds.includes(account.id)}
                    onChange={event=>setTargetAccountIds(current=>event.target.checked ? Array.from(new Set([...current, account.id])) : current.filter(id=>id!==account.id))}
                  />
                  <span>{account.nickname}</span>
                </label>)}
              </div>
              <small>Podés publicar en ambas cuentas en la misma operación. Los borradores, validaciones, títulos, estados y resultados se mantienen separados por cuenta.</small>
            </div>}

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
            <label>SKU<input disabled={!accountId} value={form.sku} onChange={e=>{if (editLeaseRef.current) releaseEditLease(); setForm({...form,sku:e.target.value}); setDismissedExistingSku("");}}/>
              {skuLookupBusy && <small className="helper">Buscando ficha guardada…</small>}
            </label>
            <label>Nombre del producto<input disabled={!accountId} value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
            <label>Título descriptivo<input disabled={!accountId} value={form.title} onChange={e=>setForm({...form,title:e.target.value})}/></label>
            <label>Marca<input disabled={!accountId} value={form.brand} onChange={e=>setForm({...form,brand:e.target.value})}/></label>
            <label>Modelo<input disabled={!accountId} value={form.model} onChange={e=>setForm({...form,model:e.target.value})}/></label>
            <label>Características conocidas<input disabled={!accountId} value={form.characteristics} onChange={e=>setForm({...form,characteristics:e.target.value})}/></label>
          </div>

          {editLease && <div className="existingSkuNotice" role="status">
            Edición exclusiva activa. Se renueva mientras mantenés esta ficha abierta.
            <button type="button" className="secondary" onClick={releaseEditLease}>Liberar edición</button>
          </div>}
          {existingProduct && dismissedExistingSku !== form.sku.trim() && <div className="existingSkuNotice">
            <div>
              <b>Este SKU ya tiene una ficha guardada.</b>
              <span>Última versión: {existingProduct.latest_version.version_number}. Podés recuperar sus datos o seguir escribiendo normalmente. El SKU no limita el título ni la categoría.</span>
            </div>
            <div className="existingSkuActions">
              <button type="button" className="secondary" onClick={()=>run(loadExistingProduct)}>Cargar datos guardados</button>
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

        <section className={`card ${!contextComplete ? "locked" : ""}`} style={{display: ["technical", "prices"].includes(publisherStep) ? undefined : "none"}}>
          <div className="sectionTitle"><span>2</span> {publisherStep === "prices" ? "Precios" : "Ficha técnica"}</div>
          <div style={{display: publisherStep === "technical" ? undefined : "none"}}>
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
            <label>Stock<input disabled={!contextComplete} type="number" value={form.quantity} onChange={e=>setForm({...form,quantity:e.target.value})}/></label>
          </div>
          </div>
          <div style={{display: publisherStep === "prices" ? undefined : "none"}} className="publisherPricingUnified">
            <div className="publisherPricingHeader">
              <div>
                <div className="publisherPricingTitleRow">
                  <h2>Precios</h2>
                  <span className="pricingConfigPill">ⓘ 3 y 6 cuotas se configuran en Configuración</span>
                </div>
                <p>Calculá tus costos, compará logística y definí el precio de venta.</p>
              </div>
              {!pricingConfigured && <button type="button" className="secondary" onClick={()=>setActiveView("pricing-settings")}>Configurar política económica</button>}
            </div>

            <div className="publisherPricingTopGrid">
              <label className="publisherPricingField">
                <span>Costo del producto (con IVA)</span>
                <div className="moneyInput"><span>$</span><input disabled={!contextComplete} type="number" min="0" step="0.01" value={productCost} onChange={e=>{setProductCost(e.target.value);setPricingAnalysis(null);setBasePrincipalPrice(0);}} placeholder="0,00"/></div>
                <small>Es el único costo que cargás por producto.</small>
              </label>
              <label className="publisherPricingField">
                <span>Precio de venta (opcional)</span>
                <div className="moneyInput"><span>$</span><input disabled={!contextComplete} type="number" min="0" step="0.01" value={form.price === "0" ? "" : form.price} onChange={e=>scheduleCustomPriceRecalculation(e.target.value)} placeholder="Ej. 18.990"/></div>
                <small>Si lo dejás vacío, se calculará automáticamente.</small>
              </label>
              <div className="publisherPackageFields">
                <div className="publisherPackageHeader">
                  <b>Medidas del paquete</b>
                  {packageUsesTechnicalData && <span className="technicalAutofillPill">▣ Autocompletado desde ficha técnica</span>}
                </div>
                <div className="publisherPackageGrid">
                  <label>Largo (cm)<input disabled={!contextComplete} type="number" min="0" step="0.01" value={packageParts.length} onChange={e=>updatePackageDimensionPart("length", e.target.value)}/></label>
                  <label>Ancho (cm)<input disabled={!contextComplete} type="number" min="0" step="0.01" value={packageParts.width} onChange={e=>updatePackageDimensionPart("width", e.target.value)}/></label>
                  <label>Alto (cm)<input disabled={!contextComplete} type="number" min="0" step="0.01" value={packageParts.height} onChange={e=>updatePackageDimensionPart("height", e.target.value)}/></label>
                  <label>Peso (kg)<input disabled={!contextComplete} type="number" min="0.01" step="0.01" value={simulationPackage.weight} onChange={e=>{setSimulationPackage(current=>({...current,weight:e.target.value}));setPricingAnalysis(null);setLogisticsQuotes(null);}}/></label>
                </div>
                <small>Si falta algún dato, podés completarlo manualmente.</small>
              </div>
            </div>

            <div className="publisherPricingWorkspace">
              <div className="publisherPricingWorkbench">
                <section className="publisherLogisticsSection">
                  <div className="publisherPricingSubheader">
                    <div><h3>Logística</h3><p>Compará las opciones y elegí cuál usar en el cálculo principal.</p></div>
                    <span>Flex se ofrece siempre{shippingCapabilities && !shippingCapabilities.flex_available ? " cuando Mercado Libre lo habilita." : "."}</span>
                  </div>
                  {shippingCapabilitiesError && <div className="shippingCapabilityError">{shippingCapabilitiesError}</div>}
                  <div className="publisherLogisticsCards">
                    <button
                      type="button"
                      className={`publisherLogisticsCard ${pricingLogisticType === shippingCapabilities?.base_logistic_type ? "selected" : ""}`}
                      disabled={!shippingCapabilities || pricingRecalculationBusy}
                      onClick={()=>shippingCapabilities && void selectPricingLogistics(shippingCapabilities.base_logistic_type)}
                    >
                      <div className="publisherLogisticsCardTitle"><span className="radioDot"/><b>Mercado Envíos / Colecta</b>{pricingLogisticType === shippingCapabilities?.base_logistic_type && <em>Seleccionada</em>}</div>
                      <div className="publisherLogisticsCardBody">
                        <div><strong>{logisticsQuotes?.colecta?.available ? money(logisticsQuotes.colecta.seller_cost) : "—"}</strong><small>Costo logístico estimado</small></div>
                        <div className="publisherLogisticsMeta"><span>Modalidad: {shippingCapabilities?.base_logistic_type || "Pendiente"}</span><span>{logisticsQuotes?.colecta?.available ? "Cotización real de Mercado Libre" : "Calculá para cotizar"}</span></div>
                      </div>
                    </button>
                    <button
                      type="button"
                      className={`publisherLogisticsCard ${pricingLogisticType === shippingCapabilities?.flex_logistic_type ? "selected" : ""}`}
                      disabled={!shippingCapabilities?.flex_available || pricingRecalculationBusy}
                      onClick={()=>shippingCapabilities?.flex_available && void selectPricingLogistics(shippingCapabilities.flex_logistic_type)}
                    >
                      <div className="publisherLogisticsCardTitle"><span className="radioDot"/><b>Flex</b>{pricingLogisticType === shippingCapabilities?.flex_logistic_type && <em>Seleccionada</em>}</div>
                      <div className="publisherLogisticsCardBody">
                        <div><strong>{logisticsQuotes?.flex?.available ? money(logisticsQuotes.flex.seller_cost) : "—"}</strong><small>Costo logístico estimado</small></div>
                        <div className="publisherLogisticsMeta"><span>Modalidad: {shippingCapabilities?.flex_logistic_type || "self_service"}</span><span>{shippingCapabilities?.flex_available ? (logisticsQuotes?.flex?.available ? "Cotización real de Mercado Libre" : "Calculá para cotizar") : "No habilitado para esta cuenta/categoría"}</span></div>
                      </div>
                    </button>
                  </div>
                  <div className="publisherLogisticsFooter">
                    <label>Quién paga el envío
                      <select disabled={!contextComplete} value={simulationPackage.freeShipping} onChange={e=>{setSimulationPackage(current=>({...current,freeShipping:e.target.value}));setPricingAnalysis(null);setLogisticsQuotes(null);}}>
                        <option value="">Elegí una opción</option>
                        <option value="false">El comprador paga</option>
                        <option value="true">Ofrecer envío gratis</option>
                      </select>
                    </label>
                    {activeCommercialAllocations.length > 1
                      ? <label>Modalidad de publicación
                        <select disabled={!contextComplete} value={pricingListingTypeId} onChange={e=>{setPricingListingTypeId(e.target.value);setPricingAnalysis(null);setLogisticsQuotes(null);}}>
                          <option value="">Elegí una modalidad</option>
                          {activeCommercialAllocations.map(option=><option key={option.listing_type_id} value={option.listing_type_id}>{option.listing_type_name}</option>)}
                        </select>
                      </label>
                      : activeCommercialAllocations.length === 1 && <div className="pricingResolvedContext compact"><span>Modalidad</span><b>{activeCommercialAllocations[0].listing_type_name}</b><small>Se toma de la configuración del lote.</small></div>}
                  </div>
                </section>

                <section className="publisherMarginSection">
                  <div className="publisherPricingSubheader">
                    <div><h3>Cálculo por Mercado Libre</h3><p>Elegí el margen deseado o personalizá el precio. Se calculan los costos automáticamente.</p></div>
                  </div>
                  <div className="publisherMarginControls">
                    <div className="publisherMarginSelector" role="group" aria-label="Margen de contribución objetivo">
                      {([
                        ["mc0", 0, "MC 0%"],
                        ["mc15", 15, "MC 15%"],
                        ["mc20", 20, "MC 20%"],
                        ["mc25", 25, "MC 25%"],
                        ["mc35", 35, "MC 35%"],
                      ] as const).map(([key, margin, label]) => <button
                        key={key}
                        type="button"
                        className={pricingScenario === key && priceVariant === "base" ? "active" : ""}
                        disabled={!pricingAnalysis || pricingRecalculationBusy}
                        onClick={()=>void chooseMarginScenario(key, margin)}
                      >{label}</button>)}
                      <button type="button" className={pricingScenario === "custom" && priceVariant === "base" ? "active" : ""} onClick={()=>setPricingScenario("custom")}>Personalizado</button>
                    </div>
                    <label className="publisherCustomPrice">Precio personalizado
                      <div className="moneyInput"><span>$</span><input disabled={!contextComplete} type="number" min="0.01" step="0.01" value={pricingScenario === "custom" && priceVariant === "base" && form.price !== "0" ? form.price : ""} onChange={e=>scheduleCustomPriceRecalculation(e.target.value)} placeholder="Ej. 24.990"/></div>
                      <small>Se recalcula automáticamente al dejar de escribir.</small>
                    </label>
                  </div>
                  <div className="publisherPricingPrimaryActions">
                    <button type="button" disabled={!contextComplete || !pricingConfigured || !Number(productCost) || busy || pricingRecalculationBusy} onClick={()=>run(()=>simulateCurrentPrice({salePrice:Number(form.price)>0?Number(form.price):null,scenario:Number(form.price)>0?"custom":undefined,variant:"base",updateBase:true}))}>{busy || pricingRecalculationBusy ? "Calculando…" : "Calcular"}</button>
                    <span>Usa la categoría, modalidad y logística cargadas en esta ficha.</span>
                  </div>
                </section>
              </div>

              <aside className="publisherPriceSummary">
                <div className="publisherPriceSummaryHeader"><h3>Precio principal</h3><p>{priceVariant === "3" ? "Variante para 3 cuotas" : priceVariant === "6" ? "Variante para 6 cuotas" : pricingScenario === "custom" ? "Precio personalizado" : `Precio según ${pricingScenario.replace("mc", "MC ")}%`}</p></div>
                <div className="publisherPrincipalPrice">{displayedPrincipalPrice > 0 ? money(displayedPrincipalPrice) : "—"}</div>
                <div className="publisherInstallmentActions">
                  <button type="button" className={priceVariant === "3" ? "active" : ""} disabled={!installmentBasePrice || pricingRecalculationBusy} onClick={()=>run(()=>calculateInstallmentVariant(3))}>
                    <span>▤ Calcular precio 3 cuotas</span><b>{installment3Price ? money(installment3Price) : "—"}</b>
                  </button>
                  <button type="button" className={priceVariant === "6" ? "active" : ""} disabled={!installmentBasePrice || pricingRecalculationBusy} onClick={()=>run(()=>calculateInstallmentVariant(6))}>
                    <span>▤ Calcular precio 6 cuotas</span><b>{installment6Price ? money(installment6Price) : "—"}</b>
                  </button>
                </div>
                <div className="publisherInstallmentPreview">
                  <div><span>3 cuotas</span><b>{installment3Price ? `${money(installment3Price / 3)} × 3` : "—"}</b><small>+{pricingProfile.installment_3_markup_pct}% sobre precio principal</small></div>
                  <div><span>6 cuotas</span><b>{installment6Price ? `${money(installment6Price / 6)} × 6` : "—"}</b><small>+{pricingProfile.installment_6_markup_pct}% sobre precio principal</small></div>
                </div>
                {selectedPricingBreakdown ? <div className="publisherPriceLedger">
                  <div><span>Costo del producto (con IVA)</span><b>{money(selectedPricingBreakdown.gross_cmv || Number(productCost))}</b></div>
                  <div><span>Comisión Mercado Libre</span><b>− {money(selectedPricingBreakdown.ml_commission_net || 0)}</b></div>
                  {Number(selectedPricingBreakdown.financing_net || 0) > 0 && <div><span>Financiación Mercado Libre</span><b>− {money(selectedPricingBreakdown.financing_net)}</b></div>}
                  <div><span>Cargo fijo por venta</span><b>− {money(selectedPricingBreakdown.fixed_fee || 0)}</b></div>
                  <div><span>Costo logístico neto</span><b>− {money(selectedPricingBreakdown.net_logistic_cost || 0)}</b></div>
                  <div><span>IIBB</span><b>− {money(selectedPricingBreakdown.iibb || 0)}</b></div>
                  <div className="publisherMarginResult"><span>Margen resultante</span><b>{Number(selectedPricingBreakdown.contribution_margin_pct || 0).toFixed(2)}%</b><strong>{money(selectedPricingBreakdown.contribution_margin || 0)}</strong></div>
                </div> : <div className="publisherPriceSummaryEmpty">Calculá el precio para ver el desglose económico.</div>}
              </aside>
            </div>

          <div className="quantityPricingBox publisherWholesalePricing">
            <div className="publisherWholesaleHeader">
              <div><h3>Precios mayoristas</h3><span className="wholesalePendingPill">ⓘ Pendiente definir operación exacta en Mercado Libre</span></div>
              <label className="checkboxLabel"><input type="checkbox" disabled={!contextComplete} checked={quantityPricingEnabled} onChange={e=>setQuantityPricingEnabled(e.target.checked)}/> Habilitar precios por cantidad</label>
            </div>
            <p className="helper blockHelper">Mercado Libre habilita PxQ B2B sólo para vendedores seleccionados. La publicación principal se conserva si ML rechaza la tabla mayorista y el job lo informa como advertencia.</p>
            {quantityPricingEnabled && <>
              <div className="quantityPriceRows">
                {quantityPrices.map((tier,index)=>{
                  const analysis = quantityPricingAnalysis?.tiers.find(
                    item => item.minPurchaseUnit === tier.min_purchase_unit
                  );
                  const manualOverride = Boolean(
                    analysis && tier.amount > 0 && Math.abs(tier.amount - analysis.amount) >= 0.01
                  );
                  return <div className="quantityPriceRow" key={index}>
                    <label>Desde<input type="number" min="2" value={tier.min_purchase_unit} onChange={e=>updateQuantityPriceTier(index,{min_purchase_unit:Number(e.target.value),amount:0})}/></label>
                    <label>Precio unitario ARS<input type="number" min="0.01" step="0.01" value={tier.amount || ""} onChange={e=>updateQuantityPriceTier(index,{amount:Number(e.target.value) || 0})} placeholder="Calculá o ingresá un precio"/></label>
                    <div className="quantityTierEconomics">
                      {analysis ? <>
                        <span className={`tierRisk ${analysis.status === "OPTIMO" ? "ok" : "bad"}`}>{analysis.status === "OPTIMO" ? `MC OBJETIVO ${analysis.targetMarginPct}%` : "SIN NUEVO ESCALÓN"}</span>
                        <small>Precio sugerido: <b>{money(analysis.amount)}</b> · MC logrado: <b>{analysis.contributionMarginPct}%</b></small>
                        <small>Minorista: <b>{money(analysis.retailPrice)}</b> · Piso MC mínimo: <b>{money(analysis.minimumPrice)}</b></small>
                        {manualOverride
                          ? <small>Precio editado manualmente. Por debajo de {money(analysis.minimumPrice)} se reduce el MC bajo el mínimo recomendado; podés guardar igualmente.</small>
                          : <small>{analysis.status === "OPTIMO" ? <>Descuento sugerido: <b>{analysis.discountPct}%</b></> : <>El margen mínimo ya fue alcanzado; no hay un escalón automático adicional sostenible.</>}</small>}
                      </> : <small>Cada escalón baja 5 puntos desde el MC objetivo, sin perforar el MC mínimo. Después del cálculo podés ajustar el precio manualmente.</small>}
                    </div>
                    <button type="button" className="tiny dangerButton" onClick={()=>removeQuantityPriceTier(index)}>Eliminar</button>
                  </div>;
                })}
              </div>
              <div className="quantityPricingActions">
                <button type="button" className="secondary" disabled={quantityPrices.length >= 5} onClick={addQuantityPriceTier}>+ Agregar escalón mayorista</button>
                <button type="button" className="secondary" disabled={!pricingConfigured || !quantityPrices.length || busy} onClick={()=>run(simulateQuantityPrices)}>Calcular precios óptimos</button>
              </div>
              <small className="helper">Máximo 5 escalones. Podés guardar la ficha y cargar imágenes sin calcular precios. Los escalones incompletos se conservan como borrador y no se envían a Mercado Libre; los precios manuales completos pueden publicarse si cumplen las reglas del marketplace. El MC es orientativo.</small>
              {!quantityPricingSnapshot().valid && <div className="optionalNotice" role="status">Precios mayoristas en borrador: podés guardar la ficha y cargar imágenes. Esta tabla todavía no se enviará a Mercado Libre.</div>}
            </>}
          </div>
          </div>
          <div style={{display: publisherStep === "technical" ? undefined : "none"}}>
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
          </div>
          {publisherStep === "prices" && <div className="publisherSaveFooter">
            <button
              disabled={!contextComplete || categoryContractLoading || busy || (Boolean(batchId) && drafts.length > 0 && (!shippingReady || !requiredAttributesComplete))}
              onClick={()=>run(batchId && drafts.length > 0 ? saveCorrectionsAndRevalidate : createProduct)}
            >
              {batchId && drafts.length > 0
                ? "Guardar correcciones y revalidar lote"
                : existingProduct ? "Guardar nueva versión" : "Guardar ficha"}
            </button>
            {(!shippingReady || !requiredAttributesComplete) && !(batchId && drafts.length > 0) && <p className="helper blockHelper" role="status">
              Podés guardar la ficha y cargar imágenes aunque falten atributos obligatorios o Mercado Libre no haya confirmado la logística. Esos pendientes deberán resolverse antes de publicar.
            </p>}
            {batchId && drafts.length > 0 && <p className="helper blockHelper">
              Si la validación detecta un dato faltante, completalo acá y guardá las correcciones. La app crea un nuevo snapshot de la ficha, conserva los borradores e imágenes y vuelve a validar el lote sin recargar la página.
            </p>}
          </div>}
        </section>

        <section className={`card ${!productComplete ? "locked" : ""}`} style={{display: publisherStep === "images" ? undefined : "none"}}>
          <div className="sectionTitle"><span>4</span> Imágenes y plan del lote</div>
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
            <label>Cantidad de publicaciones por cuenta
              <input type="number" min="1" max="100" disabled={!versionId} value={form.count}
                onChange={e=>setForm({...form,count:e.target.value})}/>
            </label>
          </div>

          {uploadedImages.length > 0 && <div className="imageManager" aria-label="Gestor de imágenes">
            <div className="imageManagerHeader">
              <div><h3>Orden de publicación</h3><p>Arrastrá las miniaturas para reordenarlas. La primera imagen es la principal; el orden se persiste y se usa en todos los borradores.</p></div>
            </div>
            <div className="imageManagerGrid">
              {uploadedImages.map((image, index) => <article
                className={`imageManagerCard ${index === 0 ? "primary" : ""}`}
                key={image.id}
                draggable={!busy}
                onDragStart={event => {
                  event.dataTransfer.setData("text/plain", image.id);
                  event.dataTransfer.effectAllowed = "move";
                }}
                onDragOver={event => {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = "move";
                }}
                onDrop={event => {
                  event.preventDefault();
                  const sourceId = event.dataTransfer.getData("text/plain");
                  run(() => reorderImageByDrop(sourceId, image.id));
                }}
              >
                <div className="imageThumbWrap">
                  <img src={`/uploads/${image.id}`} alt={image.original_name || `Imagen ${index + 1}`} className="imageThumb"/>
                  {index === 0 && <span className="primaryImageBadge">Principal</span>}
                </div>
                <div className="imageManagerMeta"><b>{index + 1}. {image.original_name}</b><small>Posición {index + 1}</small></div>
                <div className="imageManagerActions">
                  <button type="button" className="tiny secondary" disabled={busy || index === 0} onClick={()=>run(()=>moveImage(index,-1))}>←</button>
                  <button type="button" className="tiny secondary" disabled={busy || index === uploadedImages.length - 1} onClick={()=>run(()=>moveImage(index,1))}>→</button>
                  <button type="button" className="tiny dangerButton" disabled={busy} onClick={()=>run(()=>removeUploadedImage(image.id))}>Eliminar</button>
                </div>
              </article>)}
            </div>
          </div>}

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

          <button disabled={!versionId || busy || distributionInvalid || targetAccountIds.length === 0} onClick={()=>run(generateDrafts)}>Generar borradores multicuenta con IA</button>
        </section>

        {drafts.length > 0 && <section className="card wide" style={{display: publisherStep === "review" ? undefined : "none"}}>
          <div className="toolbar">
            <div>
              <div className="sectionTitle"><span>5</span> Revisión de borradores</div>
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
              <thead><tr><th>Publicar</th><th>Cuenta</th><th>#</th><th>Título</th><th>Chars</th><th>Modalidad</th><th>Score</th><th>Imgs</th><th>Estado</th><th>Acciones</th></tr></thead>
              <tbody>
                {drafts.map(d=><tr key={d.id}>
                  <td><input className="draftCheckbox" type="checkbox" checked={selectedDraftIds.includes(d.id)} disabled={d.status !== "APPROVED" || Boolean(job && !terminalJob)} onChange={()=>toggleDraftSelection(d.id)}/></td>
                  <td><span className="accountDraftPill">{d.account_nickname || d.account_id || "—"}</span></td>
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

        {publisherStep === "review" && drafts.length === 0 && <div className="card wizardEmpty">Generá los borradores en Imágenes y lote para revisarlos acá.</div>}
        {publisherStep === "execution" && !job && <div className="card wizardEmpty">Seleccioná y publicá borradores aprobados desde Revisión para ver la ejecución.</div>}
        {job && <section className="card" style={{display: publisherStep === "execution" ? undefined : "none"}}>
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
        <div className="wizardNavigation" role="navigation" aria-label="Navegación de la ficha">
          <div className="wizardNavigationHeading">
            <strong>{({category: "Producto y categoría", technical: "Ficha técnica", prices: "Precios", images: "Imágenes", review: "Revisión", execution: "Publicación"} as const)[publisherStep]}</strong>
            <span>Podés navegar libremente. Los campos conservan su contenido mientras cambiás de etapa.</span>
          </div>
          <div className="wizardNavigationActions">
            <button type="button" className="secondary" disabled={publisherStep === "category"} onClick={() => setPublisherStep((current) => {
              const steps = ["category", "technical", "prices", "images", "review", "execution"] as const;
              return steps[Math.max(0, steps.indexOf(current) - 1)];
            })}>← Anterior</button>
            <button type="button" disabled={publisherStep === "execution"} onClick={() => setPublisherStep((current) => {
              const steps = ["category", "technical", "prices", "images", "review", "execution"] as const;
              return steps[Math.min(steps.length - 1, steps.indexOf(current) + 1)];
            })}>Siguiente →</button>
          </div>
        </div>

      </main>

      {validationActive && <div className="modalBackdrop progressBackdrop">
        <div className="modal progressModal validationProgressModal">
          <div className="spinner"/>
          <h2>Validando con Mercado Libre</h2>
          <p>Estamos comprobando atributos, logística, imágenes y contrato de publicación con la API real de Mercado Libre.</p>
          <div className="progressSteps">
            <span>Preparando payload de validación</span>
            <span>Consultando reglas de la cuenta y categoría</span>
            <span>Consolidando observaciones y errores</span>
          </div>
          <small>La ficha permanece guardada. La validación no publica ni modifica una publicación existente.</small>
        </div>
      </div>}

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


type Operator = {id: string; username: string; display_name: string; role: "ADMIN" | "SUPERVISOR" | "OPERATOR"};

function AuthenticatedPublisher() {
  const [operator, setOperator] = useState<Operator | null>(null);
  const [manageUsers, setManageUsers] = useState(false);
  const [hadSession, setHadSession] = useState(false);
  const [loading, setLoading] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  useEffect(() => {
    let cancelled = false;
    api<Operator>("/api/operator-auth/me")
      .then(user => {if (!cancelled) {setOperator(user); setHadSession(true);}})
      .catch(() => {if (!cancelled) setOperator(null);})
      .finally(() => {if (!cancelled) setLoading(false);});
    return () => {cancelled = true;};
  }, []);
  useEffect(() => {
    const expired = () => {setManageUsers(false); setOperator(null); setError("La sesión caducó. Ingresá nuevamente para continuar sin perder los datos abiertos.");};
    window.addEventListener("publisher-session-expired", expired);
    return () => window.removeEventListener("publisher-session-expired", expired);
  }, []);
  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const user = await api<Operator>("/api/operator-auth/login", {
        method: "POST", body: JSON.stringify({username, password}),
      });
      setPassword("");
      setOperator(user);
      setHadSession(true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "No se pudo iniciar sesión");
    } finally {
      setSubmitting(false);
    }
  }
  async function logout() {
    try {
      await api<void>("/api/operator-auth/logout", {method: "POST"});
      setOperator(null);
      setManageUsers(false);
      setPassword("");
      window.location.reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "No se pudo cerrar sesión");
    }
  }
  if (loading) return <div className="loginViewport"><section className="loginCard"><p>Verificando sesión…</p></section></div>;
  const loginScreen = <div className="loginViewport"><form className="loginCard" onSubmit={login}>
    <h1>Publicador ML</h1><p>Accedé con tu usuario interno.</p>
    <label>Usuario<input required autoComplete="username" value={username} onChange={e => setUsername(e.target.value)}/></label>
    <label>Contraseña<input required autoComplete="current-password" type="password" value={password} onChange={e => setPassword(e.target.value)}/></label>
    {error && <p role="alert" className="loginError">{error}</p>}
    <button disabled={submitting} type="submit">{submitting ? "Ingresando…" : "Ingresar"}</button>
  </form></div>;
  if (!operator && !hadSession) return loginScreen;
  return <>{!operator && loginScreen}<div style={{display: operator ? undefined : "none"}}>{operator && <div className="operatorSessionBar"><span>{operator.display_name} · {operator.role}</span>{operator.role !== "OPERATOR" && <button className="secondary tiny" type="button" onClick={() => setManageUsers(value => !value)}>{manageUsers ? "Volver al Publicador" : "Usuarios y permisos"}</button>}<button className="secondary tiny" type="button" onClick={logout}>Cerrar sesión</button></div>}{operator && manageUsers && operator.role !== "OPERATOR" && <OperatorUsers actor={operator} onBack={() => setManageUsers(false)}/>}<div style={{display: manageUsers ? "none" : undefined}}><App operatorRole={operator?.role ?? "OPERATOR"} /></div></div></>;
}

createRoot(document.getElementById("root")!).render(<AuthenticatedPublisher />);

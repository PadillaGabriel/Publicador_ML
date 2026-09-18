export type CostKind =
  | "FIXED_MONTHLY"
  | "FIXED_PER_UNIT"
  | "FIXED_PER_ORDER"
  | "PERCENTAGE_OF_PRICE"
  | "PERCENTAGE_OF_COST";

export type CostBasis =
  | "GROSS_SALE"
  | "NET_SALE_EX_VAT"
  | "TAXABLE_REVENUE"
  | "PRODUCT_COST"
  | "FIXED_PER_UNIT"
  | "FIXED_PER_ORDER";

export type PricingCostComponent = {
  name: string;
  kind: CostKind;
  value: number;
  basis: CostBasis;
  active: boolean;
};

export type PricingProfile = {
  name: string;
  channel: string;
  currency_id: string;
  target_margin_pct: number;
  minimum_margin_pct: number;
  vat_rate_pct: number;
  iibb_rate_pct: number;
  ads_rate_pct: number;
  refund_rate_pct: number;
  monthly_units_projection: number | null;
  rounding_step: number;
  components: PricingCostComponent[];
};

export type PricingBreakdown = {
  grossPrice: number;
  netPrice: number;
  grossCmv: number;
  netCmv: number;
  mlCommissionNet: number;
  financingNet: number;
  fixedFee: number;
  mlFixedFeeNet: number;
  shippingCost: number;
  shippingSubsidy: number;
  buyerShippingAmount: number;
  netLogisticCost: number;
  iibb: number;
  adsExpected: number;
  refundsExpected: number;
  additionalUnitCostNet: number;
  contributionMargin: number;
  contributionMarginPct: number;
};

export type PricingTarget = {
  targetMarginPct: number;
  grossPrice: number;
  achievedMarginPct: number;
  probes: number;
};

export type PricingAudit = {
  marketplaceContext: Record<string, string | number>;
  targetMarginPct: number;
  targetMarginSource: string;
  minimumMarginPct: number;
  recommendedTargetMarginPct: number;
  roundingStep: number;
};

export type PricingCalculation = {
  scenario: "NEW_PRODUCT" | "EXISTING_LISTING";
  scenarioUnits: number;
  analyzed: PricingBreakdown;
  mc0: PricingTarget;
  mc15: PricingTarget;
  mc20: PricingTarget;
  minimum: PricingTarget;
  target: PricingTarget;
  custom: PricingTarget | null;
  recommendedPrice: number;
  breakdowns: Record<string, PricingBreakdown>;
  audit: PricingAudit;
};


export type QuantityTierAnalysis = {
  minPurchaseUnit: number;
  amount: number;
  targetMarginPct: number;
  contributionMargin: number;
  contributionMarginPct: number;
  status: "OPTIMO" | "SIN_VENTAJA";
  minimumPrice: number;
  retailPrice: number;
  discountPct: number;
};

export type QuantityPricingAnalysis = {
  minimum: PricingTarget;
  target: PricingTarget;
  retailPrice: number;
  tiers: QuantityTierAnalysis[];
};

export type PricingCalculatorPrefill = {
  requestId: number;
  accountId: string;
  categoryId: string;
  categoryLabel: string;
  listingTypeId: string;
  grossCmv: string;
  salePrice: string;
  dimensions: string;
  weight: string;
  logisticType: string;
  shippingMode: string;
  freeShipping: string;
};

export type ShippingCapabilities = {
  mode: "me2";
  base_logistic_type: string;
  flex_available: boolean;
  flex_logistic_type: "self_service";
};

type ApiEconomicResult = {
  gross_price: number; net_price: number; gross_cmv: number; net_cmv: number;
  ml_commission_net: number; financing_net: number; fixed_fee: number; ml_fixed_fee_net: number; shipping_cost: number;
  shipping_subsidy: number; buyer_shipping_amount: number; net_logistic_cost: number;
  iibb: number; ads_expected: number; refunds_expected: number; additional_unit_cost_net: number;
  contribution_margin: number; contribution_margin_pct: number;
};

type ApiTarget = {
  target_margin_pct: number; gross_price: number; achieved_margin_pct: number; probes: number;
};

type ApiAudit = {
  marketplace_context: Record<string, string | number>;
  target_margin_pct: number;
  target_margin_source: string;
  minimum_margin_pct: number;
  recommended_target_margin_pct: number;
  rounding_step: number;
};

export type PricingCalculatorApiResponse = {
  scenario: PricingCalculation["scenario"]; scenario_units: number; analyzed: ApiEconomicResult;
  mc0: ApiTarget; mc15: ApiTarget; mc20: ApiTarget; minimum: ApiTarget; target: ApiTarget;
  custom: ApiTarget | null; recommended_price: number; breakdowns: Record<string, ApiEconomicResult>; audit: ApiAudit;
};

function numberValue(value: number): number { return Number(value); }

function toBreakdown(source: ApiEconomicResult): PricingBreakdown {
  return {
    grossPrice: numberValue(source.gross_price), netPrice: numberValue(source.net_price), grossCmv: numberValue(source.gross_cmv), netCmv: numberValue(source.net_cmv),
    mlCommissionNet: numberValue(source.ml_commission_net), financingNet: numberValue(source.financing_net), fixedFee: numberValue(source.fixed_fee), mlFixedFeeNet: numberValue(source.ml_fixed_fee_net),
    shippingCost: numberValue(source.shipping_cost), shippingSubsidy: numberValue(source.shipping_subsidy), buyerShippingAmount: numberValue(source.buyer_shipping_amount),
    netLogisticCost: numberValue(source.net_logistic_cost), iibb: numberValue(source.iibb), adsExpected: numberValue(source.ads_expected),
    refundsExpected: numberValue(source.refunds_expected), additionalUnitCostNet: numberValue(source.additional_unit_cost_net),
    contributionMargin: numberValue(source.contribution_margin), contributionMarginPct: numberValue(source.contribution_margin_pct),
  };
}

function toTarget(target: ApiTarget): PricingTarget {
  return { targetMarginPct: numberValue(target.target_margin_pct), grossPrice: numberValue(target.gross_price), achievedMarginPct: numberValue(target.achieved_margin_pct), probes: target.probes };
}


export type QuantityPricingApiResponse = {
  minimum: ApiTarget;
  target: ApiTarget;
  retail_price: number;
  tiers: Array<{
    min_purchase_unit: number;
    amount: number;
    target_margin_pct: number;
    analyzed: ApiEconomicResult;
    status: "OPTIMO" | "SIN_VENTAJA";
    minimum_price: number;
    retail_price: number;
    discount_pct: number;
  }>;
};

export function normalizeQuantityPricing(response: QuantityPricingApiResponse): QuantityPricingAnalysis {
  return {
    minimum: toTarget(response.minimum),
    target: toTarget(response.target),
    retailPrice: numberValue(response.retail_price),
    tiers: response.tiers.map(tier => ({
      minPurchaseUnit: tier.min_purchase_unit,
      amount: numberValue(tier.amount),
      targetMarginPct: numberValue(tier.target_margin_pct),
      contributionMargin: numberValue(tier.analyzed.contribution_margin),
      contributionMarginPct: numberValue(tier.analyzed.contribution_margin_pct),
      status: tier.status,
      minimumPrice: numberValue(tier.minimum_price),
      retailPrice: numberValue(tier.retail_price),
      discountPct: numberValue(tier.discount_pct),
    })),
  };
}

export function normalizeCalculation(response: PricingCalculatorApiResponse): PricingCalculation {
  const source = response.analyzed;
  return {
    scenario: response.scenario,
    scenarioUnits: response.scenario_units,
    analyzed: toBreakdown(source),
    mc0: toTarget(response.mc0), mc15: toTarget(response.mc15), mc20: toTarget(response.mc20),
    minimum: toTarget(response.minimum), target: toTarget(response.target),
    custom: response.custom ? toTarget(response.custom) : null, recommendedPrice: numberValue(response.recommended_price),
    breakdowns: Object.fromEntries(Object.entries(response.breakdowns).map(([key, value]) => [key, toBreakdown(value)])),
    audit: {
      marketplaceContext: response.audit.marketplace_context,
      targetMarginPct: numberValue(response.audit.target_margin_pct),
      targetMarginSource: response.audit.target_margin_source,
      minimumMarginPct: numberValue(response.audit.minimum_margin_pct),
      recommendedTargetMarginPct: numberValue(response.audit.recommended_target_margin_pct),
      roundingStep: numberValue(response.audit.rounding_step),
    },
  };
}

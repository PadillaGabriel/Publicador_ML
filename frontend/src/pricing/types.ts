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
  mlFixedFeeNet: number;
  shippingCost: number;
  shippingSubsidy: number;
  buyerShippingAmount: number;
  netLogisticCost: number;
  iibb: number;
  adsExpected: number;
  refundsExpected: number;
  contributionMargin: number;
  contributionMarginPct: number;
};

export type PricingTarget = {
  targetMarginPct: number;
  grossPrice: number;
  achievedMarginPct: number;
  probes: number;
};

export type PricingCalculation = {
  scenario: "NEW_PRODUCT" | "EXISTING_LISTING";
  scenarioUnits: number;
  analyzed: PricingBreakdown;
  mc0: PricingTarget;
  mc15: PricingTarget;
  mc20: PricingTarget;
  custom: PricingTarget | null;
  recommendedPrice: number;
};

type ApiEconomicResult = {
  gross_price: number; net_price: number; gross_cmv: number; net_cmv: number;
  ml_commission_net: number; ml_fixed_fee_net: number; shipping_cost: number;
  shipping_subsidy: number; buyer_shipping_amount: number; net_logistic_cost: number;
  iibb: number; ads_expected: number; refunds_expected: number;
  contribution_margin: number; contribution_margin_pct: number;
};

type ApiTarget = {
  target_margin_pct: number; gross_price: number; achieved_margin_pct: number; probes: number;
};

export type PricingCalculatorApiResponse = {
  scenario: PricingCalculation["scenario"]; scenario_units: number; analyzed: ApiEconomicResult;
  mc0: ApiTarget; mc15: ApiTarget; mc20: ApiTarget; custom: ApiTarget | null;
  recommended_price: number;
};

function numberValue(value: number): number { return Number(value); }

function toTarget(target: ApiTarget): PricingTarget {
  return { targetMarginPct: numberValue(target.target_margin_pct), grossPrice: numberValue(target.gross_price), achievedMarginPct: numberValue(target.achieved_margin_pct), probes: target.probes };
}

export function normalizeCalculation(response: PricingCalculatorApiResponse): PricingCalculation {
  const source = response.analyzed;
  return {
    scenario: response.scenario,
    scenarioUnits: response.scenario_units,
    analyzed: {
      grossPrice: numberValue(source.gross_price), netPrice: numberValue(source.net_price), grossCmv: numberValue(source.gross_cmv), netCmv: numberValue(source.net_cmv),
      mlCommissionNet: numberValue(source.ml_commission_net), mlFixedFeeNet: numberValue(source.ml_fixed_fee_net), shippingCost: numberValue(source.shipping_cost),
      shippingSubsidy: numberValue(source.shipping_subsidy), buyerShippingAmount: numberValue(source.buyer_shipping_amount), netLogisticCost: numberValue(source.net_logistic_cost),
      iibb: numberValue(source.iibb), adsExpected: numberValue(source.ads_expected), refundsExpected: numberValue(source.refunds_expected),
      contributionMargin: numberValue(source.contribution_margin), contributionMarginPct: numberValue(source.contribution_margin_pct),
    },
    mc0: toTarget(response.mc0), mc15: toTarget(response.mc15), mc20: toTarget(response.mc20),
    custom: response.custom ? toTarget(response.custom) : null, recommendedPrice: numberValue(response.recommended_price),
  };
}

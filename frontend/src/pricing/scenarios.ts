import type { PricingBreakdown, PricingCalculation, PricingTarget } from "./types";

export type PricingScenarioOption = {
  key: string;
  label: string;
  target: PricingTarget;
  breakdown: PricingBreakdown;
  recommended: boolean;
};

function sameMargin(left: number, right: number) {
  return Math.abs(left - right) < 0.001;
}

function option(
  calculation: PricingCalculation,
  key: string,
  label: string,
  target: PricingTarget,
): PricingScenarioOption | null {
  const breakdown = calculation.breakdowns[key];
  if (!breakdown) return null;
  return {
    key,
    label,
    target,
    breakdown,
    recommended: sameMargin(target.targetMarginPct, calculation.audit.recommendedTargetMarginPct),
  };
}

export function pricingScenarioOptions(calculation: PricingCalculation): PricingScenarioOption[] {
  const options = [
    option(calculation, "mc0", "MC 0%", calculation.mc0),
    option(calculation, "mc15", "MC 15%", calculation.mc15),
    option(calculation, "mc20", "MC 20%", calculation.mc20),
  ].filter((value): value is PricingScenarioOption => value !== null);

  if (calculation.custom && !options.some(item => sameMargin(item.target.targetMarginPct, calculation.custom!.targetMarginPct))) {
    const custom = option(calculation, "custom", `MC ${calculation.custom.targetMarginPct}%`, calculation.custom);
    if (custom) options.push(custom);
  }

  const recommendedMargin = calculation.audit.recommendedTargetMarginPct;
  if (!options.some(item => sameMargin(item.target.targetMarginPct, recommendedMargin))) {
    const candidates: Array<[string, PricingTarget]> = [
      ["target", calculation.target],
      ["minimum", calculation.minimum],
    ];
    for (const [key, target] of candidates) {
      if (!sameMargin(target.targetMarginPct, recommendedMargin)) continue;
      const recommended = option(calculation, key, `MC ${recommendedMargin}%`, target);
      if (recommended) options.push(recommended);
      break;
    }
  }
  return options;
}

export function recommendedScenario(calculation: PricingCalculation): PricingScenarioOption | null {
  return pricingScenarioOptions(calculation).find(item => item.recommended) ?? null;
}

export type TitleRecommendationConfidence =
  | "TREND_SUPPORTED"
  | "FACTUAL_FALLBACK";

export type TitleRecommendationResponse = {
  recommended_title: string;
  alternatives: string[];
  confidence: TitleRecommendationConfidence;
  matched_trends: string[];
  fallback_used: boolean;
};

export type TitleAssistantProps = {
  accountId: string;
  categoryId: string;
  productText: string;
  attributes: Record<string, unknown>;
  maxLength: number | null;
  onUseTitle: (title: string) => void;
};

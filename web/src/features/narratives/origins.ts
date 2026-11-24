import type { LineageItem } from "@/lib/api/results";

export const ORIGIN_LABEL: Record<LineageItem["origin"], string> = {
  event: "Event",
  mutation: "Mutation",
  invention: "Invention",
  price_news: "Price news",
};

// Presentation groups for already-audited supplier claims. These groups are
// not suitability scores, package approvals, or model predictions.
export function groupSourceOptions(leads = []) {
  const exactConditions = [];
  const relatedFoodName = [];
  const outsidePublishedUse = [];
  for (const lead of leads) {
    if (lead.food_name_match === "exact_name"
        && lead.application_status === "published_food_quantity_temperature_match_unverified"
        && lead.reason_codes.length === 0) {
      exactConditions.push(lead);
    } else if (lead.food_name_match === "raw_name_variant_unreviewed"
        && lead.reason_codes.length === 1
        && lead.reason_codes[0] === "food_identity_requires_review") {
      relatedFoodName.push(lead);
    } else {
      outsidePublishedUse.push(lead);
    }
  }
  return { exactConditions, relatedFoodName, outsidePublishedUse };
}

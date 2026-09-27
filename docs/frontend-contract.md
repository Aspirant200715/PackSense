# Frontend decision JSON contract

The frontend can be designed against `frontend-decision-v1` while the material
model and package-release gates remain unfulfilled. This is a versioned
projection of the existing batch report, **not** an HTTP API or a new
prediction engine. It does not expose the source workbook paths or raw food
rows. Generate it from a completed batch audit:

```powershell
python -m packsense.frontend_contract batch-report.json --output new-frontend-decisions.json
```

The output path must be new. The projector refuses a batch that claims package
feasibility or shelf-life prediction, a contradictory row status, an invalid
preliminary preference, or an unsupported batch version. It does not modify
the batch, food or material data, shortlist, or model state.

## Top-level fields

- `contract_version`: currently `frontend-decision-v1`; clients should reject
  unknown major versions rather than guessing at field meanings.
- `source_batch_version`: the audited backend batch contract.
- `model`: material-suitability task, deployment status, prediction
  availability, and model version. In this version it is `not_deployed`,
  `false`, and `null` because no validated artifact exists.
- `recommendation_release_status`: `withheld` in this version.
- `trace`: source hashes for the scenario batch, reference masters, and any
  supplied route, food-assessment, structure-review, transfer, or public-
  candidate registers. Absent optional inputs have `null` hashes.
- `total_rows` and `rows`: one decision record for every source scenario row.

## Per-row states

`status` has exactly three values:

- `exception`: input validation or food-reference matching failed. Display
  `input_issues`; do not show a package result.
- `not_ready`: the input was interpretable, but food needs or package evidence
  are incomplete. Display `requirement_gaps`, `screening_reason_codes`, and
  `warnings` separately. Missing evidence is not a negative suitability label.
- `preliminary_shortlist`: one or more reviewed structures passed the current
  narrow non-respiring protection screen. Display `screened_candidates` with
  their own `eligible_for_shortlist`, `excluded`, or `unresolved` statuses.
  `preliminary_preferred_structure_id` is a protection-only comparison, **not**
  a certified or released package recommendation.

Every row also carries `source_row_number`, `record_id`, `food_reference_id`
where matched, the requested shelf-life target, distinct temperature exposure
segments, and the screened candidate's pack format, layer gauges, service-
temperature bounds, protection rank, and reason codes when available.

In **all** three states of this contract, `recommended_structure_id`,
`material_prediction`, and `predicted_shelf_life_days` are `null`, and
`package_feasible` is `false`. A frontend must not relabel a supplier lead or
preliminary preference as an AI prediction. A later model-release contract
will need a new version and independent validation before any of these fields
can be populated.

The backend still needs genuine, independently reviewed food/complete-package
outcomes with both decisions, source/rights approval, and a frozen group split
before fitting or releasing a material predictor. The 5,000-food and 81-grade
workbooks remain reference features, not package-choice labels. See
[material-suitability intake](material-suitability.md) and
[preliminary recommendation](basic-recommendation.md).

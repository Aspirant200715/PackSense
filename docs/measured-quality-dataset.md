# Public measured quality dataset

The supplied public dataset is suitable for a narrowly scoped experiment that predicts measured quality indicators for smoked catfish and rabbit under the reported study conditions. It is **not** a shelf-life label table and cannot train or validate the architecture's final shelf-life prediction or packaging recommendation.

## Source and files

The data are from Ansong, Amponsah, Addo, and Nkrumah, *Effects of packaging system and storage temperature on the physicochemical and microbiological stability of smoked catfish and rabbit*, Mendeley Data, version 1, DOI [10.17632/tvsw53j89z.1](https://data.mendeley.com/datasets/tvsw53j89z/1). The repository lists the dataset under CC BY 4.0. Keep that attribution with any copy or derived report.

The study compares two food categories, three packaging systems, two storage categories, and assessment days 30, 60, and 90. Its package-level table has two package observations per food/package/storage/day cell: 72 experimental units in total. It records water activity, peroxide value, pH, mesophilic bacteria, coliforms, yeast, and mould.

The provided files have different roles:

- `packsense_public_measured_quality_packages_72.csv` is the package-level table for days 30, 60, and 90. Use these 72 rows as the experimental units for a quality-response experiment.
- `packsense_public_measured_quality_raw_672.csv` is the long-format source and lineage table. It also contains 168 day-0 measurements described by the source as shared starting baselines. Those values are not additional package trials and must not be added to the 72 post-baseline units.

The wide file records the long file's SHA-256 and source CSV line numbers. `packsense.quality_observations` verifies that lineage and all 504 post-baseline indicator values before the data are used. Keep the original files unchanged. Do not commit them to the application repository.

## Safe use in PackSense

The code keeps these observations separate from `TrialOutcome`. An assessment day is when a measured quality sample was taken; it is not the day a failure occurred. The dataset does not record a declared failure criterion, a failure event, or right-censoring. It therefore cannot be converted into observed shelf-life days, even if an indicator changes over time.

The storage field is categorical in the supplied records. The source describes ambient storage as approximately 25–30 °C and refrigeration as 4–5 °C, but these are not exact row-level temperature measurements. Do not replace the categories with midpoint temperatures. The table also lacks transport exposures, relative humidity, package geometry, gauge, and a catalogue join to complete structures. The names Vacuum, LDPE, and Paper are reported packaging systems, not enough to assert structure-level OTR, WVTR, seal, or mechanical properties.

An exploratory model may predict one of the seven measured quality indicators at a sampled day, using only observed food, package-system, storage-category, and assessment-day fields. It must keep all records from a food/package/storage treatment group in one split partition. With only one study/source, a grouped holdout can test limited within-study treatment generalization, but it cannot establish performance on a new study, food, package grade, or commercial route. Any such run is research-only and must not drive final package selection or shelf-life claims.

The source's analysis workflow applies `log10(PV + 1)` to peroxide value and log-transforms microbial counts after assigning stated detection limits to non-detects: 25 CFU/g for bacterial counts and 5 CFU/g for yeast and mould. Preserve source values, including zeros, in the raw tables. Apply those transformations only in a clearly documented analysis step; do not overwrite the measurements or describe a non-detect as an observed zero count. Water activity and pH remain on their recorded scales.

The source also states that processing-run identifiers were not retained. Catfish-versus-rabbit is an observed product-category contrast, not a replicated species effect, and between-run variation cannot be estimated. The source explicitly cautions that the study is not a commercial shelf-life or food-safety validation dataset.

## Audit

Run the source-specific audit with both unchanged files:

```powershell
py -3.11 -m packsense.quality_observations `
  path/to/packsense_public_measured_quality_raw_672.csv `
  path/to/packsense_public_measured_quality_packages_72.csv `
  --report outputs/measured-quality-audit.json
```

The audit passes only when the two schemas, expected study design, file hash, all 504 cross-file measurements, and all source line references agree. A passing audit confirms structural and lineage consistency. It does not authorize shelf-life training, establish food safety, or make the package systems complete catalogue structures.

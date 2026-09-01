# TRAPEZIUM CSV Validation Design

## Goal

Preserve the vendor CSV byte-for-byte while allowing every UTM validation path to understand the TRAPEZIUM export format and expose canonical time, force, and displacement roles.

## Input contract

- Continue accepting canonical UTF-8 CSV files with `time_s`, `displacement_mm`, and `force_N` headers.
- Accept TRAPEZIUM CSV files encoded as UTF-8, UTF-8 with BOM, or CP949.
- Recognize the TRAPEZIUM title row, header row, and unit row.
- Map `Time/sec`, `Force/N`, and `스트로크/mm` to `time_s`, `force_N`, and `displacement_mm`.
- Preserve other vendor columns, including `Height/mm`, as source metadata.

## Output contract

The probe reports the source format, encoding, canonical columns, source columns, units, row count, SHA-256, and signal-quality checks. It must not rewrite the raw CSV. Canonical and TRAPEZIUM inputs share the same failure codes for missing columns, invalid numeric data, non-monotonic time, absent displacement signal, and absent force signal.

## Runtime integration

Linux components use one parser in `utils/utm_csv.py`. The standalone Windows worker carries the equivalent dependency-free implementation, and parity tests compare both results. `Validate Raw Data CSV` receives the exact `raw_csv_path` produced by the Save block instead of using the retired `C:/ATR/utm_exports` pattern.

## Skill lifecycle

Publish a new `utm_validate_raw_data` version, deploy and enable it, rebind the UTM flow, then disable and delete the prior deployed version. The live test uses the CSV created by the preceding Save test and performs no UTM motion or GUI click.


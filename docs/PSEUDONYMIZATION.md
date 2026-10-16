# Pseudonymization and Masking (Step 10)

## What it is — and is not

`privacy/pseudonymization.py` turns an identifier into a keyed, deterministic token:

```
pz_<key id>_<26 base32 chars of HMAC-SHA-256(key, "tdm-pseudonym-v1" ∥ namespace ∥ canonical(value))>
```

* **Pseudonymization, not anonymization.** Masked rows can still single out a person
  through the remaining columns (age + ZIP + diagnosis). Step 13 (privacy validation)
  is what measures that risk.
* **Not encryption.** Tokens cannot be reversed. If re-identification is ever required,
  keep a mapping table in a separately permissioned vault — it is deliberately not built here.
* **Keyed, not a plain hash.** SSNs, MRNs and account numbers are low-entropy; anyone could
  hash every possible SSN. Without the key, guesses cannot be tested.

## Threat model

| Adversary | Has | Protection |
|---|---|---|
| Consumer of a masked dataset | Masked CSV | Cannot recompute tokens without the key; identifier columns never contain raw values. |
| Consumer comparing two datasets | Two masked CSVs | Same namespace → same token **by design** (joins work). Different namespaces never link. |
| Someone with DB dump / browser bundle / logs | Metadata store, frontend build, logs | Key is never stored, logged, returned or bundled. Responses expose only the key **id**. |
| Insider with the key | Key + masked data | Can confirm guesses ("is token X SSN Y?"). Restrict key access to the masking service. |
| API user | Steward role | No endpoint pseudonymizes arbitrary input (that would be a guessing oracle). Masking only reads registered/sample sources and is steward+ and Step 9 gated. |

## Canonicalization

| Input | Treatment |
|---|---|
| `None`, `""`, whitespace | stays null (never one shared token) |
| strings | Unicode NFKC, trim, collapse internal whitespace; **case preserved** |
| `42`, `42.0`, `"42"` | same identifier; `"042"` is different (leading zeros kept) |
| tuples/lists | composite id, parts length-prefixed; any null part → null |
| bytes | UTF-8 decoded, else rejected |
| bool, NaN/inf, dicts | rejected |

## Namespaces used by masking

| Column kind | Namespace | Effect |
|---|---|---|
| Join keys (relationship graph, or `id` / `*_id`) | `key.<root parent table>.<column>` (graph) or `key.<column>` | Parent key and all child FKs share tokens → joins survive. |
| Direct identifiers | `id.<type>` e.g. `id.ssn`, `id.email` | Same SSN masks identically everywhere. |

Discovering relationships later (Data Relationship Validation tab) can change a key's namespace
from `key.patient_id` to `key.patients.patient_id`, so re-mask related tables together after
the graph changes.

## Keys and rotation

* `TDM_PSEUDONYM_KEYS="k1:<base64>,k2:<base64>"` (≥ 32 bytes each), `TDM_PSEUDONYM_ACTIVE_KEY_ID=k2`.
* Inject from a secret manager. Never commit; `.env` is git-ignored.
* Development auth mode without keys uses an ephemeral key (warning logged; tokens change on restart).
  Any other mode refuses to mask (HTTP 503).
* **Rotation:** add the new key, make it active, keep the old one loaded. New datasets use the new
  key id; `Pseudonymizer.matches()` verifies tokens from any loaded key and `rotation_pairs()` yields
  old→new pairs when backfilling from source. Tokens cannot be re-keyed without the raw value, so a
  backfill re-masks from the source. Remove the old key once no retained dataset uses it
  (the key id is embedded in every token, so this is checkable).

## Not yet covered

* Activity/audit logs still record usernames and table names in clear (they are actors and metadata,
  not data-subject identifiers). Revisit if usernames become personal data under your policy.
* Date shifting and format-preserving tokens are not implemented; substitution covers dates/names.

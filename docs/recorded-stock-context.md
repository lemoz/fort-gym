# Recorded inventory context

The displayed-key campaign response adds `stock_context` for its final checkpoint.
It uses the food inventory already retained in the audited result and binds the
breakdown to that save's digest and decision count. Raw measurements, timelines,
conditions, histories and historical endpoints remain unchanged.

Food counts include trader-flagged items. The page shows raw units, trader-flagged
units and their difference. That difference is not a claim of fortress ownership,
accessibility, nutrition or sustainable production. Missing or incomplete scans
keep the breakdown unknown. The frozen drink measurement does not record trader
flags, so its trader share remains unknown, not zero.

This breakdown describes only the latest saved endpoint. Earlier decision rows
retain their original raw totals; they do not inherit the final save's trader
share. Stock changes must not be credited as production. The additional context
is evaluator/reporting metadata, not advice sent to the playing model.

This change registers no new native result. The existing recorded campaign still
contains 96 decisions. Synthetic fixtures are tests only. The established
FastAPI app, dependencies and served local-preview source are preserved; no
browser QA, main merge, Site registration or public deployment is included.

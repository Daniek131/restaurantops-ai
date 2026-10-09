# Interview guide

Start with: a sale identifies recipes, each recipe identifies quantities of ingredients, and one transaction updates stock while keeping a history of usage and cost.

| Question | Code that prompts it | What to understand |
| --- | --- | --- |
| 1. Why separate recipes from ingredients? | `models.py`, `RecipeIngredient` | The many-to-many table stores quantity per portion; ingredient units are the common scale. |
| 2. What happens if the second ingredient is out of stock? | `services.py`, `record_sale`; rollback test | All updates and the sale share one transaction, so a later failure undoes earlier writes. |
| 3. What prevents two workers from overselling? | Conditional `UPDATE` in `record_sale` | Check stock in the update predicate rather than trusting an earlier read. PostgreSQL concurrency still needs an integration test. |
| 4. Why hash the payload as well as storing a unique ID? | `payload_hash` | A repeated ID can be an identical retry or a conflicting event. Explain canonical line ordering and timestamp normalization. |
| 5. Why save the unit cost in the movement? | `Movement`, `cost_summary` | Joining today's ingredient prices would change old COGS; snapshots preserve the price used when processing. |
| 6. How do you avoid double counting in report joins? | `analytics.py`, `sql/reports.sql` | Revenue and cost use separate aggregates; joining sale lines directly to movements could multiply rows. |
| 7. What is the forecast and how is it evaluated? | `daily_usage`, `forecast`, `evaluate_forecast` | Complete calendar days, missing-day assumption, trailing mean, walk-forward split, MAE, and a naive comparison. |
| 8. What does Celery add? | `tasks.py`, `compose.yaml` | Broker delivery, worker execution, scheduler publishing, one scheduler, and snapshot uniqueness. Eager tests bypass transport. |
| 9. Could the model change inventory? | `assistant.py` | Three report functions, server-side allowlist, validated arguments, bounded calls, and no SQL or write tool. Text answers can still be wrong. |
| 10. What is missing for a real restaurant? | README limits, status table | POS ingestion, units/yields, refund semantics, authorization, migrations, real-data validation, and deployment operations. |

## Walk through a sale by hand

For two flatbreads, multiply the flour requirement `0.25 × 2 = 0.50 kg` and cheese requirement `0.10 × 2 = 0.20 kg`. At $2/kg flour and $8/kg cheese, the standard ingredient cost is `$1.00 + $1.60 = $2.60`. At $12 each, revenue is $24. Explain the difference between gross profit and net profit; payroll, rent, waste, and tax are not in this calculation.

Read `record_sale` alongside its tests. Explain each query, the unique-key flush, the update condition, why quantities are grouped across recipes, and why the caller owns the transaction. Then reproduce the shortage test and identify exactly which database rows survive.

## Parts to study before presenting

SQLAlchemy sessions, conditional updates with `RETURNING`, Decimal precision, Pandas reindexing, Celery Beat, and the Responses tool loop are the least elementary sections. They are included for a working purpose, not as decorative technologies. If you cannot explain one, describe it as a component you are reviewing and practicing rather than claiming independent mastery.

The async transport and model calls have not been demonstrated live. Do not say they have. There is no evidence of a trained model, real restaurant forecast accuracy, or a deployed pilot. Keep those claims separate from the working local backend.

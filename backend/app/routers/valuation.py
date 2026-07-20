from fastapi import APIRouter

from app.schemas.valuation import ValuationRequest, ValuationResponse
from app.services import event_bus
from app.services.valuation_service import check_valuation

router = APIRouter()


@router.post(
    "/tools/valuation",
    response_model=ValuationResponse,
    operation_id="checkValuation",
    description="Compare an asking price against HDB resale transactions from the past 5 years for the same town and flat type. Optionally pass floor_level (low/mid/high) to narrow the comparison to similar-floor units when the buyer cares about floor level.",
)
def check_valuation_endpoint(request: ValuationRequest) -> ValuationResponse:
    floor_note = f" (floor level: {request.floor_level})" if request.floor_level else ""
    area_note = f" ({request.floor_area_sqm:.0f} sqm)" if request.floor_area_sqm else ""
    event_bus.publish(
        "valuation",
        "start",
        f"Checking whether ${request.asking_price:,} is fair for a {request.flat_type} in "
        f"{request.town}{area_note}{floor_note}...",
    )
    result = check_valuation(request)
    if result.valuation_verdict == "insufficient_data":
        done_message = "No comparable transactions found — pricing fairness can't be assessed for this listing."
    else:
        verdict_label = result.valuation_verdict.replace("_", " ").title()
        done_message = (
            f"{verdict_label} — {result.premium_pct:+.1f}% vs ${result.median_transacted_price:,} "
            f"median across {result.comparable_transactions} transaction(s)"
        )
    event_bus.publish("valuation", "done", done_message)
    return result

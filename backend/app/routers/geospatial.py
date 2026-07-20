from fastapi import APIRouter

from app.schemas.geospatial import GeospatialRequest, GeospatialResponse
from app.services import event_bus
from app.services.geo_service import lookup_amenities

router = APIRouter()


@router.post(
    "/tools/geospatial",
    response_model=GeospatialResponse,
    operation_id="lookupAmenities",
    description="Geocode an address and list nearby amenities (MRT, schools, hawker centres) within a radius.",
)
def lookup_amenities_endpoint(request: GeospatialRequest) -> GeospatialResponse:
    amenity_list = ", ".join(a.replace("_", " ") for a in request.amenity_types)
    event_bus.publish(
        "geospatial",
        "start",
        f"Looking up {amenity_list} near {request.address} (within {request.radius_m}m)...",
    )
    result = lookup_amenities(request)
    event_bus.publish("geospatial", "done", result.amenity_summary)
    return result

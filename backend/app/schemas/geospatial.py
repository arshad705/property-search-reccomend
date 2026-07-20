from pydantic import BaseModel


class GeospatialRequest(BaseModel):
    address: str
    amenity_types: list[str]
    radius_m: int = 1000


class Coordinates(BaseModel):
    lat: float
    lng: float


class Amenity(BaseModel):
    name: str
    type: str
    distance_m: int


class GeospatialResponse(BaseModel):
    coordinates: Coordinates
    amenities: list[Amenity]
    amenity_summary: str

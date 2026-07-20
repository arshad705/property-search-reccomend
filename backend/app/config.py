from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://hdb_advisor:hdb_advisor@localhost:5433/hdb_advisor"

    rapidapi_key: str = ""
    rapidapi_host: str = "99-co-sg-api.p.rapidapi.com"

    data_gov_sg_resource_id: str = "d_8b84c4ee58e3cfc0ece0d773c8ca6abc"

    # Google Places API (New) + Geocoding API — replaced OneMap entirely, since
    # OneMap's Themes catalog had no MRT station or school data (only hawker
    # centres). Requires a Google Cloud billing account even for free-tier use.
    google_maps_api_key: str = ""

    use_fixtures: bool = True

    # watsonx Orchestrate — used by the chat endpoint to run the supervisor_agent.
    # Auth type is inferred from the URL by IAMAuthenticator/MCSPAuthenticator the
    # same way the ADK CLI does: URLs containing "cloud.ibm.com" use IBM Cloud IAM.
    wxo_instance_url: str = ""
    wxo_api_key: str = ""
    wxo_iam_url: str = ""
    wxo_agent_name: str = "supervisor_agent"


settings = Settings()

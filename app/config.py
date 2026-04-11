from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    webhook_bearer_token: str = "my_super_secret_college_key"
    firebase_credentials_path: str = ""
    firebase_service_account_json: str = ""
    # Comma-separated Firebase UIDs with full admin (all merchants / all orders)
    flowpay_admin_uids: str = ""


settings = Settings()


def admin_uid_set() -> frozenset[str]:
    raw = (settings.flowpay_admin_uids or "").strip()
    if not raw:
        return frozenset()
    return frozenset(x.strip() for x in raw.split(",") if x.strip())

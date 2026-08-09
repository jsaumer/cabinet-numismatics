from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://numis:changeme@localhost:5432/numismatics"
    photo_dir: str = "./photos"
    # Re-run stale melt estimates this often (days); 0 disables the scheduler.
    reestimate_days: int = 7
    # Fernet key(s) encrypting stored secrets; comma-separated to rotate (the
    # first encrypts, any decrypts). Unset → a key is generated into
    # secret_key_file, which must stay off the publicly served photo volume.
    secret_key: str = ""
    secret_key_file: str = "/data/state/secret.key"

    @property
    def sqlalchemy_url(self) -> str:
        # Compose/.env use the generic scheme; SQLAlchemy needs the psycopg 3 driver.
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()

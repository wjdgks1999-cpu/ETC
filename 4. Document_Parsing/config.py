import os
from dotenv import load_dotenv

# Initialize environment variables
load_dotenv()

class Settings:
    """
    Application settings loaded from environment variables.
    Using a class for better organization, even without pydantic.
    """
    @property
    def UPSTAGE_API_KEY(self) -> str :
        key = os.getenv("UPSTAGE_API_KEY")
        if not key:
            raise ValueError("UPSTAGE_API_KEY environment variable is not set")
        return key

# Global settings instance
settings = Settings()
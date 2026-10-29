import os
from dotenv import load_dotenv

# Initialize environment variables
load_dotenv()

class Settings:
    """
    Application settings loaded from environment variables.
    """
    @property
    def UPSTAGE_API_KEY(self) -> str :
        key = os.getenv("UPSTAGE_API_KEY")
        if not key:
            raise ValueError("UPSTAGE_API_KEY environment variable is not set")
        return key
    
    @property
    def GEMINI_API_KEY(self) -> str:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        return key
    
# Global settings instance
settings = Settings()
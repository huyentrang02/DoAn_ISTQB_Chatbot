import os
from dotenv import load_dotenv

# Load env from .env file explicitly if needed, or rely on system env
load_dotenv()

class Settings:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    
    def validate(self):
        missing = []
        if not self.GOOGLE_API_KEY: missing.append("GOOGLE_API_KEY")
        if not self.SUPABASE_URL: missing.append("SUPABASE_URL")
        if not self.SUPABASE_KEY: missing.append("SUPABASE_KEY")
        
        if missing:
            raise ValueError(f"Missing environment variables: {', '.join(missing)}. Please check your backend/.env file.")

settings = Settings()
settings.validate() # Validate on startup

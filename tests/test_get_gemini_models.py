import os
from dotenv import load_dotenv

# Load .env file explicitly
load_dotenv()

from services.system_manager import ConfigManager

def test_fetch_gemini_models():
    api_key = os.getenv("GOOGLE_API_KEY")
    print(f"API Key present: {bool(api_key)}")
    
    # Clear cache
    ConfigManager._cached_gemini_models = None
    
    models = ConfigManager.get_gemini_models()
    print(f"Returned models count: {len(models)}")
    print("Returned models list:")
    for m in models:
        print(f"  - {m}")
        
    print("\n--- Direct API List Check ---")
    if api_key:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            all_models = list(client.models.list())
            print(f"Total models returned by Google GenAI API: {len(all_models)}")
            for m in all_models:
                print(f"  API Model Name: {m.name}, Display: {getattr(m, 'display_name', '')}")
        except Exception as e:
            print(f"Direct API call error: {e}")

if __name__ == "__main__":
    test_fetch_gemini_models()

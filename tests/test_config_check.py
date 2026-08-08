from services.system_manager import ConfigManager

def test_model_config():
    print("Checking model configurations loaded by ConfigManager:")
    summarizer = ConfigManager.get_model("summarizer")
    planner = ConfigManager.get_model("planner")
    refiner = ConfigManager.get_model("refiner")
    shorts = ConfigManager.get_model("shorts")
    map_model = ConfigManager.get_model("summarizer_map")
    reduce_model = ConfigManager.get_model("summarizer_reduce")
    
    print(f"  - Summarizer       : {summarizer}")
    print(f"  - Planner          : {planner}")
    print(f"  - Refiner          : {refiner}")
    print(f"  - Shorts           : {shorts}")
    print(f"  - Summarizer Map   : {map_model}")
    print(f"  - Summarizer Reduce: {reduce_model}")
    
    assert summarizer == "gemini-3.5-flash-lite"
    assert planner == "gemini-3.1-flash-lite"
    assert refiner == "gemini-3.1-flash-lite"
    assert shorts == "gemini-3.5-flash-lite"
    print("All model assertions passed successfully!")

if __name__ == "__main__":
    test_model_config()

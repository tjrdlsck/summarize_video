import json
import os

class PromptFactory:
    """
    VideoMode에 따른 시스템 지침 및 JSON Schema를 동적으로 주입하는 팩토리 클래스.
    """
    MODES_DIR = os.path.join(os.path.dirname(__file__), "modes")

    @classmethod
    def get_mode_config(cls, mode_name: str = "sermon") -> dict:
        """
        주어진 모드 이름에 해당하는 설정(JSON)을 로드합니다.
        기본값은 'sermon'입니다.
        """
        file_name = f"{mode_name.lower()}.json"
        file_path = os.path.join(cls.MODES_DIR, file_name)

        if not os.path.exists(file_path):
            print(f"[PromptFactory] Warning: Mode '{mode_name}' not found. Falling back to 'sermon'.")
            file_path = os.path.join(cls.MODES_DIR, "sermon.json")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[PromptFactory] Error loading mode config: {e}")
            return {}

    @classmethod
    def create_summarize_prompt(cls, segments: list[dict], mode_name: str = "sermon") -> tuple[str, dict]:
        """
        모드에 따른 시스템 지시문과 스키마를 반환합니다.
        
        Returns:
            (system_instruction, response_schema, script_text)
        """
        config = cls.get_mode_config(mode_name)
        
        # 스크립트 데이터 포맷팅
        lines = [f"{seg['id']} | {seg['text']}" for seg in segments]
        script_text = "\n".join(lines)
        
        system_instruction = config.get("system_instruction", "")
        response_schema = config.get("response_schema", {})

        return system_instruction, response_schema, script_text

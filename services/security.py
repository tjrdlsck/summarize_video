import re
import os
from fastapi import HTTPException

class SecurityManager:
    """
    보안 관련 검증 로직을 담당하는 클래스.
    '화이트리스트' 방식을 사용하여 허용되지 않은 모든 패턴을 거부합니다.
    """
    
    # 허용되는 문자: 한글, 영문, 숫자, 점(.), 하이픈(-), 언더스코어(_)
    # 그 외의 모든 문자(특히 /, \, .. 등 경로 조작 문자)는 거부함
    SAFE_FILENAME_PATTERN = r'^[a-zA-Z0-9ㄱ-ㅎ가-힣._-]+$'

    @classmethod
    def validate_filename(cls, filename: str):
        """
        파일명의 안전성을 검사합니다. 안전하지 않으면 400 에러를 발생시킵니다.
        """
        if not filename:
            raise HTTPException(status_code=400, detail="파일명이 누락되었습니다.")

        # 1. 정규표현식 검사 (허용된 문자만 있는지 확인)
        if not re.match(cls.SAFE_FILENAME_PATTERN, filename):
            raise HTTPException(
                status_code=400, 
                detail=f"안전하지 않은 파일명이 탐지되었습니다: '{filename}'. "
                       f"특수문자나 공백을 제거하고 영문, 숫자, 한글만 사용해 주세요."
            )

        # 2. 경로 탐색 방어 (상위 디렉토리 참조 차단)
        # basename을 취했을 때 원본과 다르면 경로 정보가 포함된 것으로 간주
        if os.path.basename(filename) != filename:
             raise HTTPException(
                status_code=400, 
                detail="파일명에 경로 정보(/, \\)가 포함될 수 없습니다."
            )

        return True

import asyncio
import os
import sys
import pytest
from services.clipper import VideoClipper

pytestmark = pytest.mark.anyio

async def test_merge():
    clipper = VideoClipper()
    print("Testing VideoClipper GPU detection:")
    print(f"  - NVENC available: {clipper._is_nvenc_available()}")
    print(f"  - CUDA HWACCEL available: {clipper._is_cuda_hwaccel_available()}")

if __name__ == "__main__":
    asyncio.run(test_merge())

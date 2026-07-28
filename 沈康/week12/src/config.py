from pathlib import Path

from loguru import logger

REACT_FUNCTION_CALLING_CONTEXT = []
REACT_MANUAL_CONTEXT = []

ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "outputs"
OUTPUT_LOG = OUTPUT_DIR / "Print.log"


def add_message(message):
    REACT_MANUAL_CONTEXT.append(message)
    REACT_FUNCTION_CALLING_CONTEXT.append(message)


logger.add(OUTPUT_LOG, rotation="100 MB")


def print_log(mode):
    logger.info(f"###################### 历史信息如下：###################### ")
    if mode == "manual":
        logger.info(REACT_MANUAL_CONTEXT)
    else:
        logger.info(REACT_FUNCTION_CALLING_CONTEXT)
    logger.info("")

"""
ULTRON VISION - Main Entry Point
AI Camera Surveillance System
"""

import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("mother_vision.log")
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Main entry point"""
    logger.info("=" * 50)
    logger.info("ULTRON VISION - AI Camera Surveillance System")
    logger.info("=" * 50)
    
    from src.api import run_server
    run_server()


if __name__ == "__main__":
    main()


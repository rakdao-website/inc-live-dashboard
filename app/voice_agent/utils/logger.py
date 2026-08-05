import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def log_info(msg):
    logger.info(msg)

def log_error(msg):
    logger.error(msg)
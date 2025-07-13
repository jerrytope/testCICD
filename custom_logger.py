import logging
import os
from datetime import datetime

def setup_logger(name, level=logging.INFO):
    """Setup a logger with file and console handlers."""
    # Create logs directory if it doesn't exist
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid adding handlers if they already exist
    if logger.handlers:
        return logger
    
    # Create formatters
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create file handlers
    debug_handler = logging.FileHandler(os.path.join(log_dir, 'debug.log'))
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(formatter)
    
    info_handler = logging.FileHandler(os.path.join(log_dir, 'info.log'))
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)
    
    warning_handler = logging.FileHandler(os.path.join(log_dir, 'warning.log'))
    warning_handler.setLevel(logging.WARNING)
    warning_handler.setFormatter(formatter)
    
    error_handler = logging.FileHandler(os.path.join(log_dir, 'error.log'))
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    # Add handlers to logger
    logger.addHandler(debug_handler)
    logger.addHandler(info_handler)
    logger.addHandler(warning_handler)
    logger.addHandler(error_handler)
    logger.addHandler(console_handler)
    
    return logger 
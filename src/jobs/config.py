import os
import sys
import logging
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(_file_).resolve().parents[2]))

from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI

# Logger Setup

logger = logging.getLogger("configuration")

if _name_ == "_main_":
    # Initialize ServiceNow API with credentials
    username = "admin"
    password = "jSsW$6aRd$E8"
    snow = ServicenowAPI(username, password)
    ritm_sys_id = "bed16448c324f210d0d2f64d05013161"

    # --- Create SC Task Configuration ---
    task_id_1 = snow.create_sctask(
        ritm_sys_id,
        "Configuration Auto Sc task",
        "This SC Task was created via external script"
    )

    if task_id_1:
        logger.info(f"SC Task created successfully: {task_id}")
    else:
        logger.info(f"SC Task Creation Failed")

        # --- Close SC Task ---
    result_1 = snow.close_sctask(task_id, "Closing SC Task after test")
        if result_1:
            logger.info(f"SC Task {task_id} closed successfully")
        else:
            logger.error(f"Failed to close SC Task {task_id}")

    task_id_1 = snow.create_sctask(
        ritm_sys_id,
        "Configuration Auto Sc task",
        "This SC Task was created via external script"
    )

    if task_id_1:
        logger.info(f"SC Task created successfully: {task_id}")
    else:
        logger.info(f"SC Task Creation Failed")

        # --- Close SC Task ---
    result_1 = snow.close_sctask(task_id, "Closing SC Task after test")
        if result_1:
            logger.info(f"SC Task {task_id} closed successfully")
        else:
            logger.error(f"Failed to close SC Task {task_id}")
import os
from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parents[2]


def load_transaction_schema(account_name):
    """读取流水信息schema"""
    config_file = os.path.join(ROOT_DIR, "ledger/config/transaction_schema.yaml")

    with open(config_file, "r") as file:
        schema = yaml.safe_load(file)[account_name]
    return schema
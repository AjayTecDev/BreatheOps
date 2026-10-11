"""Seed the demo school into a REAL DynamoDB table. Uses your AWS credentials from the environment/SSO.
  TABLE=<table> AWS_REGION=<region> python3 backend/scripts/seed_table.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import boto3
from breatheops.config import Settings
from breatheops.repository import DynamoRepository
from breatheops import seed

cfg = Settings.from_env()   # table + region only; no validation needed for seeding
if not cfg.table: sys.exit("Set TABLE")
seed.seed_repository(DynamoRepository(boto3.resource("dynamodb", region_name=cfg.aws_region or None).Table(cfg.table)))
print("seeded", seed.SCHOOL_ID, "into", cfg.table)

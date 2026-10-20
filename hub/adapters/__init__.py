"""Adapters turn one source into a list of records for one table.

Each adapter module exposes:
    run(src: dict, ctx: dict) -> dict(records=[...], warnings=[...], pages_failed=int)
ctx carries: session, previous (this source's records from the last run, keyed by id), fx.
"""
from . import shopify, native_extracts, open_beauty_facts, cosing_checker

ADAPTERS = {
    "shopify": shopify,
    "native_extracts": native_extracts,
    "open_beauty_facts": open_beauty_facts,
    "cosing_checker": cosing_checker,
}

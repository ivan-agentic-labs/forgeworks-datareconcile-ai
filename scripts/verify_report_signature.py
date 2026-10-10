#!/usr/bin/env python3
"""Verify a report attestation offline using independent trust and expected binding."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/api/src'))
from datareconcile_ai.domain.report_signatures import verify_report_attestation, ReportSignatureError


def read(path, limit):
    with open(path, 'rb') as source:
        data = source.read(limit + 1)
    if len(data) > limit: raise ValueError('Input budget exceeded')
    return data.decode('utf-8')


def unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result: raise ValueError('Duplicate JSON key')
        result[name] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--envelope',required=True)
    parser.add_argument('--public-key',required=True)
    parser.add_argument('--expected-binding',required=True)
    args = parser.parse_args()
    try:
        envelope = json.loads(read(args.envelope, 4*1024*1024),object_pairs_hook=unique)
        binding = json.loads(read(args.expected_binding, 16384),object_pairs_hook=unique)
        payload = verify_report_attestation(envelope,read(args.public_key,16384),binding)
    except (OSError, ValueError, RecursionError):
        print('Report attestation verification failed',file=sys.stderr)
        return 1
    print(json.dumps({'verification':'PASS','artifact_sha256':payload['artifact_sha256']}))
    return 0


if __name__ == '__main__': raise SystemExit(main())

"""Ed25519 report attestation with independently supplied verification trust."""
import base64
import hashlib
import json
import math
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

MAX_BYTES = 2 * 1024 * 1024
BINDING_FIELDS = {'tenant_id', 'report_id', 'run_id', 'artifact_sha256'}
PAYLOAD_FIELDS = BINDING_FIELDS | {'schema_version', 'ledger_sha256', 'source_revision', 'approved_summary_sha256', 'run_version', 'finalized_at', 'report_json'}


class ReportSignatureError(ValueError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _bytes(text):
    if not isinstance(text, str): raise ReportSignatureError('REPORT_INVALID_TEXT')
    try: data = text.encode('utf-8')
    except UnicodeError as error: raise ReportSignatureError('REPORT_INVALID_UNICODE') from error
    if len(data) > MAX_BYTES: raise ReportSignatureError('REPORT_BUDGET_EXCEEDED')
    return data


def _check_report_content_consistency(payload):
    """Bind signed report metadata to the independently parsable report body."""
    raw = payload['report_json']
    if not isinstance(raw, str):
        raise ReportSignatureError('REPORT_CONTENT_INVALID')

    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ReportSignatureError('REPORT_CONTENT_DUPLICATE_KEY')
            result[name] = value
        return result

    def nonfinite(_):
        raise ReportSignatureError('REPORT_CONTENT_NONFINITE_NUMBER')

    def finite_float(number):
        # json.loads otherwise converts an exponent such as 1e999 to infinity
        # even when parse_constant rejects literal Infinity and NaN.
        value = float(number)
        if not math.isfinite(value):
            raise ReportSignatureError('REPORT_CONTENT_NONFINITE_NUMBER')
        return value

    try:
        content = json.loads(raw, object_pairs_hook=unique,
                             parse_constant=nonfinite, parse_float=finite_float)
    except ReportSignatureError:
        raise
    except (ValueError, RecursionError, TypeError):
        raise ReportSignatureError('REPORT_CONTENT_INVALID') from None

    required = {'source_revision', 'rule_version', 'totals', 'approved_summary_sha256'}
    if (
        not isinstance(content, dict)
        or set(content) != required
        or not isinstance(content['totals'], dict)
        or not isinstance(content['rule_version'], str)
    ):
        raise ReportSignatureError('REPORT_CONTENT_SCHEMA_INVALID')
    if (content['source_revision'] != payload['source_revision']
            or content['approved_summary_sha256'] != payload['approved_summary_sha256']):
        raise ReportSignatureError('REPORT_CONTENT_BINDING_MISMATCH')
    if payload['ledger_sha256'] != payload['artifact_sha256']:
        raise ReportSignatureError('REPORT_LEDGER_DIGEST_MISMATCH')


def attest_report(report, tenant_id, private_key_pem):
    body = _bytes(report['content_json'])
    if not body or hashlib.sha256(body).hexdigest() != report['artifact_sha']:
        raise ReportSignatureError('REPORT_INTEGRITY_FAILURE')
    if not isinstance(private_key_pem, str) or not private_key_pem or len(private_key_pem) > 16384:
        raise ReportSignatureError('REPORT_SIGNING_KEY_UNAVAILABLE')
    try:
        key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey): raise ValueError('Wrong signing algorithm')
    except (ValueError, TypeError, UnicodeError, UnsupportedAlgorithm) as error:
        raise ReportSignatureError('REPORT_SIGNING_KEY_UNAVAILABLE') from error
    fields = {'schema_version':'report-attestation-v1', 'tenant_id':tenant_id,
        'report_id':report['id'], 'run_id':report['run_id'], 'artifact_sha256':report['artifact_sha'],
        'ledger_sha256':report['ledger_sha'], 'source_revision':report['source_revision'],
        'approved_summary_sha256':report['approved_summary_sha'], 'run_version':report['run_version'],
        'finalized_at':report['finalized_at'], 'report_json':report['content_json']}
    _check_report_content_consistency(fields)
    # Never emit an attestation that the independent verifier must reject.
    # A bool is an int subclass in Python but is not a valid run version.
    if type(fields['run_version']) is not int or fields['run_version'] < 1:
        raise ReportSignatureError('REPORT_PAYLOAD_INVALID')
    for field in PAYLOAD_FIELDS - {'run_version'}:
        _bytes(fields[field])
    payload = _json(fields)
    encoded = _bytes(payload)
    public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return {'algorithm':'Ed25519', 'key_sha256':hashlib.sha256(public).hexdigest(),
        'signed_payload':payload, 'signed_payload_sha256':hashlib.sha256(encoded).hexdigest(),
        'signature':base64.urlsafe_b64encode(key.sign(encoded)).decode()}


def verify_report_attestation(envelope, trusted_public_key_pem, expected_binding):
    """The envelope never chooses the trusted key or independently expected report."""
    if not isinstance(expected_binding, dict) or not BINDING_FIELDS <= expected_binding.keys():
        raise ReportSignatureError('REPORT_EXPECTED_BINDING_REQUIRED')
    if not isinstance(envelope, dict) or set(envelope) != {'algorithm','key_sha256','signed_payload','signed_payload_sha256','signature'}:
        raise ReportSignatureError('REPORT_ENVELOPE_INVALID')
    if envelope['algorithm'] != 'Ed25519': raise ReportSignatureError('REPORT_ALGORITHM_INVALID')
    try:
        if not isinstance(trusted_public_key_pem, str) or len(trusted_public_key_pem) > 16384: raise ValueError('Invalid key')
        key = serialization.load_pem_public_key(trusted_public_key_pem.encode())
        if not isinstance(key, Ed25519PublicKey): raise ValueError('Wrong key type')
    except (ValueError, TypeError, UnicodeError, UnsupportedAlgorithm) as error:
        raise ReportSignatureError('REPORT_TRUSTED_KEY_INVALID') from error
    public = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if hashlib.sha256(public).hexdigest() != envelope['key_sha256']: raise ReportSignatureError('REPORT_KEY_MISMATCH')
    body = _bytes(envelope['signed_payload'])
    if hashlib.sha256(body).hexdigest() != envelope['signed_payload_sha256']: raise ReportSignatureError('REPORT_PAYLOAD_DIGEST_MISMATCH')
    try:
        signature = envelope['signature']
        if not isinstance(signature, str) or len(signature) != 88: raise ValueError('Invalid signature')
        decoded = base64.b64decode(signature, altchars=b'-_', validate=True)
        if len(decoded) != 64 or base64.urlsafe_b64encode(decoded).decode() != signature: raise ValueError('Noncanonical signature')
        key.verify(decoded, body)
    except (ValueError, TypeError, InvalidSignature) as error:
        raise ReportSignatureError('REPORT_SIGNATURE_INVALID') from error
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result: raise ReportSignatureError('REPORT_DUPLICATE_JSON_KEY')
            result[name] = value
        return result
    def nonfinite(_): raise ReportSignatureError('REPORT_NONFINITE_NUMBER')
    try: payload = json.loads(body, object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, RecursionError) as error: raise ReportSignatureError('REPORT_PAYLOAD_INVALID') from error
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_FIELDS or payload['schema_version'] != 'report-attestation-v1':
        raise ReportSignatureError('REPORT_PAYLOAD_INVALID')
    if any(name not in payload or type(payload[name]) is not type(value) or payload[name] != value
           for name, value in expected_binding.items()):
        raise ReportSignatureError('REPORT_BINDING_MISMATCH')
    if type(payload['run_version']) is not int or payload['run_version'] < 1:
        raise ReportSignatureError('REPORT_PAYLOAD_INVALID')
    for name in PAYLOAD_FIELDS - {'run_version'}:
        _bytes(payload[name])
    if hashlib.sha256(_bytes(payload['report_json'])).hexdigest() != payload['artifact_sha256']:
        raise ReportSignatureError('REPORT_CONTENT_DIGEST_MISMATCH')
    _check_report_content_consistency(payload)
    return payload
